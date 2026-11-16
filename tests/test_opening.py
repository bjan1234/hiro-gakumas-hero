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


# ---------------------------------------------------------------- 第 2 步支援卡 + 租借
def _step2(monkeypatch, *, enabled_after_pick=True, picked=True, mismatch=False):
    calls = {"set": [], "pick": []}
    from hiro.produce import formation_steps, prep_steps

    monkeypatch.setattr(prep_steps, "select_set", lambda n, **kw: calls["set"].append(n) or True)
    monkeypatch.setattr(formation_steps, "autofix_support", lambda dev, plan: None)

    def check(img, plan, set_no, **kw):  # shoot / sleep：等翻页动画停（账号 2 11-16）
        if mismatch:
            raise opening.ResumeBlocked("支援卡编成和方案对不上")  # FormationMismatch 也是停机类

    monkeypatch.setattr(formation_steps, "check_support", check)
    state = {"enabled": False}

    def pick(plan, attr, main):
        calls["pick"].append(attr)
        state["enabled"] = enabled_after_pick
        return picked

    monkeypatch.setattr(formation_steps, "rental_pick", pick)
    monkeypatch.setattr(opening, "_next_enabled", lambda f, name: Match(Box(500, 1150, 501, 1151), 0.9) if state["enabled"] or getattr(f, "lit", False) else None)
    return calls, state


def test_step2_full_formation_goes_next(monkeypatch):
    calls, state = _step2(monkeypatch)
    s2 = frame({"Produce.TextStepIndicator2": (1, 1)})
    s2.lit = True
    rt, _ = rig(monkeypatch, [s2], on_tap=lambda taps: [frame({"Produce.TextStepIndicator3": (1, 1)})])
    opening.step2(rt, set_no=4)
    assert calls["set"] == [4] and calls["pick"] == [] and rt.raw_device.taps == [(500, 1150)]


def test_step2_rents_when_slot_empty(monkeypatch):
    calls, state = _step2(monkeypatch)
    rt, _ = rig(monkeypatch, [frame({"Produce.TextStepIndicator2": (1, 1)})], on_tap=lambda taps: [frame({"Produce.TextStepIndicator3": (1, 1)})])
    opening.step2(rt, set_no=4, rental_attr="Vi")
    assert calls["pick"] == ["Vi"] and rt.raw_device.taps == [(500, 1150)]


def test_step2_stops_without_rental_or_set_or_on_mismatch(monkeypatch):
    s2 = [frame({"Produce.TextStepIndicator2": (1, 1)})]
    _step2(monkeypatch, picked=False, enabled_after_pick=False)
    rt, _ = rig(monkeypatch, s2)
    with pytest.raises(ResumeBlocked, match="租借"):
        opening.step2(rt, set_no=4)
    rt, _ = rig(monkeypatch, s2)
    with pytest.raises(ResumeBlocked, match="编成号"):
        opening.step2(rt, set_no=None)
    _step2(monkeypatch, mismatch=True)
    rt, _ = rig(monkeypatch, s2)
    with pytest.raises(ResumeBlocked, match="对不上"):
        opening.step2(rt, set_no=4)


# ---------------------------------------------------------------- 第 3 / 4 步、本战选拔回忆
def test_step3_confirms_rent_tip_then_next(monkeypatch):
    from hiro.produce import formation_steps, prep_steps

    monkeypatch.setattr(prep_steps, "select_set", lambda n, **kw: True)
    monkeypatch.setattr(formation_steps, "autofix_memory", lambda dev, plan, mk: None)
    checked = []
    monkeypatch.setattr(formation_steps, "check_memory_set", lambda img, plan, n: checked.append(n))
    s3 = frame({"Produce.TextStepIndicator3": (1, 1), "Produce.Step3.ButtonNext": (500, 1160)})
    tip = frame({"Produce.TextRentAvailable": (360, 600), "Produce.RentAvailableConfirmButton": (360, 900)})
    s4 = frame({"Produce.TextStepIndicator4Or2": (1, 1)})
    rt, _ = rig(monkeypatch, [s3], on_tap=lambda taps: [tip] if len(taps) == 1 else [s4])
    opening.step3(rt, set_no=5)
    assert checked == [5] and rt.raw_device.taps == [(500, 1160), (360, 900)]


def test_step4_sets_boost_checkboxes(monkeypatch):
    states = {"Produce.Step4.CheckboxNoteBoost": True, "Produce.Step4.CheckboxPtBoost": False}
    monkeypatch.setattr("hiro.vision.ui_templates.checkbox_checked", lambda img, m: states[m.name])
    s4 = frame({"Produce.TextStepIndicator4Or2": (1, 1), "Produce.Step4.CheckboxNoteBoost": (100, 800), "Produce.Step4.CheckboxPtBoost": (100, 900)})
    rt, _ = rig(monkeypatch, [s4])
    real_find = nav.find
    monkeypatch.setattr(nav, "find", lambda f, name, **kw: (m := real_find(f, name, **kw)) and type("M", (), {"rect": m.rect, "name": name})())
    opening.step4(rt, note_boost=False, pt_boost=False)
    assert rt.raw_device.taps == [(100, 800)]  # 只把勾着的 NoteBoost 取消，PtBoost 本来就没勾


def test_check_main_memory(monkeypatch):
    from hiro.produce import memory_select

    rt, _ = rig(monkeypatch, [frame({})])
    seq = iter([[], ["2066"], []])
    picked = []
    monkeypatch.setattr(memory_select, "memory_missing_on_page", lambda expect, **kw: next(seq))
    monkeypatch.setattr(memory_select, "select_memory", lambda expect, **kw: picked.append(expect) or True)
    opening.check_main_memory(rt, ("1498", "2066", "944"))  # 页面上已经是这份
    opening.check_main_memory(rt, ("1498", "2066", "944"))  # 缺 2066 → 去列表选 → 再核通过
    assert picked == [("1498", "2066", "944")]
    monkeypatch.setattr(memory_select, "memory_missing_on_page", lambda expect, **kw: ["944"])
    with pytest.raises(memory_select.MemoryMismatch):
        opening.check_main_memory(rt, ("1498", "2066", "944"))
    opening.check_main_memory(rt, ())  # 没指定就不查


def test_prepare_main_skips_formation_steps(monkeypatch):
    called = []
    monkeypatch.setattr(opening, "check_main_memory", lambda rt, expect: called.append(("memory", expect)))
    monkeypatch.setattr(opening, "step4", lambda rt, **kw: called.append(("step4", kw)))
    monkeypatch.setattr(opening, "step1", lambda *a, **k: called.append("step1"))
    s1 = frame({"Produce.TextStepIndicator1": (1, 1), "Produce.Step1.ButtonNext": (500, 1160)})
    rt, _ = rig(monkeypatch, [s1], on_tap=lambda taps: [frame({"Produce.TextStepIndicator4Or2": (1, 1)})])
    opening.prepare(rt, "main", idol="i_card-skin-hski-3-007", expect_memory=("1", "2", "3"))
    assert called == [("memory", ("1", "2", "3")), ("step4", {"note_boost": False, "pt_boost": False})]


def _memory_unset_rig(monkeypatch, chosen):
    from hiro.produce import formation_steps, prep_steps
    from hiro.vision.ocr import Box as OBox, Text

    monkeypatch.setattr(prep_steps, "select_set", lambda n, **kw: True)
    monkeypatch.setattr(formation_steps, "autofix_memory", lambda dev, plan, mk: None)
    monkeypatch.setattr(formation_steps, "check_memory_set", lambda img, plan, n: None)
    s3 = frame({"Produce.TextStepIndicator3": (1, 1), "Produce.Step3.ButtonNext": (500, 1160)})
    dlg = frame({}, [Text("キャンセル", OBox(162, 1144, 311, 1180)), Text("く完了する", OBox(394, 1144, 577, 1176))])
    dlg.__dict__.update(has_dialog=True, dialog={"kind": "other", "title": "メモリー編成確認", "danger": False, "y": 937, "body": ""})
    s4 = frame({"Produce.TextStepIndicator4Or2": (1, 1)})
    rt, _ = rig(monkeypatch, [s3], on_tap=lambda taps: [dlg] if len(taps) == 1 else [s4])
    plan = {"memory": {"chosen": [{"card_id": f"c{i}"} for i in range(chosen)]}}
    return rt, plan


def test_step3_memory_unset_confirm_when_plan_has_fewer(monkeypatch):
    """「メモリー編成確認」（有空的回忆格，账号 2 11-16 原来没处理）：方案本来就不到 4 份 → 点「完了する」进第 4 步。"""
    rt, plan = _memory_unset_rig(monkeypatch, 1)
    opening.step3(rt, set_no=20, plan=plan)
    assert rt.raw_device.taps == [(500, 1160), (485, 1160)]


def test_step3_memory_unset_cancel_and_stop_when_plan_wants_four(monkeypatch):
    rt, plan = _memory_unset_rig(monkeypatch, 4)
    with pytest.raises(ResumeBlocked, match="キャンセル"):
        opening.step3(rt, set_no=20, plan=plan)
    assert rt.raw_device.taps[-1] == (236, 1162)  # 点的是キャンセル，不是完了する
