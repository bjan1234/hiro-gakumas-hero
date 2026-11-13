"""通用导航（新主循环、开局 / 续跑、日常任务共用）：从任意页回首页、按模板找 / 点。不 import KAA / kotonebot。"""

from __future__ import annotations

from hiro.vision.ui_templates import tpl

HOME_TIMEOUT = 60.0
HOME_BUTTONS = ("Common.ButtonHome", "Common.ButtonToolbarHome", "Common.ButtonIconClose")


def find(f, name: str, **kw):
    """模板在这一帧的命中（ui_templates.Match）或 None。测试替身换这一个函数。"""
    return tpl(name).find(f.img, **kw)


def tap_match(rt, m) -> None:
    rt.device.tap(*m.rect.center)


def at_home(f) -> bool:
    """首页（底栏「ホーム」高亮，同 hiro.vision.classify.at_home）。"""
    return find(f, "Daily.ButtonHomeCurrent") is not None


def goto_home(rt, timeout: float = HOME_TIMEOUT):
    """回首页：点首页 / 工具栏首页 / ✕，直到认出首页（同 KAA goto_home）。返回首页那一帧。"""

    def step(f):
        if at_home(f):
            return f
        for name in HOME_BUTTONS:
            if (m := find(f, name)) is not None:
                tap_match(rt, m)
                return None
        return None

    return rt.drive(step, timeout, "回首页")


