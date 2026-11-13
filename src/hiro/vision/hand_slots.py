"""考试手牌的位置：卡名首字母框（A / M / T）→ 每张卡的卡面区域和能不能打（去 KAA 第 3 步，替换 KAA 的 _locate_letters / locate_cards）。

做法照 KAA（kotones-auto-assistant，GPL-3.0）play_cards.ui 移植：字母框在手牌字母带（box InProduce.BoxCardLetter）里找模板
InProduce.A / M / T；卡面区域是字母框中心往左 57、上边往上 148 的矩形；字母框里出现灰色 #7a7d7d（HLS 加权距离 ≤ 0.05）= 不可打出。
只给位置和可用性，不认卡——卡是哪张由识别层 hiro.vision.hif.read_hand 认（KAA 的卡图库认错过 紙吹雪 等）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hiro.vision.ui_templates import Point, Rect, box, normalize, tpl

CARD_OFFSET = (57, 148)  # 字母框（中心 x，上边 y）到卡面左上角的偏移
DISABLED_RGB = (0x7A, 0x7D, 0x7D)  # 不可打出时字母框的灰
COLOR_THRESHOLD = 0.95  # 同 KAA color.find 缺省：相似度 ≥ 0.95


def card_letters(img: np.ndarray) -> list[Rect]:
    """手牌字母框（720x1280 坐标），A / M / T 依次找，不排序（同 KAA）。"""
    region = box("InProduce.BoxCardLetter").xywh
    return [m.rect for name in ("InProduce.A", "InProduce.M", "InProduce.T") for m in tpl(name).find_all(img, region=region)]


def has_color(img: np.ndarray, rect: Rect, rgb: tuple[int, int, int], threshold: float = COLOR_THRESHOLD) -> bool:
    """rect 里有没有接近 rgb 的像素：HLS 空间加权距离（H 环形、权重 2），≤ 1 - threshold 算接近（同 KAA color.find）。"""
    import cv2

    crop = normalize(img)[rect.y1 : rect.y2, rect.x1 : rect.x2]
    if crop.size == 0:
        return False
    th, tl, ts = cv2.cvtColor(np.array([[rgb]], np.uint8), cv2.COLOR_RGB2HLS)[0, 0].astype(np.float32)
    hls = cv2.cvtColor(crop, cv2.COLOR_BGR2HLS).astype(np.float32)
    dh = np.minimum(np.abs(hls[..., 0] - th), 180 - np.abs(hls[..., 0] - th)) / 90
    dl, ds = np.abs(hls[..., 1] - tl) / 255, np.abs(hls[..., 2] - ts) / 255
    dist = np.sqrt((dh * 2) ** 2 + dl**2 + ds**2) / np.sqrt(6)
    return bool((dist <= 1 - threshold).any())


@dataclass(frozen=True)
class HandSlot:
    rect: Rect  # 卡面左半边（点这里出牌）
    letter: Rect
    available: bool

    @property
    def center(self) -> Point:
        return self.rect.center


def hand_slots(img: np.ndarray) -> list[HandSlot]:
    """手牌从左到右，每个字母框一张（KAA 认不出卡时那张是 None；这里不认卡，所以不会缺）。"""
    img = normalize(img)
    out = []
    for letter in card_letters(img):
        x2, y2 = letter.center.x, letter.y1
        out.append(HandSlot(Rect(x2 - CARD_OFFSET[0], y2 - CARD_OFFSET[1], x2, y2), letter, not has_color(img, letter, DISABLED_RGB)))
    return sorted(out, key=lambda s: s.rect.x1)
