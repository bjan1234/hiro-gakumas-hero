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
