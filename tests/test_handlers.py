"""新主循环的页面处理器（hiro.produce.handlers）：页面 → HifCore 方法；考试入口打完关门、换页开门、再挑戦直接重进。"""

from hiro.produce.handlers import make_handlers
from hiro.runtime.loop import DONE, STAY


class FakeCore:
    exam_restarted = False

    def __init__(self, restart_times: int = 0):
        self.calls, self.restart_times = [], restart_times

    def _hook(name):
        def f(self, ctx):
            assert ctx is None  # 新主循环不给 KAA 上下文
            self.calls.append(name)

        return f

    on_consult = _hook("consult")
    on_skill_card_enhance = _hook("enhance")
    on_skill_card_removal = _hook("removal")
    on_pdrink_max_confirm = _hook("pdrink_max_confirm")
    on_select_pitem = _hook("select_pitem")
    on_study = _hook("study")
    on_outing = _hook("outing")
    on_practice_entered = _hook("practice")

    def on_exam_entered(self, ctx):
        self.calls.append("exam")
        if self.restart_times:
            self.restart_times -= 1
            self.exam_restarted = True  # 点了再挑戦


def _run(h, page):
    return h[page](None, None, None)


def test_pages_call_core_methods():
    core = FakeCore()
    h = make_handlers(core)
    assert _run(h, "CONSULT") is DONE and _run(h, "SKILL_CARD_REMOVAL") is DONE and _run(h, "PDRINK_MAX_CONFIRM") is DONE
    assert core.calls == ["consult", "removal", "pdrink_max_confirm"]
    assert "ACTION_SELECT" not in h  # 还要 KAA ctx 的页没登记，交给 advance


def test_exam_entered_once_until_another_page():
    core = FakeCore()
    h = make_handlers(core)
    assert _run(h, "HIF_EXAM") is DONE
    assert _run(h, "HIF_EXAM") is STAY and _run(h, "EXAM") is STAY  # 打完的考试残帧：不重进
    assert core.calls == ["exam"]
    _run(h, "CONSULT")  # 换到别的已处理页面后，下一场考试照常进入
    assert _run(h, "HIF_EXAM") is DONE and core.calls == ["exam", "consult", "exam"]


def test_exam_retry_reenters_directly():
    core = FakeCore(restart_times=1)
    h = make_handlers(core)
    _run(h, "HIF_EXAM")  # 第一次：没过线，点了再挑戦
    assert _run(h, "HIF_EXAM") is DONE  # 再挑戦后同一场直接重进
    assert core.calls == ["exam", "exam"] and core.exam_restarted is False
    assert _run(h, "HIF_EXAM") is STAY  # 这次打完了：关门


def test_event_commit_double_clicks_and_confirms_outing_ap_dialog(monkeypatch):
    """授業 / 外出提交（HifCore._event_commit，替换 KAA Study/OutingContext.commit）：双击第 i 个按钮；外出时 AP 已满框点确定。"""
    from types import SimpleNamespace as NS

    import pytest

    import hiro.produce.hif as hif
    import hiro.vision.classify as cl
    from hiro.vision.ocr import Box

    t = [0.0]
    clicks, taps = [], []
    monkeypatch.setattr(hif.time, "monotonic", lambda: t[0])
    monkeypatch.setattr(hif, "sleep", lambda s: t.__setitem__(0, t[0] + s))
    monkeypatch.setattr(hif, "device", NS(screenshot=lambda: None, click=lambda x, y: None, double_click=lambda x, y: clicks.append((x, y))))
    monkeypatch.setattr(cl, "option_regions", lambda img: [Box(80, 700, 640, 780), Box(80, 820, 640, 900)])
    shown = iter([True, False, False])
    monkeypatch.setattr(hif, "tpl", lambda name: NS(exists=lambda img: next(shown, False)))
    monkeypatch.setattr(hif, "tap", lambda name, img, click: taps.append(name))
    core = hif.HifCore.__new__(hif.HifCore)
    core._event_commit(1, outing=True)
    assert clicks == [(360, 860)] and taps == ["InProduce.OutingApMaxOutDialog.ButtonConfirm"]
    with pytest.raises(ValueError):
        core._event_commit(5, outing=False)


def test_produce_end_and_allowance_record_then_delegate(monkeypatch):
    from types import SimpleNamespace as NS

    from hiro.runtime import finish

    seen = []
    core = FakeCore()
    core.s = NS(observe=lambda **kw: seen.append(("observe", kw["scene"])) or kw["scene"], record=lambda obs, **kw: seen.append(("record", obs)))
    monkeypatch.setattr(finish, "on_produce_end", lambda rt, f, hit: seen.append("finish_end") or finish.END)
    monkeypatch.setattr(finish, "on_allowance", lambda rt, f, hit: seen.append("claim") or DONE)
    h = make_handlers(core)
    assert h["ALLOWANCE"](None, None, None) is DONE
    assert h["PRODUCE_END"](None, None, None) is finish.END
    assert seen == [("observe", "ALLOWANCE"), "claim", ("record", "ALLOWANCE"), ("observe", "PRODUCE_END"), ("record", "PRODUCE_END"), "finish_end"]
