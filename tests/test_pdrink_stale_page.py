"""DMM qualifyverify4（11-17 14:37）：饮料溢出页刚出现、还没在状态里稳定（state.page 仍是上一页 DECK_LIST，page_fields 是牌组一览的），
处理器就决策了：决策器没读到 held / incoming，兜底「不换」→ 点「残す」（放弃新饮料）。下一拍主循环又把过渡帧判成 PDRINK_MAX，
处理器重入、观测写死 scene=PDRINK_MAX，「報酬スキップ」确认框已盖在上面，重新决策成「换」，点被挡住的勾选框，2 次没生效停机。"""

from types import SimpleNamespace as NS

from hiro.contracts import Action, ActionKind, Decision, GameState


def test_overflow_decider_waits_when_fields_are_from_another_page():
    from hiro.brain.deciders import ProduceDeciders
    from hiro.brain.state import CAMPUS_HIRO

    st = GameState(page={"name": "DECK_LIST"}, page_fields={"cards": [], "complete": True},
                   produce={"mode": "produce-007", "drink_capacity": 4, "drinks": ["pdrink_02-1-008", "pdrink_00-2-008", "pdrink_00-2-009", "pdrink_00-3-001"]})  # fmt: skip
    d = ProduceDeciders(CAMPUS_HIRO, None).decide("PDRINK_MAX", st)
    assert d.action.kind is ActionKind.WAIT, (d.action, d.reason)


def _strategy(monkeypatch, pages, confirm_on_top=lambda img: False):
    import hiro.produce.hif as hif

    seen, confirms = [], []
    st = {"i": 0}

    def observe(**k):
        st["i"] += 1
        name = pages[min(st["i"], len(pages)) - 1]
        sess.state = GameState(page={"name": name}, pending_page=None if name == "PDRINK_MAX" else {"name": "PDRINK_MAX", "stable": False})
        return NS(fields={})

    class Deciders:
        def decide(self, page, state):
            seen.append(state.page.get("name") if isinstance(state.page, dict) else state.page.name)
            return Decision(Action(ActionKind.DISCARD_DRINK, {"discard": [], "receive": False}), "不收", "rule", 0.8)

    sess = NS(state=GameState(page={"name": "DECK_LIST"}), observe=observe, record=lambda *a, **k: None, recover=lambda *a, **k: None)
    strat = hif.HiroHifStrategy.__new__(hif.HiroHifStrategy)
    strat.s, strat.deciders = sess, Deciders()
    strat.on_pdrink_max_confirm = lambda ctx: confirms.append(1)
    monkeypatch.setattr(hif, "sleep", lambda s: None)
    monkeypatch.setattr(hif, "device", NS(screenshot=lambda: None))
    monkeypatch.setattr(hif, "_confirm_on_top", confirm_on_top)
    monkeypatch.setattr("hiro.produce.drink_swap.skip_incoming", lambda **k: True)
    return strat, seen, confirms


def test_handler_waits_for_page_to_settle_before_deciding(monkeypatch):
    strat, seen, _ = _strategy(monkeypatch, ["DECK_LIST", "DECK_LIST", "PDRINK_MAX"])
    strat.on_pdrink_max(None)
    assert seen == ["PDRINK_MAX"]


def test_handler_hands_covering_confirm_to_confirm_handler(monkeypatch):
    strat, seen, confirms = _strategy(monkeypatch, ["PDRINK_MAX"], confirm_on_top=lambda img: True)
    strat.on_pdrink_max(None)
    assert seen == [] and confirms == [1]


def test_reentry_after_skip_waits_for_confirm_instead_of_redeciding(monkeypatch):
    calls = {"n": 0}

    def on_top(img):
        calls["n"] += 1
        return calls["n"] >= 3  # 「残す」点过，确认框过两拍才弹出

    strat, seen, confirms = _strategy(monkeypatch, ["PDRINK_MAX"], confirm_on_top=on_top)
    strat._skip_incoming_drink = True
    strat.on_pdrink_max(None)
    assert seen == [] and confirms == [1]
