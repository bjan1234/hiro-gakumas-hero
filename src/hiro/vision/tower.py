"""偶像之路（Idol Road）考试页的识别：顶部 6 人名次条（1st–6th）上自己的名次和分数、各人的实时分数。

和 H.I.F 的区别：选拔赛顶部是突破线 + 多人分数，本战是 3 人名次条；偶像之路是 6 人名次条，3rd 和 4th 之间有一道分隔线
（星按名次给：★ 3 位以上、★★ 2 位以上、★★★ 1 位，8a3a1e7 11-14）。自己那一列比 NPC 宽、青色底、名次字更大，
位置随名次变；屏幕中间的大数字是本回合加分的动画，不是总分（Mac 15 层实机：读成 5,442，实际 34,368）。

名次条的布局是固定的（Mac 实机帧量出来，720x1280 坐标）：右缘约 x=710，NPC 列宽 69、自己那列 127（含白框外沿），
列间 2，3rd / 4th 之间多 13。所以自己排第 r 名时 6 列的位置都定了：r 取 1–6 各试一次，「自己那列」青色底最多的就是 r。
分数在每列底部，NPC 的五位数会往右溢出到下一列约 10 像素，所以读数框不跨到下一列数字开始的地方。
读出来的分数必须从左到右不增（名次条按分数排）：违反的那一格（被特效线挡住少读一位等）给 None，不猜。
"""

from __future__ import annotations

import cv2
import numpy as np

from hiro.vision.digits import read_number

RIGHT, NPC_W, ME_W, GAP, DIVIDER = 710, 69, 127, 2, 13
SCORE_Y = (126, 168)
ME_CYAN_MIN = 0.15  # 自己那列青色底比例：对的位置 0.18–0.20，其余 ≤ 0.13（Mac 实机 65 帧）；H.I.F 本战压暗帧 0.134
ROWS = 6


def layout(me: int) -> list[tuple[int, int, int]]:
    """自己排第 me 名时 6 列的 [(名次, 左, 右)]，从 1st 到 6th。"""
    cols, right = [], RIGHT
    for rank in range(ROWS, 0, -1):
        w = ME_W if rank == me else NPC_W
        cols.append((rank, right - w, right))
        right -= w + GAP + (DIVIDER if rank == 4 else 0)
    return sorted(cols)


def _cyan(hsv: np.ndarray, left: int, right: int) -> float:
    b = hsv[50:120, left + 4 : right - 40]
    return float(((b[..., 0] >= 85) & (b[..., 0] <= 105) & (b[..., 1] >= 120) & (b[..., 2] >= 150)).mean())


def my_rank(img: np.ndarray) -> tuple[int | None, float]:
    """自己的名次（1–6）和那一列的青色底比例；哪一列都不够青返回 (None, 最大比例)。"""
    hsv = cv2.cvtColor(img[:170], cv2.COLOR_BGR2HSV)
    best = max((_cyan(hsv, *layout(r)[r - 1][1:]), r) for r in range(1, ROWS + 1))
    return (best[1] if best[0] >= ME_CYAN_MIN else None), best[0]


def read_tower_ranking(img: np.ndarray) -> dict | None:
    """名次条 → {my_rank, my_score, scores[6]（1st→6th，读不出 / 不可信为 None）, top_score}；不是偶像之路名次条返回 None。"""
    me, _ = my_rank(img)
    if me is None:
        return None
    y1, y2 = SCORE_Y
    scores: list[int | None] = []
    for rank, left, right in layout(me):
        box = (left + 2, y1, min(720, right + 8), y2) if rank == me else (left + 6, y1, min(720, left + 80), y2)
        scores.append(read_number(img, box))
    for i in range(ROWS - 1):  # 名次条按分数排：比右边一格（名次更低）还小的读数不可信
        if scores[i] is not None and scores[i + 1] is not None and scores[i] < scores[i + 1]:
            scores[i] = None
    return {"my_rank": me, "my_score": scores[me - 1], "scores": scores, "top_score": scores[0]}


TURNS_MIN = 0.45  # 「残りターン」模板：偶像之路考试帧 0.58–0.9（Mac 实机 65 帧），非考试画面最高 0.21


def is_tower_exam(img: np.ndarray) -> bool:
    """偶像之路考试页：左上「残りターン」+ 没有突破线、不是本战 3 人名次条 + 6 人名次条里认得出自己那一列。"""
    from hiro.vision import hif

    if hif._match(img, "hif_exam_remaining_turns", (0, 0, 160, 45))[0] < TURNS_MIN:
        return False
    if hif.is_finals_strip(img) or hif._match_white(img, "hif_exam_breakthrough", hif.TOP_STRIP)[0] >= hif.BREAKTHROUGH_MIN:
        return False
    return my_rank(img)[0] is not None


# ---------------------------------------------------------------- 偶像之路的非考试页面（Mac 实机采样 11-14，.temp/tower-mac/frames）
# 判据都是整帧 OCR 的固定字样；字段只读画面上的，读不到给 None / 不写，不猜。boxes：[(去空格的文字, (x1, y1, x2, y2))]。
ATTRS = ("Vo", "Da", "Vi")


def _find(boxes, word: str, y=(0, 1280)):
    return next((b for t, b in boxes if word in t and y[0] <= (b[1] + b[3]) // 2 <= y[1]), None)


def _center(b) -> list[int]:
    return [int((b[0] + b[2]) // 2), int((b[1] + b[3]) // 2)]


def _int(text: str) -> int | None:
    import re

    m = re.search(r"\d[\d,]*", text)
    return int(m.group().replace(",", "")) if m else None


def _list_fields(boxes) -> dict:
    """路线列表：每张卡「STAGE n」、偶像名在下方约 215 像素、进度「x/81」再下约 60。"""
    import re

    idols = []
    for t, b in boxes:
        m = re.fullmatch(r"STAGE(\d+)", t)
        if not m:
            continue
        cx, cy = _center(b)
        name = next((t2 for t2, b2 in boxes if abs(_center(b2)[0] - cx) < 60 and 180 <= _center(b2)[1] - cy <= 250 and len(t2) >= 2
                     and not re.search(r"\d", t2)), None)  # fmt: skip
        prog = next((t2 for t2, b2 in boxes if re.fullmatch(r"\d+/\d+", t2) and abs(_center(b2)[0] - cx) < 90 and 240 <= _center(b2)[1] - cy <= 310), None)
        idols.append({"stage": int(m.group(1)), "name": name, "progress": prog, "center": [cx, cy]})
    return {"idols": idols}


def _formation_fields(boxes) -> dict:
    """编成页（挑戦する那页）：层号、回合数、三属性倍率 → 千分比（HIRO_TOWER_LOADOUT 的 score_bonus_permils）、体力上限、按钮。
    三属性倍率从上到下是 Vo / Da / Vi（ボーカル / ダンス / ビジュアル 那三行右侧的「2309%」）。"""
    import re

    out: dict = {}
    if (st := next((t for t, _ in boxes if re.fullmatch(r"STAGE\d+", t)), None)) is not None:
        out["layer"] = int(st[5:])
    turn_label = _find(boxes, "ターン", (60, 130))
    if turn_label is not None:
        tx = _center(turn_label)[0]
        out["turns"] = next((int(t) for t, b in boxes if t.isdigit() and abs(_center(b)[0] - tx) < 30 and 30 <= _center(b)[1] <= 80), None)
    pcts = sorted(((_center(b)[1], int(m.group(1))) for t, b in boxes if (m := re.fullmatch(r"\D?(\d{2,5})%", t)) and _center(b)[0] > 560), key=lambda x: x[0])
    if len(pcts) == 3:
        out["score_bonus_permils"] = [p * 10 for _, p in pcts]
    hp = _find(boxes, "体力", (500, 600))
    if hp is not None:
        out["max_stamina"] = next((int(t) for t, b in boxes if t.isdigit() and abs(_center(b)[0] - _center(hp)[0]) < 30 and 15 <= _center(b)[1] - _center(hp)[1] <= 50), None)
    for key, word in (("challenge", "挑戦する"), ("omakase", "おまかせ"), ("reset", "リセット")):
        if (b := _find(boxes, word, (1000, 1280))) is not None:
            out[key] = _center(b)  # おまかせ 只记位置，绝不点（用户 11-14：编成走我们的决策）
    return out


STAR_X = (250, 360, 470)
STAR_PINK_MIN = 0.2
LAYER_BOX = (280, 385, 440, 470)


def _result_fields(img: np.ndarray, boxes) -> dict:
    """结果页：过关（CLEAR）、层号（大字）、本次星数（三颗星里粉色的个数）、按钮。"""
    hsv = cv2.cvtColor(img[550:660], cv2.COLOR_BGR2HSV)
    stars = 0
    for x in STAR_X:  # 三颗星：拿到的粉色（约 0.46–0.50），没拿到的灰色（0）
        cell = hsv[:, x - 45 : x + 45]
        stars += int((((cell[..., 0] >= 150) | (cell[..., 0] <= 8)) & (cell[..., 1] >= 80) & (cell[..., 2] >= 150)).mean() >= STAR_PINK_MIN)
    layer = read_number(img, LAYER_BOX)  # 「CLEAR」下面的大号层号
    out = {"cleared": _find(boxes, "CLEAR", (150, 320)) is not None, "layer": layer, "stars": stars}
    for key, word in (("retry", "再挑戦"), ("back", "一覧に戻る"), ("next", "次へ")):
        if (b := _find(boxes, word, (1080, 1260))) is not None:
            out[key] = _center(b)
    return out


def tower_dialog(dialog: dict, boxes) -> tuple[str, dict] | None:
    """偶像之路的弹窗：层详情「条件」（每颗星的条件原文，8a3a1e7 按原文查表）、再挑戦确认（选项 / 按钮 / 消耗词）。"""
    from hiro.runtime.tower import retry_cost

    title, body = dialog.get("title", ""), dialog.get("body", "")
    if "条件" in title and "位" in body + "".join(t for t, _ in boxes):
        import re

        # 星按名次给：1 位 ★★★、2 位以上 ★★、3 位以上 ★（8a3a1e7 11-14）；条件原文交 8a3a1e7 按表查（26 / 27 层★3 另有通关时条件）
        conds = sorted(((b[1], t.lstrip("・•").strip()) for t, b in boxes if "クリア" in t), key=lambda x: x[0])
        rows = [{"star": 4 - int(m.group(1)) if (m := re.search(r"(\d)位", t)) else None, "text": t} for _, t in conds]
        return "TOWER_LAYER_INFO", {"conditions": rows,
                                     "close": _center(c) if (c := _find(boxes, "閉じる", (1080, 1260))) else None}  # fmt: skip
    if "再挑戦" in title and "ステージを再挑戦" in body + "".join(t for t, _ in boxes):
        out = {"cost": retry_cost(dialog)}
        for key, word in (("rebuild", "編成して再挑戦"), ("same", "同じ編成で再挑戦"), ("cancel", "キャンセル"), ("ok", "OK")):
            if (b := _find(boxes, word, (900, 1260))) is not None:
                out[key] = _center(b)
        return "TOWER_RETRY_CONFIRM", out
    return None


def tower_page(img: np.ndarray, boxes) -> tuple[str, dict] | None:
    """偶像之路的非弹窗页面（考试页由 is_tower_exam 判）。"""
    if _find(boxes, "アイドルへの道", (0, 120)) and _find(boxes, "STAGE", (600, 1100)):
        return "TOWER_LIST", _list_fields(boxes)
    if _find(boxes, "挑戦する", (900, 1100)) and _find(boxes, "ステージ別ランキング"):
        b = _find(boxes, "挑戦する", (900, 1100))
        name = next((t for t, bb in boxes if _center(bb)[1] < 200 and _center(bb)[0] < 220 and len(t) >= 3), None)
        stage = next((int(t[5:]) for t, _ in boxes if t.startswith("STAGE") and t[5:].isdigit()), None)
        return "TOWER_LAYERS", {"idol": name, "stage": stage, "challenge": _center(b)}
    if _find(boxes, "応援/トラブル", (0, 60)) and _find(boxes, "審査基準") and _find(boxes, "ターン", (60, 130)):
        return "TOWER_FORMATION", _formation_fields(boxes)
    if _find(boxes, "編成中") and _find(boxes, "審査基準"):
        dec = next((b for t, b in boxes if "決定" in t and _center(b)[1] > 1050), None)
        return "TOWER_MEMORY_SELECT", {"decide": _center(dec) if dec else None}
    if _find(boxes, "CLEAR", (150, 320)) and (_find(boxes, "一覧に戻る", (1080, 1260)) or _find(boxes, "再挑戦", (1080, 1260))):
        return "TOWER_RESULT", _result_fields(img, boxes)
    return None
