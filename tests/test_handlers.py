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
