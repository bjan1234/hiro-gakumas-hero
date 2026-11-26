"""收活动费，移植 KAA tasks/daily/acquire_activity_funds：点首页活动费入口（点了就领），弹出领取框后点 ✖ 关掉，回首页。

11-25 DMM 实测：入口没有红点（显示 25%、26%）时点进去也能领（领了 8,243 マニー，日常任务「マニーを回収しよう」完成），
KAA 只在有红点时领，没满就一直不领。现在不看红点：点一次，弹出领取框就算领了，读框里的マニー数。"""

from __future__ import annotations

import logging
import re

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


def amount(f) -> str | None:
    """领取框里「8,243 マニー」那一行的数（读不到 None）。"""
    for t in f.texts:
        if m := re.search(r"([\d,]+)\s*マニ", t.text):
            return m.group(1)
    return None


def is_dialog(f) -> bool:
    if nav.find(f, TITLE) is not None:
        return True
    texts = [t.text for t in f.texts]
    return any("活動費" in x for x in texts) and any("保管上限" in x or "経過時間" in x for x in texts)


def run(rt) -> str:
    nav.goto_home(rt)
    rt.sleep(1)
    tapped = {"n": 0}

    def step(f):
        if tapped["n"] and is_dialog(f):
            got = amount(f)
            if (m := nav.find(f, CROSS)) is not None:
                nav.tap_match(rt, m)
            elif (c := next((t for t in f.texts if "閉じる" in t.text), None)) is not None:
                rt.device.tap(*c.rect.center)
            rt.sleep(0.8)
            return f"领了活动费（{got} 金币）" if got else "领了活动费"
        if tapped["n"] >= 3:
            return "点了活动费入口没有弹出领取框" if not need_acquire(f) else "活动费没领成"
        rt.device.tap(*box(ENTRY).center)
        tapped["n"] += 1
        rt.sleep(1.0)
        return None

    r = rt.drive(step, TIMEOUT, "收活动费")
    logger.info(r)
    nav.goto_home(rt)
    return r
