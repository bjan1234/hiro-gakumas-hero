"""初（はじめ）特有的读数：练习课（PRACTICE）的 HUD、考试结算的过线。初 Mac 采样 11-17（.temp/hajime-nia-mac/frames）。

- 练习课 HUD：左上「残りターン数」、正中「CLEARまで / PERFECTまで N」、右上「属性图标 + 评级 + 当前属性值」。剩余回合 / 体力 / 元气 / 手牌
  执行器的 Frame 已经按 KAA 的 InLesson 框读得出（hiro.exec.exam.Frame），这里只补属性和「还在不在练习课」。
- 属性按右上角图标颜色认（用户 11-17：图标优先）：粉 = Vo、蓝 = Da、橙 = Vi，同选行动页的 ATTR_HUE。
"""

from __future__ import annotations

import cv2
import numpy as np

LESSON_ICON = (503, 40, 545, 90)  # 右上属性图标（x1, y1, x2, y2）；Vo / Vi 实测各 1,100+ 像素
LESSON_ICON_MIN = 400


def lesson_attr(img: np.ndarray) -> str | None:
    """练习课右上角属性图标 → Vo / Da / Vi；认不出 None。"""
    from hiro.vision.action import ATTR_HUE

    if img is None or img.shape[:2] != (1280, 720):
        return None
    x1, y1, x2, y2 = LESSON_ICON
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    vivid = (hsv[..., 1] > 120) & (hsv[..., 2] > 150)
    hues = hsv[..., 0][vivid]
    counts = {a: int(((hues >= lo) & (hues <= hi)).sum()) for a, (lo, hi) in ATTR_HUE.items()}
    best = max(counts, key=counts.get)
    return {"vo": "Vo", "da": "Da", "vi": "Vi"}[best] if counts[best] >= LESSON_ICON_MIN else None


def in_lesson(img: np.ndarray) -> bool:
    """画面上还有练习课的「CLEARまで / PERFECTまで」（KAA 判 PRACTICE 用的同一对模板）。"""
    from hiro.vision.ui_templates import normalize, tpl

    if img is None:
        return False
    img = normalize(img)
    return any(tpl(n).find(img) is not None for n in ("InProduce.TextClearUntil", "InProduce.TextPerfectUntil"))


def exam_rank(img: np.ndarray) -> dict | None:
    """考试结算名次页（1st–6th 名单 + 左下「再挑戦」+「次へ」，版面同 H.I.F）→ {rank, score, retry}；不是这一页 None。
    H.I.F 的 passed 按突破线判，初没有突破线，过没过由调用方按名次（modes.pass_rank，初前 3）定。"""
    from hiro.vision.hif import read_hif_result

    try:
        r = read_hif_result(img)
    except Exception:  # noqa: BLE001  识别异常当没读到
        return None
    if r.get("rank") is None:
        return None
    return {"rank": r["rank"], "score": r.get("score"), "retry": r.get("retry")}
