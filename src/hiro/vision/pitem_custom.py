"""H.I.F P 道具定制三选一（「カスタム後を選択してください」）的候选识别，纯函数、不点击。

两段定制画面结构一样：上面一个背包、下面三个候选背包（x 147 / 360 / 573），区别在上面的背包里有没有毛绒：
- 第一段（选拔②后，ぬいぐるみ）：上面是空背包，候选是不同的毛绒，按毛绒主色认种类
  （ロボ 蓝、うさぎ 黄、インコ 绿、もじゃ 紫）；
- 第二段（选拔③后，デコレーション）：上面是第一段选定的毛绒，三个候选是同一只毛绒加不同装饰，按装饰的颜色特征认
  （花 = 红花、リボン = 浅蓝蝴蝶结和波浪边框、羽 = 顶部白色翅膀）。メダル 还没有实机样本，认不出时给 None（不猜）。

阈值来自 DMM 三局（dmmw1 / dmmt1 / dmmt2）的 6 张定制帧，720x1280 坐标；各特征在命中格和其他格之间差 4 倍以上。
"""

from __future__ import annotations

import numpy as np

SLOTS_X = (147, 360, 573)
TOP_BAG = (slice(340, 500), slice(290, 430))  # 上面背包的内部（不含黄 / 绿 / 红边框）
TOP_PLUSH_MIN = 5000  # 内部高饱和像素：空背包约 1300，装着毛绒约 13500
PLUSH_MIN = 1500  # 候选格中心 80x80 主色像素下限
FLOWER_MIN = 800  # 红花像素：花约 1640，其他 0（第一段インコ的红脸颊约 500，只在第二段用）
WINGS_MIN = 3000  # 格子顶部白色像素：羽约 5440，其他 ≤ 1440
RIBBON_MIN = 3500  # 浅蓝（低饱和）像素：リボン约 6540，其他 ≤ 1330

PLUSH_BY_HUE = {"blue": "ロボ", "yellow": "うさぎ", "green": "インコ", "purple": "もじゃ"}


def _hsv(img: np.ndarray) -> np.ndarray:
    import cv2

    frame = cv2.resize(img, (720, 1280)) if img.shape[:2] != (1280, 720) else img
    return cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)


def is_decoration_stage(img: np.ndarray) -> bool:
    """上面的背包里已经有毛绒 → 第二段（装饰）。"""
    top = _hsv(img)[TOP_BAG]
    return int(((top[..., 1] > 110) & (top[..., 2] > 110)).sum()) >= TOP_PLUSH_MIN


def _plush_hue(hsv: np.ndarray, x: int) -> str | None:
    roi = hsv[840:920, x - 40 : x + 40]
    h, s, v = roi[..., 0], roi[..., 1], roi[..., 2]
    vivid = h[(s > 110) & (v > 110)]
    counts = {
        "yellow": int(((vivid >= 18) & (vivid <= 35)).sum()),
        "green": int(((vivid >= 40) & (vivid <= 85)).sum()),
        "blue": int(((vivid >= 90) & (vivid <= 130)).sum()),
        "purple": int(((h >= 125) & (h <= 165) & (s > 50) & (v > 110)).sum()),  # もじゃ 淡紫，饱和度低
    }
    best = max(counts, key=counts.get)
    return best if counts[best] > PLUSH_MIN else None


def plush_kinds(img: np.ndarray) -> list[str | None]:
    """三个候选格的毛绒种类（第一段用；第二段三格都是同一只毛绒）。"""
    hsv = _hsv(img)
    return [PLUSH_BY_HUE.get(_plush_hue(hsv, x)) for x in SLOTS_X]


def decoration_features(img: np.ndarray) -> list[dict[str, int]]:
    hsv = _hsv(img)
    h, s, v = (hsv[..., i].astype(np.int32) for i in range(3))
    out = []
    for x in SLOTS_X:
        slot = (slice(770, 1000), slice(x - 105, x + 105))
        top = (slice(770, 850), slice(x - 105, x + 105))
        hh, ss, vv = h[slot], s[slot], v[slot]
        out.append({
            "red": int((((hh <= 8) | (hh >= 172)) & (ss >= 120) & (vv >= 150)).sum()),
            "white": int(((s[top] <= 35) & (v[top] >= 235)).sum()),
            "light_blue": int(((hh >= 95) & (hh <= 115) & (ss >= 40) & (ss <= 120) & (vv >= 200)).sum()),
        })  # fmt: skip
    return out


def decoration_kinds(img: np.ndarray) -> list[str | None]:
    """三个候选格的装饰：花 / リボン / 羽；都不像或不止一种像时为 None。"""
    kinds = []
    for f in decoration_features(img):
        hits = [k for k, ok in (("花", f["red"] >= FLOWER_MIN), ("羽", f["white"] >= WINGS_MIN), ("リボン", f["light_blue"] >= RIBBON_MIN)) if ok]
        kinds.append(hits[0] if len(hits) == 1 else None)
    return kinds


def custom_names(img: np.ndarray, pouch_kanji: str) -> list[str | None]:
    """候选的道具名，格式同 hiro.brain.pitem（「ロボ（黄）」「花ロボ（黄）」）；认不出的格为 None。"""
    plush = plush_kinds(img)
    if not is_decoration_stage(img):
        return [f"{p}（{pouch_kanji}）" if p else None for p in plush]
    base = next((p for p in plush if p), None)  # 三格是同一只毛绒（装饰可能盖住一部分，取认出来的那个）
    return [f"{d}{base}（{pouch_kanji}）" if d and base else None for d in decoration_kinds(img)]
