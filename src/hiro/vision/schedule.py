"""考试审查日程面板（考试左上「残りターン / 属性 %」那块点开，客户端 ExamAuditionBonusScheduleView）的读数。

实拍（初 PRO 中間第 1 回合前，协调 11-18，fixtures pages/exam-schedule-panel-hajime-mid1.png）：白色弹窗，
- 标题「現在1ターン目」，下一行过线条件「3位以上またはスコア1700以上で中間試験突破」；
- 一行三属性倍率（图标 + 「644%」），y ≈ 250；
- 逐行「現在のターン / 1ターン後 … 8ターン後」+ 属性图标（x ≈ 231）+ 属性文字，行距 ≈ 88，一屏 9 行（更长的考试要往下滑）；
- 底部中间圆形 ✕（360, 1160）关闭。
属性按图标颜色认（用户 11-17：图标优先），认不出再看文字。读不到的项不给 / 给 None，不猜。
"""

from __future__ import annotations

import re

import cv2
import numpy as np

CLOSE = (360, 1160)  # 底部圆形 ✕
ICON_X = (205, 258)  # 每行属性图标的 x 范围
ICON_HALF_H = 20
ICON_MIN = 250  # 图标彩色像素（实测 1,000+）
ATTR_WORDS = (("ボーカル", "Vo"), ("ダンス", "Da"), ("ビジュアル", "Vi"))
PERMIL_Y = (225, 280)  # 三属性倍率那一行
PERMIL_X = ((60, 260), (260, 460), (460, 660))  # Vo / Da / Vi 三格（图标 + 数字，从左到右固定顺序）


def _attr_by_icon(hsv: np.ndarray, y: int) -> str | None:
    from hiro.vision.action import ATTR_HUE

    reg = hsv[max(0, y - ICON_HALF_H) : y + ICON_HALF_H, ICON_X[0] : ICON_X[1]]
    vivid = (reg[..., 1] > 120) & (reg[..., 2] > 150)
    hues = reg[..., 0][vivid]
    counts = {a: int(((hues >= lo) & (hues <= hi)).sum()) for a, (lo, hi) in ATTR_HUE.items()}
    best = max(counts, key=counts.get)
    return {"vo": "Vo", "da": "Da", "vi": "Vi"}[best] if counts[best] >= ICON_MIN else None


def _row_offset(text: str) -> int | None:
    """「現在のターン」→ 0，「3ターン後」→ 3；不是行标签 None。"""
    t = text.replace(" ", "")
    if "現在のターン" in t:
        return 0
    m = re.search(r"(\d{1,2})ターン後", t)
    return int(m.group(1)) if m else None


def read_schedule_panel(img: np.ndarray, texts=None) -> dict | None:
    """→ {current_turn, rows: {偏移: Vo/Da/Vi/None}, permil: {Vo, Da, Vi}（千分比，644% → 6440）, pass_rank, pass_score, close}；
    不是这个面板 None。texts：hiro.vision.ocr.screen_texts 的结果（不给就自己读）。"""
    if img is None or img.shape[:2] != (1280, 720):
        return None
    if texts is None:
        from hiro.vision.ocr import screen_texts

        texts = screen_texts(img)
    tx = [(t.text.replace(" ", ""), int(t.rect.center.x), int(t.rect.center.y)) for t in texts]
    cur = next((int(m.group(1)) for s, _, _ in tx if (m := re.search(r"現在(\d{1,2})ターン目", s))), None)
    labels = [(off, y) for s, x, y in tx if x < 200 and (off := _row_offset(s)) is not None]
    if cur is None and not labels:
        return None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    rows: dict[int, str | None] = {}
    for off, y in labels:
        attr = _attr_by_icon(hsv, y)
        if attr is None:
            word = next((s for s, x, yy in tx if x > 240 and abs(yy - y) <= 20), "")
            attr = next((a for w, a in ATTR_WORDS if w in word), None)
        rows[off] = attr
    permil = {}
    for (x1, x2), a in zip(PERMIL_X, ("Vo", "Da", "Vi")):
        num = next((int(m.group(1)) for s, x, y in tx if x1 <= x < x2 and PERMIL_Y[0] <= y <= PERMIL_Y[1]
                    and (m := re.search(r"(\d{2,5})\s*[%％]", s))), None)  # fmt: skip
        if num is not None:
            permil[a] = num * 10
    cond = next((s for s, _, _ in tx if "以上" in s and ("突破" in s or "位" in s)), "")
    rank = re.search(r"(\d{1,2})位以上", cond)
    score = re.search(r"スコア(\d[\d,]*)以上", cond)
    return {
        "current_turn": cur,
        "rows": rows,
        "permil": permil if len(permil) == 3 else None,
        "pass_rank": int(rank.group(1)) if rank else None,
        "pass_score": int(score.group(1).replace(",", "")) if score else None,
        "close": list(CLOSE),
    }


def turn_types(panels: list[dict], total_turns: int | None) -> list[str | None] | None:
    """一屏或几屏面板读数 → 全场每回合属性（下标 0 = 第 1 回合，长度 = 总回合数）。读不到的回合是 None；一个都没有给 None。
    总回合数不知道时按读到的最后一行算长度。"""
    cur = next((p["current_turn"] for p in panels if p.get("current_turn")), None)
    if cur is None:
        return None
    by_turn: dict[int, str | None] = {}
    for p in panels:
        for off, a in (p.get("rows") or {}).items():
            if a is not None or (cur + off) not in by_turn:
                by_turn[cur + off] = a
    if not any(by_turn.values()):
        return None
    n = total_turns if total_turns else max(by_turn)
    return [by_turn.get(t) for t in range(1, n + 1)]
