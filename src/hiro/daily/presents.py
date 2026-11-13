"""领礼物（邮箱），移植 KAA tasks/daily/acquire_presents：首页 → 礼物页 → 「一括受取」→ 关结果框 → 回首页。"""

from __future__ import annotations

import logging

from hiro.daily import common
from hiro.runtime import nav

logger = logging.getLogger(__name__)

ENTRY = "Daily.ButtonPresentsPartial"
CLAIM_ALL = "Daily.Presents.ButtonClaimAllNoIcon"
CLOSE = "Common.ButtonClose"
TIMEOUT = 60.0


def run(rt) -> str:
    nav.goto_home(rt)

    def enter(f):
        if (m := nav.find(f, CLAIM_ALL)) is not None:
            return "empty" if common.enabled(f, m) is False else "open"
        if (m := nav.find(f, ENTRY)) is not None:
            nav.tap_match(rt, m)
            rt.sleep(1)
        return None

    if rt.drive(enter, TIMEOUT, "进礼物页") == "empty":
        logger.info("没有可领的礼物")
        nav.goto_home(rt)
        return "没有可领的礼物"
    claimed = {"n": 0}

    def claim(f):
        btn = nav.find(f, CLAIM_ALL)
        if btn is not None and not (claimed["n"] and common.enabled(f, btn) is False):
            nav.tap_match(rt, btn)
            claimed["n"] += 1
            rt.sleep(1)
            return None
        if (close := nav.find(f, CLOSE)) is not None:
            nav.tap_match(rt, close)
            rt.sleep(1)
            return True
        if btn is not None:  # 领过了、按钮灰了、也没有结果框：已经回到礼物页（KAA 这里会一直点灰按钮）
            return True
        return None

    rt.drive(claim, TIMEOUT, "领礼物")
    nav.goto_home(rt)
    return "领了礼物"
