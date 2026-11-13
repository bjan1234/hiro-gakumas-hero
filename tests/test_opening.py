"""开局导航（hiro.runtime.opening / nav）：假设备 + 假帧（每帧标出能看到哪些模板、在哪），不跑真识别。"""

import os
import subprocess
import sys

import numpy as np
import pytest

from hiro.loop.errors import ResumeBlocked
from hiro.runtime import Frame, Runtime, UNKNOWN, nav, opening
from hiro.vision.ocr import Box, Text
from hiro.vision.ui_templates import Match


class FakeDevice:
    name = "fake"

    def __init__(self):
        self.taps = []

    def screenshot(self):
        return np.zeros((1280, 720, 3), np.uint8)

    def tap(self, x, y):
        self.taps.append((x, y))


def frame(seen: dict, texts=()):
    """seen：模板名 → 中心点。"""
    f = Frame(np.zeros((1280, 720, 3), np.uint8), 0.0)
    f.__dict__.update(texts=list(texts), has_dialog=False, dialog=None)
    f.seen = seen
    return f


def rig(monkeypatch, frames, on_tap=None):
    """Runtime：截图依次给 frames（用完重复最后一帧）；on_tap(taps) 返回下一批帧时替换队列（模拟点完换页）。"""
    t = {"now": 0.0}
    rt = Runtime(FakeDevice(), lambda img: UNKNOWN, clock=lambda: t["now"], sleep=lambda s: t.__setitem__("now", t["now"] + s))
    queue = list(frames)

    def shot():
        f = queue.pop(0) if len(queue) > 1 else queue[0]
        f.t = t["now"]
        rt.screen.frame = f
        return f

    rt.screen.shot = shot
    raw_tap = rt.raw_device.tap

    def tap(x, y):
        raw_tap(x, y)
        if on_tap is not None and (nxt := on_tap(rt.raw_device.taps)) is not None:
            queue[:] = nxt

    rt.raw_device.tap = tap
    monkeypatch.setattr(nav, "find", lambda f, name, **kw: Match(Box(*(p := f.seen[name]), p[0] + 1, p[1] + 1), 0.9)
                        if name in getattr(f, "seen", {}) else None)  # fmt: skip
    monkeypatch.setattr("hiro.runtime.guard.word_at", lambda f, x, y: None)
    return rt, t


HOME = {"Daily.ButtonHomeCurrent": (359, 1155)}


def test_goto_home_taps_home_buttons_until_home(monkeypatch):
    rt, _ = rig(monkeypatch, [frame({"Common.ButtonIconClose": (650, 100)})], on_tap=lambda taps: [frame(HOME)])
    f = nav.goto_home(rt)
    assert f.seen == HOME and rt.raw_device.taps == [(650, 100)]


def test_goto_home_times_out(monkeypatch):
    rt, _ = rig(monkeypatch, [frame({})])
    with pytest.raises(ResumeBlocked, match="回首页"):
        nav.goto_home(rt, timeout=3)


def test_enter_produce_new_and_resume_guard(monkeypatch):
    ongoing = opening.box("Produce.BoxProduceOngoing").center
    rt, _ = rig(monkeypatch, [frame(HOME)], on_tap=lambda taps: [frame({"Produce.LogoHif": (360, 400)})])
    assert opening.enter_produce(rt, new=True) == "new" and rt.raw_device.taps == [tuple(ongoing)]
    rt, _ = rig(monkeypatch, [frame(HOME)], on_tap=lambda taps: [frame({"Produce.ButtonResume": (500, 1000)})])
    with pytest.raises(ResumeBlocked, match="resume"):
        opening.enter_produce(rt, new=True)
    rt, _ = rig(monkeypatch, [frame(HOME)], on_tap=lambda taps: [frame({"Produce.ButtonResume": (500, 1000)})])
    assert opening.enter_produce(rt, new=False) == "resume"


def test_enter_produce_discard_dialog_only_cancels(monkeypatch):
    dlg = frame({"Produce.BreakProduceDialog.Title": (360, 500)}, [Text("キャンセル", Box(180, 1150, 260, 1170)), Text("開始する", Box(460, 1150, 560, 1170))])
    rt, _ = rig(monkeypatch, [frame(HOME)], on_tap=lambda taps: [dlg] if len(taps) == 1 else None)
    with pytest.raises(ResumeBlocked, match="破棄"):
        opening.enter_produce(rt, new=True)
    assert rt.raw_device.taps[-1] == (220, 1160)  # 只点了キャンセル


def test_select_hif_goes_back_then_forward(monkeypatch):
    prev, nxt = tuple(opening.point("Produce.PointPrev")), tuple(opening.point("Produce.PointNext"))
    pages = [frame({"Produce.LogoNia": (1, 1)}), frame({"Produce.LogoHajime": (1, 1)}), frame({"Produce.LogoNia": (1, 1)}),
             frame({"Produce.LogoHif": (1, 1)})]  # fmt: skip
    rt, _ = rig(monkeypatch, [pages[0]], on_tap=lambda taps: [pages[len(taps)]])
    opening.select_hif(rt)
    assert rt.raw_device.taps == [prev, nxt, nxt]


def test_choose_mode_refills_ap_once(monkeypatch):
    calls = []

    def refill(shoot, click, ocr, **kw):
        calls.append(kw["extra_ap"])
        click(500, 800)  # 真的 refill 会点「回復する」「使用する」…，点完回到选模式页
        return {"ok": True, "drinks": 1, "shortfall": 5, "error": None}

    monkeypatch.setattr("hiro.loop.ap_refill.refill", refill)
    btn = {"Produce.ButtonHifQualify": (360, 900)}
    seq = [frame({"Produce.TextAPInsufficient": (360, 600)}), frame(btn), frame({"Produce.TextStepIndicator1": (100, 100)})]
    rt, _ = rig(monkeypatch, [frame(btn)], on_tap=lambda taps: [seq[len(taps) - 1]] if len(taps) <= len(seq) else None)
    opening.choose_mode(rt, "qualify")
    assert calls == [20]  # 只打选拔：本战还要 20 AP 一起补
    rt, _ = rig(monkeypatch, [frame({"Produce.TextAPInsufficient": (360, 600)})])
    monkeypatch.setattr("hiro.loop.ap_refill.refill", lambda *a, **k: {"ok": False, "error": "确认框有ジュエル"})
    with pytest.raises(ResumeBlocked, match="ジュエル"):
        opening.choose_mode(rt, "main")


def test_start_presses_start_then_skip_commu(monkeypatch):
    seq = [frame({"Produce.RadioTextSkipCommu": (200, 700)}), frame({"Common.ButtonConfirmNoIcon": (500, 1100)}), frame({})]
    rt, _ = rig(monkeypatch, [frame({"Produce.Step4.ButtonProduceStart": (500, 1150)})],
                on_tap=lambda taps: [seq[min(len(taps) - 1, 2)]])  # fmt: skip
    opening.start(rt)
    assert rt.raw_device.taps[:3] == [(500, 1150), (200, 700), (500, 1100)]


def test_opening_imports_no_kaa():
    code = "import sys, hiro.runtime.opening; print([m for m in sys.modules if m.split('.')[0] in ('kaa', 'kotonebot')])"
    env = {k: v for k, v in os.environ.items() if k != "HIRO_KAA_GAME_DATA"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env).stdout.strip()
    assert out == "[]"


# ---------------------------------------------------------------- 第 1 步选偶像
def _step1(monkeypatch, selected_frames):
    """idol_selected 按帧上的 selected 标记；idol_select.locate 直接给卡位。"""
    monkeypatch.setattr(opening, "idol_selected", lambda f, skin: getattr(f, "selected", False))
    monkeypatch.setattr("hiro.produce.idol_select.locate", lambda skin, **kw: Box(200, 600, 349, 797))


def test_step1_already_selected_just_next(monkeypatch):
    _step1(monkeypatch, None)
    s1 = frame({"Produce.TextStepIndicator1": (1, 1), "Produce.Step1.ButtonNext": (500, 1160)})
    s1.selected = True
    rt, _ = rig(monkeypatch, [s1], on_tap=lambda taps: [frame({"Produce.TextStepIndicator2": (1, 1)})])
    opening.step1(rt, "i_card-skin-hski-3-007")
    assert rt.raw_device.taps == [(500, 1160)]


def test_step1_selects_from_overview_then_next(monkeypatch):
    _step1(monkeypatch, None)
    s1 = frame({"Produce.TextStepIndicator1": (1, 1), "Produce.ButtonPIdolOverview": (600, 400)})
    another = frame({"Common.ButtonConfirmNoIcon": (500, 1160), "Produce.TextAnotherIdolAvailableDialog": (360, 500), "Common.ButtonIconClose": (650, 300)})
    overview = frame({"Produce.IdolOverview.ButtonConfirm": (500, 1160), "Common.ButtonConfirmNoIcon": (500, 1160)})
    back = frame({"Produce.TextStepIndicator1": (1, 1), "Produce.Step1.ButtonNext": (500, 1160)})
    back.selected = True
    s2 = frame({"Produce.TextStepIndicator2": (1, 1)})
    script = {1: [another], 2: [overview], 3: [overview], 4: [back], 5: [s2]}  # 第几次点击之后的画面
    rt, _ = rig(monkeypatch, [s1], on_tap=lambda taps: script.get(len(taps)))
    opening.step1(rt, "i_card-skin-hski-3-007")
    assert rt.raw_device.taps == [(600, 400), (650, 300), (274, 698), (500, 1160), (500, 1160)]  # 一览、关提示、点卡、确认、次へ


def test_step1_idol_missing_stops(monkeypatch):
    monkeypatch.setattr(opening, "idol_selected", lambda f, skin: False)
    monkeypatch.setattr("hiro.produce.idol_select.locate", lambda skin, **kw: None)
    s1 = frame({"Produce.TextStepIndicator1": (1, 1), "Produce.IdolOverview.ButtonConfirm": (500, 1160)})
    rt, _ = rig(monkeypatch, [s1])
    with pytest.raises(ResumeBlocked, match="找不到"):
        opening.step1(rt, "i_card-skin-none")
