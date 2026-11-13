"""收活动费，移植 KAA tasks/daily/acquire_activity_funds：首页活动费入口有红点就点，弹出领取框后点 ✖ 关掉，回首页。"""

from __future__ import annotations

import logging

from hiro.daily import common
from hiro.runtime import nav
from hiro.vision.ui_templates import box

logger = logging.getLogger(__name__)

ENTRY = "Daily.ActivityFunds.EntryArea"
TITLE = "Daily.ActivityFunds.DialogTitle"
CROSS = "Common.IconButtonCross"  # 弹窗的 ✖（KAA dialog.no）
RED_DOTS = ("#ff6085", "#ff1249")  # 入口上的红点（同 KAA need_acquire）
TIMEOUT = 30.0


def need_acquire(f) -> bool:
    return any(common.has_color(f.img, c, box(ENTRY)) for c in RED_DOTS)


def run(rt) -> str:
    nav.goto_home(rt)
    rt.sleep(1)
    tapped = {"n": 0}

    def step(f):
        if not need_acquire(f):
            return "没有活动费可领" if not tapped["n"] else "领了活动费"
        if nav.find(f, TITLE) is not None:
            if (m := nav.find(f, CROSS)) is not None:
                nav.tap_match(rt, m)
            rt.sleep(0.5)
            return "领了活动费"
        rt.device.tap(*box(ENTRY).center)
        tapped["n"] += 1
        rt.sleep(0.5)
        return None

    r = rt.drive(step, TIMEOUT, "收活动费")
    logger.info(r)
    nav.goto_home(rt)
    return r
