"""选卡：决策要刷新、执行侧没刷成（每页上限 / 失败）时，按「刷新已用完」重新决策，不退到候选里第一个「拿」的动作。
DMM 选拔第 6 天：决策要用最后 1 次刷新，执行侧每页 3 次上限先到，拿了不要的 本番前夜+，禁用还剩 3 次没用。"""

from types import SimpleNamespace as NS

import pytest

from hiro.contracts import Action, ActionKind, Candidate, Decision, GameState


def test_reroll_blocked_redecides(monkeypatch):
    pytest.importorskip("kaa")
    import hiro.produce.hif as hif

    cands = [{"index": i, "card_id": c} for i, c in enumerate(("p_card-02-men-2_054", "p_card-02-men-1_006", "p_card-02-act-1_071"))]
    state = GameState(page_fields={"candidates": cands, "rerolls_left": 1, "excludes_left": 3})
    seen, acted = [], []

    def decide(page, st, n_options=None):
        seen.append(st.page_fields.get("rerolls_left"))
        if st.page_fields.get("rerolls_left"):  # 第一次：要刷新；候选里第一个「拿」是 本番前夜（第 0 张）
            return Decision(Action(ActionKind.REROLL), "刷新", "rule", 0.9, [Candidate(Action.activate_effect(0))])
        return Decision(Action.activate_effect(2), "刷新用完：拿第 2 张", "rule", 0.9)

    opts = [NS(rect=NS(center=NS(x=150 + 200 * i, y=700)), card=None) for i in range(3)]
    ctx = NS(fetch_cards=lambda: opts, fetch_recommend_card=lambda: None)
    h = hif.HiroHifStrategy.__new__(hif.HiroHifStrategy)
    h.s = NS(state=state, observe=lambda **k: NS(fields={}), record=lambda *a, **k: None)
    h.deciders = NS(decide=decide)
    h.rec = NS(log=lambda *a, **k: None)
    h._note_fallback = lambda *a: None
    h._rerolls_this_page = hif.HiroHifStrategy.MAX_REROLLS_PER_PAGE  # 本页已到上限
    h._act = lambda commit, action, **k: acted.append(action) or NS(ok=True)
    monkeypatch.setattr(hif, "device", NS(screenshot=lambda: None))
    monkeypatch.setattr("hiro.vision.extract.extract", lambda page, img: ({"candidates": cands}, 0.0))
    h.on_select_card(ctx)
    assert seen == [1, 0] and acted == [Action.activate_effect(2)]
