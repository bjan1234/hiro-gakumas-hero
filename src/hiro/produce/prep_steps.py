"""编成第 2 / 3 步的通用动作（不依赖 KAA；旧主循环把 KAA prepare._select_set 换成 select_set，新主循环直接用）。"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from hiro.devices.active import sleep as _sleep
from hiro.vision.ocr import screen_texts
from hiro.vision.ui_templates import box, point

logger = logging.getLogger(__name__)

READ_TIMEOUT = 5.0
RETRIES = 3


def set_number(img) -> int | None:
    """编成页左上「N/20」读出当前编成号（OCR 编成号区域，取第一个数）；读不到 None。"""
    text = "".join(t.text for t in screen_texts(img, box("Produce.BoxSetCountIndicator").xywh))
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def select_set(index: int, *, shoot: Callable, tap: Callable[[int, int], None], sleep: Callable[[float], None] = _sleep,
               clock: Callable[[], float] = time.monotonic) -> bool:  # fmt: skip
    """翻到第 index 号支援卡 / 回忆编成（同 KAA _select_set：差几号点几下翻页箭头，再读一次核对，最多 RETRIES 轮）。
    读不出编成号（READ_TIMEOUT 内）或翻不到时返回 False（KAA 原版读不出会一直等）。"""

    def current() -> int | None:
        t0 = clock()
        while (n := set_number(shoot())) is None:
            if clock() - t0 >= READ_TIMEOUT:
                return None
            sleep(0.2)
        return n

    for attempt in range(RETRIES):
        now = current()
        if now is None:
            logger.error("编成号读不出来（%.0fs）", READ_TIMEOUT)
            return False
        if now == index:
            return True
        target = point("Produce.PointProduceNextSet" if now < index else "Produce.PointProducePrevSet")
        logger.info("编成：从 %d 号翻到 %d 号", now, index)
        for _ in range(abs(index - now)):
            tap(*target)
            sleep(0.1)
        if current() == index:
            return True
        logger.warning("编成没翻到 %d 号（第 %d 次）", index, attempt + 1)
    logger.error("翻了 %d 轮仍没到 %d 号编成", RETRIES, index)
    return False
