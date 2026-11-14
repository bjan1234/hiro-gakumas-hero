"""饮料满不要新饮料（drink_swap.skip_incoming，替代 KAA _check_pdrink_max）和轮间结束兜底（interval_exit.end_interval，替代
KAA HifRoundIntervalContext.end）。模板和设备打桩：每帧是「能看到的模板名 → 中心点」。勾选框判据和 KAA 彩色匹配的对照：
tests/fixtures 16 帧饮料满页 0 差异。"""

from types import SimpleNamespace as NS

from hiro.produce import drink_swap, interval_exit
from hiro.vision import ui_templates as ut
from hiro.vision.ocr import Box


def _rig(monkeypatch, module, frames, on_tap):
    taps, cur = [], {"f": frames[0]}

    def m(name, f):
        return NS(rect=Box(*(p := f[name]), p[0] + 1, p[1] + 1)) if name in f else None

    def tpl(name):
        return NS(find=lambda img, **k: m(name, img), exists=lambda img, **k: m(name, img) is not None,
                  find_all=lambda img, **k: [x for x in [m(name, img)] if x])  # fmt: skip

    def click(x, y):
        taps.append((x, y))
        if (nxt := on_tap(len(taps))) is not None:  # 空帧 {} 也算换页
            cur["f"] = nxt

    monkeypatch.setattr(module, "device", NS(screenshot=lambda: cur["f"], click=click))
    monkeypatch.setattr(ut, "tpl", tpl)
    if hasattr(module, "tpl"):
        monkeypatch.setattr(module, "tpl", tpl)
    return taps


def test_skip_incoming_checks_box_then_leaves(monkeypatch):
    dim = {"InProduce.TextPDrinkMax": (360, 300), "Common.CheckboxUnchecked": (250, 1000)}
    lit = {"InProduce.TextPDrinkMax": (360, 300), "lit": (500, 1160)}
    taps = _rig(monkeypatch, drink_swap, [dim], lambda n: lit if n == 1 else {})
    monkeypatch.setattr(ut, "checkbox_checked", lambda img, m: False)
    monkeypatch.setattr(ut, "find_enabled", lambda name, img: NS(rect=Box(500, 1160, 501, 1161)) if "lit" in img else None)
    assert drink_swap.skip_incoming(sleep_s=lambda s: None) is True
    assert taps == [(250, 1000), (500, 1160)]  # 先勾没勾的框，再点亮了的「離れる」


def test_skip_incoming_not_on_page(monkeypatch):
    taps = _rig(monkeypatch, drink_swap, [{}], lambda n: None)
    assert drink_swap.skip_incoming(sleep_s=lambda s: None) is False and taps == []


def test_end_interval_confirms_then_leaves(monkeypatch):
    seq = [{"InProduce.HifInterval.Title": (100, 100), "InProduce.HifInterval.ButtonEnd": (600, 1180)},
           {"InProduce.HifIntervalConfirm.Title": (360, 500), "InProduce.HifIntervalConfirm.ButtonConfirm": (500, 1100)}, {}]  # fmt: skip
    taps = _rig(monkeypatch, interval_exit, seq, lambda n: seq[n])
    monkeypatch.setattr(interval_exit, "sleep", lambda s: None)
    assert interval_exit.end_interval() is True and taps == [(600, 1180), (500, 1100)]


def test_end_interval_times_out(monkeypatch):
    t = {"now": 0.0}
    taps = _rig(monkeypatch, interval_exit, [{"InProduce.HifInterval.Title": (100, 100)}], lambda n: None)
    monkeypatch.setattr(interval_exit, "sleep", lambda s: t.__setitem__("now", t["now"] + s))
    assert interval_exit.end_interval(timeout=3, clock=lambda: t["now"]) is False
    assert set(taps) == {interval_exit.BLANK_TAP}
