"""N.I.A 特有页面的识别（整帧 OCR 文字 + 少量像素）：営業场所、営業话题、试镜选档。字段按 3940a9 的决策接口（hiro.brain.deciders
sales_place / sales_event / audition_select）。实机样本：tests/fixtures/pages/nia-*（协调 11-17 N.I.A 采样）。

- NIA_SALES_PLACE：「営業先を選択してください」，三张场所卡（自治体イベント会場 黄 / 企業イベント会場 青绿 / 商業施設 紫 / リゾート 绿），
  每张 {index, kind, name, gain, hp_cost, center}；点一张会展开（大成功ボーナス、獲得報酬、「営業開始」），expanded / selected / start。
- NIA_SALES_EVENT：左上「営業」标签 + 2–3 个话题按钮（左侧图标颜色 = 属性：粉 Vo / 蓝 Da / 黄 Vi）+ 下方对话框。choices {index, attr, text, center}。
- NIA_AUDITION_SELECT：「オーディションを選択してください」，几条试镜横幅，下面写门槛（「9,000以上」「条件なし」）。
  tiers {index（屏幕从上到下）, number（按门槛从低到高 1..n）, vote_need, locked, center}；votes：右上的当前投票数。
  点一条会展开（评价、推奨投票数ランク、横幅上「オーディション開始」）：expanded / chosen_need / start。
"""

from __future__ import annotations

import re

import cv2

PLACE_KINDS = (("自治体", "local"), ("企業", "corporate"), ("商業", "commercial"), ("ゾート", "resort"))  # 「リゾート施設」展开时 OCR 读成「ノゾート施談」
ICON_ATTR_HUE = {"Vo": (155, 180), "Da": (95, 120), "Vi": (12, 35)}  # 话题按钮左侧圆形图标：粉 / 蓝 / 黄
VOTES_BOX = (540, 120, 700, 170)  # 右上投票数（「4,680」，上面一行「9,000」是下一档目标）


def _t(texts):
    """[(text, (x1, y1, x2, y2))] 或 screen_texts 的 Text → [(去空格文字, cx, cy)]。"""
    out = []
    for t in texts:
        if hasattr(t, "rect"):
            out.append((t.text.replace(" ", ""), t.rect.center.x, t.rect.center.y))
        else:
            s, b = t[0], t[-1]
            out.append((s.replace(" ", ""), (b[0] + b[2]) // 2, (b[1] + b[3]) // 2))
    return out


def _num(s: str) -> int | None:
    m = re.search(r"\d[\d,]*", s)
    return int(m.group(0).replace(",", "")) if m else None


def read_sales_place(texts) -> dict | None:
    tx = _t(texts)
    titles = []
    for s, x, y in tx:
        kind = next((k for w, k in PLACE_KINDS if w in s), None)
        if kind and x < 360 and ("会場" in s or "施設" in s or "施談" in s or "ゾート" in s):
            titles.append((y, kind, s))
    has_prompt = any("営業先を選択" in s for s, _, _ in tx)
    start = next(((x, y) for s, x, y in tx if "営業開始" in s), None)
    if len(titles) < 2 or not (has_prompt or start):
        return None
    titles.sort()
    places = []
    for i, (y, kind, name) in enumerate(titles):
        gain = next((_num(s) for s, x, yy in tx if s.startswith("+") and 20 <= yy - y <= 80 and x < 360), None)
        cost_txt = next((s for s, x, yy in tx if x > 420 and 20 <= yy - y <= 90 and ("消費なし" in s or re.fullmatch(r"-?\d{1,2}", s))), None)
        hp = 0 if cost_txt and "なし" in cost_txt else (_num(cost_txt) if cost_txt else None)
        places.append({"index": i, "kind": kind, "name": name, "gain": gain, "hp_cost": hp, "center": [360, y + 40]})
    out = {"places": places, "expanded": start is not None}
    if start is not None:
        bonus_y = next((y for s, _, y in tx if "大成功" in s), start[1])
        sel = [p for p in places if p["center"][1] - 40 < bonus_y]
        out["selected"] = sel[-1]["index"] if sel else None
        out["start"] = list(start)
    return out


def _icon_attr(img, y: int) -> str | None:
    """话题按钮左侧的圆形图标（x 40–90）主色 → 属性。"""
    if img is None:
        return None
    hsv = cv2.cvtColor(img[max(0, y - 22) : y + 22, 40:95], cv2.COLOR_BGR2HSV)
    sat = (hsv[..., 1] >= 120) & (hsv[..., 2] >= 150)
    if sat.sum() < 60:
        return None
    hue = hsv[..., 0][sat]
    best = max(ICON_ATTR_HUE, key=lambda a: int(((hue >= ICON_ATTR_HUE[a][0]) & (hue <= ICON_ATTR_HUE[a][1])).sum()))
    lo, hi = ICON_ATTR_HUE[best]
    return best if int(((hue >= lo) & (hue <= hi)).sum()) >= 40 else None


def read_sales_event(texts, img=None) -> dict | None:
    tx = _t(texts)
    if not any(s == "営業" and x < 180 and y < 140 for s, x, y in tx):
        return None
    opts = sorted((y, s, x) for s, x, y in tx if 600 <= y <= 960 and 90 <= x <= 470 and len(s) >= 3 and not re.fullmatch(r"[\d/,.%+-]+", s))
    if len(opts) < 2:
        return None
    choices = [{"index": i, "text": s, "attr": _icon_attr(img, y), "center": [360, y]} for i, (y, s, x) in enumerate(opts)]
    for c in choices:
        if c["attr"] is None:  # 图标认不出时按文字（「ボーカル / ダンス / ビジュアル」）
            c["attr"] = next((a for w, a in (("ボーカル", "Vo"), ("ダンス", "Da"), ("ビジュアル", "Vi")) if w in c["text"]), None)
    return {"choices": choices}


def read_votes(img) -> int | None:
    if img is None:
        return None
    from hiro.vision.ocr import screen_texts

    x1, y1, x2, y2 = VOTES_BOX
    nums = [_num(t.text) for t in screen_texts(img, (x1, y1, x2 - x1, y2 - y1)) if re.fullmatch(r"[\d,]+", t.text.replace(" ", ""))]
    return next((n for n in nums if n is not None), None)


STAGE_WORDS = (("最終", "final"), ("2次", "mid2"), ("1次", "mid1"))


def _audition_stage(tx) -> str | None:
    """左上「1次 / 2次 / 最終」+「オーディション」（实机 OCR「1次」在 (68,97)）→ mid1 / mid2 / final；页中间的大标题也认。"""
    for s, x, y in tx:
        if y < 260:
            for w, stage in STAGE_WORDS:
                if w in s and (x < 200 or "オーディ" in s or "ション" in s or y > 180):
                    return stage
    return None


def read_audition_select(texts, img=None) -> dict | None:
    tx = _t(texts)
    prompt = any("オーディションを選択" in s for s, _, _ in tx)
    start = next(((x, y) for s, x, y in tx if "オーディション開始" in s), None)
    if not (prompt or start):
        return None
    labels = []
    for s, x, y in tx:
        if 250 <= x <= 470 and y >= 700:
            if "条件なし" in s:
                labels.append((y, 0))
            elif "以上" in s and (n := _num(s)) is not None:
                labels.append((y, n))
    if not labels:
        return None
    labels.sort()
    order = sorted({n for _, n in labels})
    tiers = [{"index": i, "number": order.index(n) + 1, "vote_need": n, "locked": False, "center": [360, y - 50]}
             for i, (y, n) in enumerate(labels)]  # fmt: skip
    out = {"tiers": tiers, "votes": read_votes(img), "expanded": start is not None, "stage": _audition_stage(tx)}
    if start is not None:
        below = [(y, n) for y, n in labels if 0 < y - start[1] < 120]
        out["chosen_need"] = below[0][1] if below else None
        out["start"] = list(start)
    return out


BONUS_TAP = (360, 1222)  # 「TAP」


def read_audition_bonus(texts) -> dict | None:
    """试镜结束后的「オーディションボーナス」（第 2 页再加「パラメータボーナス」、属性 +N、獲得スコア、底部「TAP」）：展示页，点 TAP 过。
    带金色标题条，原来判成 DIALOG、第 1 页判 unknown，16 秒后停（N.I.A 采样 11-17）。"""
    tx = _t(texts)
    if not any("オーディションボーナス" in s and y < 320 for s, _, y in tx):
        return None
    tap = next(((x, y) for s, x, y in tx if s == "TAP" and y > 1150), BONUS_TAP)
    return {"tap": list(tap), "param": any("パラメータボーナス" in s for s, _, _ in tx)}


def read_audition_result(texts) -> dict | None:
    """试镜结果（「最終オーディション」/「1次オーディション」大标题 + 名次 + 偶像名 + 底部「TAPで次へ」）：展示页，点 TAP 过。
    最终试镜第 1 名那一页原来判 unknown，16 秒后停（N.I.A 采样 11-17）。"""
    tx = _t(texts)
    title = next((s for s, _, y in tx if "オーディション" in s and "ボーナス" not in s and y < 420), None)
    tap = next(((x, y) for s, x, y in tx if s.startswith("TAP") and y > 1050), None)
    if title is None or tap is None:
        return None
    stage = next((st for w, st in STAGE_WORDS if w in title), None)
    return {"tap": list(tap), "stage": stage}


def read_briefing(texts, img=None) -> dict | None:
    """试镜考前说明页（審査基準 + 合格条件「1位」+ 三属性 >> 倍率 +「タップして次へ」）：版面和 H.I.F 的不一样（没有「突破ライン」，
    「合格条件」位置不同），H.I.F 的两条判据都没命中，判 unknown 停了（N.I.A 采样 11-17 最终试镜）。读数用 H.I.F 的
    read_exam_briefing（三属性和倍率），按快速判页的格式带上要点的位置，交主循环的 advance 点（同 H.I.F）。"""
    tx = _t(texts)
    if not (any("審査基準" in s for s, _, _ in tx) and any("合格条件" in s for s, _, _ in tx)):
        return None
    tap = next(((x, y) for s, x, y in tx if "タップして次へ" in s and y > 1100), None)
    if tap is None or img is None:
        return None  # 倍率还在跳（ボーナス演出）：没有「タップして次へ」先不认
    from hiro.vision.pages import read_exam_briefing

    boxes = [(t.text, tuple(int(v) for v in t.rect)) if hasattr(t, "rect") else (t[0], tuple(t[-1])) for t in texts]
    brief = read_exam_briefing(img, boxes)
    return {**brief, "_quick": {"page": "HIF_EXAM_BRIEFING", "tap": tap, "dispatch": None, "fields": brief}}


def read_nia_page(texts, img=None) -> tuple[str, dict] | None:
    """N.I.A 特有页面 → (页面名, 字段)；都不是 None。考前说明页借用 H.I.F 的页面名（HIF_EXAM_BRIEFING，同一种页）。"""
    if (bonus := read_audition_bonus(texts)) is not None:
        return "NIA_AUDITION_BONUS", bonus
    if (brief := read_briefing(texts, img)) is not None:
        return "HIF_EXAM_BRIEFING", brief
    if (res := read_audition_result(texts)) is not None:
        return "NIA_AUDITION_RESULT", res
    for name, fn in (("NIA_AUDITION_SELECT", lambda: read_audition_select(texts, img)), ("NIA_SALES_PLACE", lambda: read_sales_place(texts)),
                     ("NIA_SALES_EVENT", lambda: read_sales_event(texts, img))):  # fmt: skip
        if (f := fn()) is not None:
            return name, f
    return None


__all__ = ["read_nia_page", "read_sales_place", "read_sales_event", "read_audition_select", "read_votes"]
