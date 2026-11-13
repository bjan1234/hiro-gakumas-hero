"""任务 ② 第 4 部分：SearchAdvisor——对齐过画面的引擎局面 → 和画面核对 → Rust GNRPA → 画面槽位；核不上 / 没局面退回 bench 中转层。"""

from types import SimpleNamespace

import pytest

from hiro.contracts import Action

pytestmark = pytest.mark.sim_master

DECK = [("p_card-02-men-1_032", 1), ("p_card-02-act-2_062", 1), ("p_card-02-men-3_040", 0), ("p_card-02-ido-3_105", 1), ("p_card-02-men-2_004", 0),
        ("p_card-02-act-1_037", 1), ("p_card-00-sup-3_152", 1), ("p_card-02-men-2_100", 1), ("p_card-02-act-3_186", 0), ("p_card-02-men-1_031", 0),
        ("p_card-02-men-2_052", 1), ("p_card-02-sup-3_094", 1)] * 2  # fmt: skip


@pytest.fixture()
def adv(monkeypatch):
    rs = pytest.importorskip("gakumas_exam_rs")
    if not hasattr(rs, "search"):
        pytest.skip("Rust 后端没有 search")
    monkeypatch.setenv("HIRO_BENCH_ADVISOR", "0")  # 退回时用规则，不加载 UINet
    monkeypatch.setenv("HIRO_EXAM_SEARCH_S", "0.3")
    monkeypatch.setenv("HIRO_EXAM_SEARCH_WORLDS", "2")
    from hiro.bench_bridge.advisor import BenchAdvisor
    from hiro.brain.state import CAMPUS_HIRO
    from hiro.contracts import Decision
    from hiro.search.advisor import SearchAdvisor

    # 退回的那一层（UINet → 规则）要完整的考试局面；这里只验搜索插件，退回换成桩
    monkeypatch.setattr(BenchAdvisor, "decide", lambda self, *a, **k: Decision(Action.skip(), "退回", "rule", None))

    a = SearchAdvisor(CAMPUS_HIRO, None)
    a.on_round_start(1, {"exam": "r2", "idol": "i_card-shro-3-007", "deck": [list(c) for c in DECK]})
    return a


def _game():
    from gakumas_exam.native_battle import maybe_native

    from hiro.sim import interval as iv

    env = maybe_native(iv._env(iv.R2Setup(deck=DECK, drinks=[], hp=20, max_hp=33, permil={"Vo": 37490, "Da": 36100, "Vi": 22860}), 7))
    env.rx.advance()
    return SimpleNamespace(env=env)


def _screen(game, *, wrong=False):
    rx = game.env.rx
    ids = [rx.card_info(g)[0] for g in rx.zone("hand")]
    if wrong:
        ids = ids[::-1] if len(set(ids)) > 1 else ["p_card-00-act-0_001"] + ids[1:]
    hand = [SimpleNamespace(slot=i, card_id=c, name=c, upgrade=0, available=True) for i, c in enumerate(ids)]
    c = rx.clone()
    c.advance()
    legal = [Action.play_card(int(a[1])) for a in c.legal_actions() if a[0] == "play"] + [Action.skip()]
    state = SimpleNamespace(hand=hand, drinks=[], sim_game=game, sim_exact_exam=True, hp=20, max_hp=33, genki=0, score=0,
                            remaining_turns=12, turn=1, motivation=0, impression=0)  # fmt: skip
    return state, legal


def test_search_picks_legal_action(adv):
    state, legal = _screen(_game())
    d = adv.decide(state, SimpleNamespace(turn=1), None, legal)
    assert d.source == "search" and d.action.legal_key() in {a.legal_key() for a in legal}
    assert "GNRPA" in d.reason and d.candidates


def test_mismatch_falls_back_then_turns_off(adv):
    from hiro.search import advisor as mod

    game = _game()
    state, legal = _screen(game, wrong=True)
    for _ in range(mod.MISS_LIMIT):
        d = adv.decide(state, SimpleNamespace(turn=1), None, legal)
        assert d.source != "search" and any("核不上" in w or "对不上" in w for w in d.warnings)
    assert adv.off_why and "连续" in adv.off_why
    good, legal2 = _screen(game)
    assert adv.decide(good, SimpleNamespace(turn=1), None, legal2).source != "search"  # 这场剩下的步不再搜


def test_no_engine_state_falls_back(adv):
    state, legal = _screen(_game())
    state.sim_game = None
    assert adv.decide(state, SimpleNamespace(turn=1), None, legal).source != "search"
