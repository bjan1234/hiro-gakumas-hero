"""bench 中转层：局面 → UIObs、出招插件的动作映射与退回规则（不需要 gkbench / 模型：算法用替身）。"""

import pytest

from hiro.bench_bridge import advisor as A
from hiro.bench_bridge.screen import ScreenTracker, exam_fields, from_screen
from hiro.bench_bridge.uiobs import from_engine
from hiro.brain.cards import CardView, DrinkView
from hiro.brain.state import CAMPUS_HIRO, BattleState, ExamMemory
from hiro.contracts import Action


def _card(slot, cid, u=0, available=True, name=None):
    return CardView(slot, name or cid, cid, u, available, "active", 3, 0, None, "パラメータ+10")


def _state(hand, drinks=(), remaining=8, turn=1, statuses=None, motivation=5, impression=3):
    mem = ExamMemory(exam="r1")
    mem.turn = turn
    st = BattleState.build(mem, CAMPUS_HIRO, source="screen", remaining_turns=remaining, hp=20, genki=10, motivation=motivation,
                           impression=impression, score=1000, buffs={}, attr="Da", multiplier_permil=None, npc_scores=None,
                           my_rank_index=None, deck_count=None, pitem_charges=None, statuses=statuses, attr_permil={"Da": 30000},
                           hand=list(hand), drinks=list(drinks))  # fmt: skip
    return st, mem


# ---------------------------------------------------------------- 引擎局面 → UIObs
def _engine_card(cid, base=0, tmp=0, support=(), customize=(), grows=()):
    return {"card_id": cid, "base_upgrade": base, "tmp_upgrade": tmp, "support_upgrades": list(support),
            "customize_counts": list(customize), "custom_override": None, "grow_after": [{"id": g} for g in grows]}


def _engine_state(**kw):
    st = {
        "cards": [_engine_card("c-a", 1), _engine_card("c-b", 0, support=[1]), _engine_card("c-c"), _engine_card("c-d", customize=[2])],
        "zones": {"hand": [0, 1], "deck": [2], "grave": [3], "lost": [], "hold": []},
        "status": {"effects": [
            {"cls": "ReviewStatusEffect", "turn": 7, "limited": True, "passing": False, "value": 0, "extra": {}, "trig": None},
            {"cls": "AggressiveStatusEffect", "turn": -1, "limited": False, "passing": False, "value": 12, "extra": {}, "trig": None},
            {"cls": "LessonParameterMultipleStatusEffect", "turn": 2, "limited": True, "passing": False, "value": 300, "extra": {}, "trig": None},
            {"cls": "StaminaConsumptionDownStatusEffect", "turn": 3, "limited": True, "passing": True, "value": 0, "extra": {}, "trig": None},
            {"cls": "PlayableValueAddStatusEffect", "turn": 1, "limited": True, "passing": False, "value": 1, "extra": {}, "trig": None},
            {"cls": "TriggerEffectStatusEffect", "turn": -1, "limited": False, "passing": False, "value": 0, "extra": {},
             "trig": {"enchant_id": "enchant-x", "limit_count": 2, "trigger": {"id": "t"}}},
            {"cls": "TriggerEffectStatusEffect", "turn": -1, "limited": False, "passing": False, "value": 0, "extra": {},
             "trig": {"enchant_id": "enchant-used", "limit_count": 0, "trigger": {"id": "t2"}}},
        ], "idol_type": 0, "idol_step": 0},
        "current_turn": 3, "limit_turn": 12, "extra_turn": 0, "turn_types": [1, 2, 3] * 4,
        "bonus_permil": [[1, 31000], [2, 32000], [3, 20000]], "stamina": 20, "max_stamina": 33, "block": 5, "score": 900,
        "remaining_actions": 1, "turn_card_play_count": 0, "drinks": ["pdrink-1"], "play_log": [],
    }
    st.update(kw)
    return st


def test_from_engine_maps_statuses_and_zones():
    obs = from_engine(_engine_state(), {"produce": "produce-008", "step": "AUDITION_MID1", "plan": 3, "crit": [1, 2, 3]},
                      [("play", 0), ("drink", 0), ("end",)], customize_ids=lambda cid, u: ["cz-1"])
    st = {(k, t): v for k, v, t in obs["status"]}
    assert st[("review", -1)] == 7.0  # 好印象的数量存在 turn 里
    assert st[("aggressive", -1)] == 12.0
    assert st[("lesson_parameter_multiple", 3)] == pytest.approx(0.3)  # 千分比 → 小数；没有 passing 时画面 = turn + 1
    assert st[("stamina_consumption_down", 3)] == 1.0  # passing 时画面 = turn
    assert obs["num"]["playable"] == 2  # 追加行动算进「还能出几张」
    assert obs["ench"] == [["enchant-x", 2, -1]]  # 次数用完的不显示
    assert obs["hand"] == [{"id": "c-a", "u": 1, "p": 1}, {"id": "c-b", "u": 1, "p": 0}]  # 支援强化计入 u
    assert obs["grave"] == [{"id": "c-d", "u": 0, "c": [["cz-1", 2]]}]
    assert obs["legal"] == [["play", 0], ["drink", 0], ["end"]]
    assert obs["exam"]["permil"] == [31000, 32000, 20000] and obs["exam"]["limit"] == 12


# ---------------------------------------------------------------- 画面读数 → UIObs
def test_screen_tracker_draws_and_reshuffles():
    t = ScreenTracker([("a", 0), ("b", 0), ("c", 1)], trend=("Vo", "Da", "Vi"))
    st, mem = _state([_card(0, "a"), _card(1, "b")], turn=1)
    t.observe(st, mem)
    assert dict(t.deck) == {("c", 1): 1}
    t.played_card(st.hand[0])
    st2, mem2 = _state([_card(0, "b")], turn=1)
    t.observe(st2, mem2)
    assert dict(t.grave) == {("a", 0): 1} and t.played == [{"id": "a", "u": 0}]
    # 换回合：剩下的 b 进弃牌；抽到 c（山札）和 a（山札空，弃牌重洗）
    st3, mem3 = _state([_card(0, "c", 1), _card(1, "a")], turn=2)
    t.observe(st3, mem3)
    assert t.played == [] and dict(t.deck) == {("b", 0): 1} and not t.grave


def test_types_fill_known_turns_and_final_three():
    t = ScreenTracker([], trend=("Vo", "Da", "Vi"))
    t.attrs = {1: "Da", 2: "Vi"}
    # 7 回合：1、2 已见；末三回合 流3 → 流2 → 流1；其余按 流1
    assert t.types(3, 7) == [2, 3, 1, 1, 3, 2, 1]


def test_from_screen_builds_obs_and_drink_slots():
    hand = [_card(0, "p_card-a", 1), _card(1, "p_card-b", 0, available=False)]
    drinks = [DrinkView(2, "饮料2", "pdrink-2", ""), DrinkView(0, "饮料0", "pdrink-0", "")]
    statuses = [{"type": "ProduceExamEffectType_ExamParameterBuff", "name": "好調", "value": 3, "unit": "turns"},
                {"type": "ProduceExamEffectType_ExamLessonValueMultiple", "name": "パラメータ上昇量増加", "value": 30, "unit": "percent"}]
    st, mem = _state(hand, drinks, remaining=8, turn=3, statuses=statuses)
    t = ScreenTracker([("p_card-a", 1), ("p_card-b", 0), ("p_card-c", 0)], trend=("Vo", "Da", "Vi"))
    t.observe(st, mem)
    obs, slot_of = from_screen(st, mem, st.legal_actions(), t, exam_fields("r2", idol="i_card-shro-3-007", plan=3))
    assert obs["exam"]["produce"] == "produce-008" and obs["exam"]["step"] == "AUDITION_MID2"
    assert obs["exam"]["turn"] == 3 and obs["exam"]["limit"] == 10 and len(obs["exam"]["types"]) == 10
    assert obs["hand"] == [{"id": "p_card-a", "u": 1, "p": 1}, {"id": "p_card-b", "u": 0, "p": 0}]
    assert obs["drinks"] == ["pdrink-0", "pdrink-2"] and slot_of == [0, 2]
    assert ["drink", 1] in obs["legal"] and ["end"] in obs["legal"] and ["play", 1] not in obs["legal"]
    kinds = {k: (v, n) for k, v, n in obs["status"]}
    assert kinds["parameter_buff"] == (3.0, 3) and kinds["lesson_parameter_multiple"][0] == pytest.approx(0.3)
    assert kinds["aggressive"] == (5.0, -1) and kinds["review"] == (3.0, -1)
    assert obs["deck"] == [{"id": "p_card-c", "u": 0}]


def test_exam_fields_labels():
    assert exam_fields("qualify-3", idol=None, plan=3)["step"] == "AUDITION_FINAL"
    assert exam_fields("qualify-1", idol=None, plan=3)["produce"] == "produce-007"
    assert exam_fields("r1#2", idol=None, plan=3)["step"] == "AUDITION_MID1"


# ---------------------------------------------------------------- 出招插件
class _Algo:
    name = "fake"
    sees_seed = privileged = False

    def __init__(self, action):
        self.action = action
        self.seen = []

    def begin(self, ctx):
        pass

    def decide(self, ctx):
        from types import SimpleNamespace

        self.seen.append(ctx.obs)
        return SimpleNamespace(action=self.action, meta={"top": [[list(self.action), 0.9]], "score_quantiles": {"50%": 123}})


def _advisor(monkeypatch, action):
    algo = _Algo(action)
    monkeypatch.setattr(A, "load_algo", lambda *a, **k: algo)
    adv = A.BenchAdvisor(CAMPUS_HIRO)
    adv.on_round_start(1, {"exam": "r1", "idol": "i_card-shro-3-007", "deck": [("p_card-a", 0), ("p_card-b", 0)]})
    return adv, algo


@pytest.mark.bench_on
def test_bench_drink_maps_back_to_screen_slot(monkeypatch):
    adv, algo = _advisor(monkeypatch, ("drink", 1))
    st, mem = _state([_card(0, "p_card-a")], [DrinkView(0, "饮料0", "pdrink-0", ""), DrinkView(3, "饮料3", "pdrink-3", "")])
    d = adv.decide(st, mem, None, [Action.from_legal(a) for a in st.legal_actions()])
    assert d.source == "bench" and d.action.legal_key() == "drink:3"
    assert algo.seen[0]["drinks"] == ["pdrink-0", "pdrink-3"]


@pytest.mark.bench_on
def test_bench_illegal_action_falls_back_to_rules_without_llm(monkeypatch):
    monkeypatch.setenv("HIRO_LLM", "should-not-be-used")
    adv, _ = _advisor(monkeypatch, ("play", 5))
    assert adv.rules.brain.llm is None
    st, mem = _state([_card(0, "p_card-a"), _card(1, "p_card-b")])
    legal = [Action.from_legal(a) for a in st.legal_actions()]
    d = adv.decide(st, mem, None, legal)
    assert d.source != "bench" and d.action.legal_key() in {a.legal_key() for a in legal}
    assert any("不在合法动作" in w for w in d.warnings)


@pytest.mark.bench_on
def test_bench_load_failure_uses_rules(monkeypatch):
    def boom(*a, **k):
        raise ImportError("No module named 'gkbench'")

    monkeypatch.setattr(A, "load_algo", boom)
    adv = A.BenchAdvisor(CAMPUS_HIRO)
    assert adv.algo is None and "gkbench" in adv.load_error and adv.rules.brain.llm is None
    st, mem = _state([_card(0, "p_card-a")])
    d = adv.decide(st, mem, None, [Action.from_legal(a) for a in st.legal_actions()])
    assert d.source != "bench"


def test_bench_off_restores_rule_llm_advisor(monkeypatch):
    called = []
    monkeypatch.setattr(A, "load_algo", lambda *a, **k: called.append(1))
    adv = A.BenchAdvisor(CAMPUS_HIRO, llm="LLM")
    assert adv.algo is None and not called and adv.load_error == "HIRO_BENCH_ADVISOR=0"
    assert adv.rules.brain.llm == "LLM"  # 关掉 bench：原来的规则 + LLM


def test_rejects_seed_seeing_algorithms(monkeypatch):
    class Seer(_Algo):
        sees_seed = True

    import sys
    import types

    fake = types.ModuleType("gkbench.algos")
    fake.make = lambda spec: Seer(("end",))
    monkeypatch.setitem(sys.modules, "gkbench", types.ModuleType("gkbench"))
    monkeypatch.setitem(sys.modules, "gkbench.algos", fake)
    with pytest.raises(ValueError, match="看种子"):
        A.load_algo("seer")


class _FakeEnchants:
    def item(self, item_id):
        return (("enchant-item", 5, -1),) if item_id == "pitem-x" else ()

    def card(self, card_id, upgrade):
        return {"c-sus": (("enchant-sus", -1, 2, False),), "c-once": (("enchant-once", 1, -1, True),)}.get(card_id, ())


def test_tracker_records_item_and_played_card_enchants():
    t = ScreenTracker([("c-sus", 0), ("c-once", 0), ("c-x", 0)], trend=("Vo", "Da", "Vi"), enchants=_FakeEnchants(), items=["pitem-x"])
    assert t.ench == [["enchant-item", 5, -1]]
    st, mem = _state([_card(0, "c-sus"), _card(1, "c-once")], turn=1)
    t.observe(st, mem)
    t.played_card(st.hand[0])
    t.played_card(st.hand[1])
    t.played_card(st.hand[1])  # 只第一次打出时挂
    assert sorted(map(tuple, t.ench)) == [("enchant-item", 5, -1), ("enchant-once", 1, -1), ("enchant-sus", -1, 2)]
    st2, mem2 = _state([_card(0, "c-x")], turn=2)
    t.observe(st2, mem2)
    st3, mem3 = _state([_card(0, "c-x")], turn=3)
    t.observe(st3, mem3)
    assert ["enchant-sus", -1, 1] not in t.ench and not any(e[0] == "enchant-sus" for e in t.ench)  # 2 回合后消失


def test_track_all_follows_bench_switch(monkeypatch):
    from hiro.sim import screen_source as ss

    monkeypatch.setenv("HIRO_BENCH_ADVISOR", "1")
    assert ss._track_all()
    monkeypatch.setenv("HIRO_EXAM_SIM_TRACK_ALL", "0")
    assert not ss._track_all()
    monkeypatch.delenv("HIRO_EXAM_SIM_TRACK_ALL")
    monkeypatch.setenv("HIRO_BENCH_ADVISOR", "0")
    assert not ss._track_all()


def test_setup_puts_engine_on_path(monkeypatch):
    """`python -m hiro.bench_bridge setup / check` 单独跑时还没导入 hiro.sim：gkbench 导入 gakumas_exam 会失败
    （Windows 上 setup 报 No module named 'gakumas_exam'，模型和主数据都没准备）。load_algo / ensure_master 先把引擎放进 sys.path。"""
    import importlib
    import sys

    from hiro.bench_bridge import advisor
    from hiro.sim import ROOT

    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(ROOT)])
    for m in [m for m in sys.modules if m == "hiro.sim" or m.startswith(("hiro.sim.", "gakumas_exam"))]:
        monkeypatch.delitem(sys.modules, m)
    advisor._engine_on_path()
    assert str(ROOT) in sys.path
    importlib.import_module("gakumas_exam.catalog")


def test_setup_failure_prints_real_reason(monkeypatch, capsys):
    """setup 失败时打印异常类型、出错位置和按类型给的提示，不再一律猜「网络？」。"""
    from hiro.bench_bridge import __main__ as M
    from hiro.bench_bridge import advisor

    def boom(**k):
        import gakumas_exam_missing_for_test  # noqa: F401

    monkeypatch.setattr(advisor, "load_algo", boom)
    assert M.main(["setup"]) == 1
    out = capsys.readouterr().out
    assert "ModuleNotFoundError: No module named 'gakumas_exam_missing_for_test'" in out
    assert "出错位置：" in out and "test_bench_bridge.py" in out
    assert "缺 Python 模块 gakumas_exam_missing_for_test" in out and "网络" not in out


@pytest.mark.bench_on
def test_engine_path_takes_screen_truths(monkeypatch):
    """模拟器合成开局只按画面粗对齐：回合属性是占位顺序、手牌强化被模拟器自己的随机支援强化抬高、やる気有偏差。
    画面能看到的一律用画面的，引擎只补画面看不到的（牌区内容、附魔、其余状态）。dmmw1 R1 离线重放发现。"""
    monkeypatch.setattr(A, "OBS_SOURCE", "engine")
    adv, algo = _advisor(monkeypatch, ("play", 0))
    eng = _engine_state(turn_types=[1, 1, 1, 1, 1, 1, 1, 1], limit_turn=8, current_turn=1, score=999, stamina=5)
    eng["cards"][0] = _engine_card("p_card-a", 1, tmp=2)  # 引擎 +++，画面 +
    eng["cards"][1] = _engine_card("p_card-b", 0)
    eng["status"]["effects"][1]["value"] = 26  # やる気 引擎 26，画面 37
    st, mem = _state([_card(0, "p_card-a", 1), _card(1, "p_card-b", 0)], remaining=8, turn=1, motivation=37, impression=3)
    st.attr = "Vi"
    st.sim_game = object()
    monkeypatch.setattr(A, "_engine_state", lambda game: eng)
    adv.decide(st, mem, None, [Action.from_legal(a) for a in st.legal_actions()])
    obs = algo.seen[-1]
    assert obs["exam"]["types"][0] == 3  # 本回合 Vi（画面），不是占位的 Vo
    assert obs["exam"]["permil"][1] == 30000  # 画面见过的 Da 倍率
    assert [c["u"] for c in obs["hand"]] == [1, 0]
    assert obs["num"]["score"] == 1000 and obs["num"]["stamina"] == 20 and obs["num"]["block"] == 10
    st_ = {k: v for k, v, _ in obs["status"]}
    assert st_["aggressive"] == 37.0 and st_["review"] == 3.0
    assert obs["grave"]  # 牌区仍来自引擎


@pytest.mark.bench_on
def test_unread_hand_upgrade_falls_back_to_deck_base(monkeypatch):
    adv, algo = _advisor(monkeypatch, ("play", 0))
    adv.on_round_start(1, {"exam": "r1", "idol": "i_card-shro-3-007", "deck": [("p_card-a", 1), ("p_card-b", 0)]})
    st, mem = _state([_card(0, "p_card-a", None), _card(1, "p_card-b", 0)])
    adv.decide(st, mem, None, [Action.from_legal(a) for a in st.legal_actions()])
    assert [c["u"] for c in algo.seen[-1]["hand"]] == [1, 0]  # 画面读不到强化：用培育牌组里的强化次数


@pytest.mark.bench_on
def test_default_uses_screen_path_even_with_sim_game(monkeypatch):
    adv, algo = _advisor(monkeypatch, ("play", 0))
    st, mem = _state([_card(0, "p_card-a", 0)])
    st.sim_game = object()
    monkeypatch.setattr(A, "_engine_state", lambda game: (_ for _ in ()).throw(AssertionError("不该读引擎局面")))
    d = adv.decide(st, mem, None, [Action.from_legal(a) for a in st.legal_actions()])
    assert d.source == "bench" and "画面读数" in d.reason


def test_types_respect_turn_quota():
    """未知回合按配额填（dmmt2：R1 实际 Vo4 / Da3 / Vi2，以前未知回合一律填 流1 = Vo）。"""
    t = ScreenTracker([], trend=("Vo", "Da", "Vi"))
    t.attrs = {1: "Vo"}
    alloc = {"random_prefix_counts": {"Vo": 3, "Da": 2, "Vi": 1}, "fixed_tail": ["Vi", "Da", "Vo"]}
    types = t.types(1, 9, alloc)
    assert types[-3:] == [3, 2, 1]
    assert sorted(types[:6]) == [1, 1, 1, 2, 2, 3] and types[0] == 1


def test_from_screen_fills_unread_numbers_and_permil():
    t = ScreenTracker([("p_card-a", 0)], trend=("Vo", "Da", "Vi"))
    ex = exam_fields("r1", idol=None, plan=3)
    ex["permil_default"] = {"Vo": 31000, "Da": 32000, "Vi": 20000}
    st, mem = _state([_card(0, "p_card-a")])
    st.attr_permils = {}
    t.observe(st, mem)
    obs, _ = from_screen(st, mem, st.legal_actions(), t, ex)
    assert obs["exam"]["permil"] == [31000, 32000, 20000]  # 开考第一步还没读到倍率：用记下的 / 参考值，不给 0
    st.score, st.genki = None, None  # 这一帧分数 / 元気没读出来
    obs, _ = from_screen(st, mem, st.legal_actions(), t, ex)
    assert obs["num"]["score"] == 1000 and obs["num"]["block"] == 10  # 用上一次的读数，不是 0


class _Facts(_FakeEnchants):
    """主数据替身：c-sleepy 打出时往山札塞一张眠気；眠気回合结束除外；d-buff 饮料挂附魔。"""

    def creates(self, card_id, upgrade):
        return (("p_card-00-acc-0_002", 0, 1),) if card_id == "c-sleepy" else ()

    def end_turn_lost(self, card_id, upgrade):
        return card_id == "c-endlost"

    def lost_on_play(self, card_id, upgrade):
        return card_id == "p_card-00-acc-0_002"

    def drink(self, drink_id):
        return (("enchant-drink", -1, -1),) if drink_id == "d-buff" else ()

    def enchant_card(self, name):
        return {"ワクワク": "c-sus"}.get(name)


def test_tracker_adds_created_cards_and_end_turn_lost():
    """dmmt / 履歴对照：山札总少一张 眠気（打出 気まぐれハート 等时塞进山札，画面看不到），第二张眠気被抽到时还误判成洗牌、弃牌清空。"""
    t = ScreenTracker([("c-sleepy", 0), ("c-x", 0), ("c-y", 0)], trend=("Vo", "Da", "Vi"), enchants=_Facts())
    st, mem = _state([_card(0, "c-sleepy"), _card(1, "c-x")], turn=1)
    t.observe(st, mem)
    t.played_card(st.hand[0])
    assert t.deck[("p_card-00-acc-0_002", 0)] == 1  # 打出时塞进山札
    st2, mem2 = _state([_card(0, "c-x"), _card(1, "p_card-00-acc-0_002")], turn=1)
    t.observe(st2, mem2)  # 抽到那张眠気：从山札扣，不触发洗牌
    assert ("c-sleepy", 0) in t.grave and t.deck[("p_card-00-acc-0_002", 0)] == 0
    t.played_card(st2.hand[1])  # 打出眠気：主数据 playMovePositionType = Lost
    st3, mem3 = _state([_card(0, "c-y")], turn=2)
    t.observe(st3, mem3)  # 换回合：眠気 除外，c-x 进弃牌
    assert t.lost[("p_card-00-acc-0_002", 0)] == 1 and t.grave[("c-x", 0)] == 1


def test_tracker_drink_enchant_pitem_charges_and_status_names():
    t = ScreenTracker([("c-a", 0)], trend=("Vo", "Da", "Vi"), enchants=_Facts(), items=["pitem-x"])
    t.drank("d-buff")
    assert ["enchant-drink", -1, -1] in t.ench
    st, mem = _state([_card(0, "c-a")], statuses=[{"type": None, "name": "ワクワク", "value": 1, "unit": "stack"}])
    st.pitem_charges = 3
    t.observe(st, mem)
    obs, _ = from_screen(st, mem, st.legal_actions(), t, exam_fields("r1", idol=None, plan=3))
    assert ["enchant-item", 3, -1] in obs["ench"]  # P 道具次数用画面读数
    assert any(e[0] == "enchant-sus" for e in obs["ench"])  # 状态栏有这张卡的持续效果、跟踪漏了：补上


def test_tracker_does_not_reshuffle_when_deck_still_has_cards():
    """qualifydmmw1 T3：持续效果塞进山札的第二张眠気被抽到，跟踪以为洗牌了，把 8 张弃牌倒回山札（存档：弃牌 8 张）。
    实际只有山札抽空才洗牌：山札还有牌时，找不到的卡当作看不见的插入。"""
    t = ScreenTracker([("c-a", 0), ("c-b", 0), ("c-c", 0), ("c-d", 0), ("c-e", 0), ("c-f", 0)], trend=("Vo", "Da", "Vi"))
    t.grave[("p_card-00-acc-0_002", 0)] = 1
    t.grave[("c-z", 0)] = 1
    st, mem = _state([_card(0, "p_card-00-acc-0_002"), _card(1, "c-a")], turn=3)
    t.observe(st, mem)
    assert sum(t.grave.values()) == 2 and sum(t.deck.values()) == 5


def test_layer_units_follow_gkms_uiobs():
    """单位照 GKMS UIObs 的实际输出：熱意獲得量増加是绝对量（不除 1000），倍率类千分比写成小数（3940a9 11-14 对拍发现）。"""
    from hiro.bench_bridge.uiobs import statuses

    def layer(cls, value):
        return {"cls": cls, "turn": 2, "limited": True, "passing": False, "value": value, "extra": {}, "trig": None}

    effects = [layer("EnthusiasticAdditiveStatusEffect", 10), layer("LessonBuffMultipleStatusEffect", 250),
               layer("FullPowerPointAdditiveStatusEffect", 400)]  # fmt: skip
    got = {k: v for k, v, _ in statuses({"status": {"effects": effects}})}
    assert got == {"enthusiastic_add": 10.0, "lesson_buff_multiple": 0.25, "full_power_point_add": 0.4}


TOWER_LO = {"produce_id": "tower", "layer": 15, "idol_card_id": "i_card-ttmr-2-000", "max_stamina": 46,
            "score_bonus_permils": [23090, 11980, 2600],
            "exam": {"produce_exam_battle_config_id": "p_exam_battle_config-tower_001-1_2_3-4_5_6-turn_15"},
            "produce_cards": ["p_card-a+1", "p_card-b/p_card_custom-x", "p_card-c+2/p_card_custom-y"]}  # fmt: skip


def test_tower_context_from_loadout():
    from hiro.bench_bridge.screen import tower_context

    tc = tower_context(TOWER_LO)
    assert tc["turns"] == 15 and tc["permil_fixed"] == {"Vo": 23090, "Da": 11980, "Vi": 2600}
    assert tc["max_stamina"] == 46 and tc["idol"] == "i_card-ttmr-2-000"
    assert tc["deck"] == [("p_card-a", 1), ("p_card-b", 0), ("p_card-c", 2)]
    assert tower_context({**TOWER_LO, "score_bonus_permils": {"1": 1, "2": 2, "3": 3}})["permil_fixed"] == {"Vo": 1, "Da": 2, "Vi": 3}
    assert tower_context({"turns": 15, "max_stamina": 46})["turns"] == 15  # 驱动手写的最小编成


def test_from_screen_tower_uses_loadout_after_restart():
    """2026-11-14 Mac 15 层：驱动中途重启，本场计数从 T1 开始（实际第 5 回合），limit 算成 11；开考只读到 Vo 倍率，三项都填成 23090；
    最大体力读不到给 0。有编成时：turn 按残りターン倒推、limit 固定 15、倍率和最大体力用编成的。"""
    from hiro.bench_bridge.screen import tower_context

    st, mem = _state([_card(0, "p_card-a", 1)], remaining=11, turn=1)
    st.max_hp = None
    exam = {**exam_fields("tower-15", idol=None, plan=None), **{k: v for k, v in tower_context(TOWER_LO).items() if k != "deck"}}
    t = ScreenTracker([("p_card-a", 1), ("p_card-b", 0)])
    t.observe(st, mem)
    obs, _ = from_screen(st, mem, st.legal_actions(), t, exam)
    assert obs["exam"]["turn"] == 5 and obs["exam"]["limit"] == 15 and len(obs["exam"]["types"]) == 15
    assert obs["exam"]["permil"] == [23090, 11980, 2600] and obs["num"]["max_stamina"] == 46
    assert obs["exam"]["produce"] == "tower" and obs["exam"]["plan"] == 0


@pytest.mark.bench_on
def test_advisor_reads_tower_loadout_file(monkeypatch, tmp_path):
    p = tmp_path / "lo.json"
    p.write_text(__import__("json").dumps({"loadout": TOWER_LO}))
    monkeypatch.setenv("HIRO_TOWER_LOADOUT", str(p))
    algo = _Algo(("play", 0))
    monkeypatch.setattr(A, "load_algo", lambda *a, **k: algo)
    adv = A.BenchAdvisor(CAMPUS_HIRO)
    adv.on_round_start(1, {"exam": "tower-15", "idol": None, "deck": []})
    assert adv.exam["turns"] == 15 and adv.exam["max_stamina"] == 46 and adv.exam["idol"] == "i_card-ttmr-2-000"
    assert adv.deck == [("p_card-a", 1), ("p_card-b", 0), ("p_card-c", 2)]
    adv.on_round_start(1, {"exam": "r1", "idol": "i_card-shro-3-007", "deck": [("p_card-x", 0)]})  # H.I.F 不受影响
    assert "turns" not in adv.exam and adv.deck == [("p_card-x", 0)]


class _Cat:
    """Enchants 用的假主数据：one(表, 键, 变体)。"""

    def __init__(self, cards, effects):
        self.cards, self.effects = cards, effects

    def one(self, table, key, variant=None):
        return (self.cards if table == "ProduceCard" else self.effects).get(key)


PLAY_CAT = _Cat(
    cards={"now": {"playEffects": [{"produceExamEffectId": "add1"}]},
           "later": {"playEffects": [{"produceExamEffectId": "timer2"}]},
           "cond": {"playEffects": [{"produceExamEffectId": "add1", "produceExamTriggerId": "t-if"}]},
           "plain": {"playEffects": []}},
    effects={"add1": {"effectType": "ProduceExamEffectType_ExamPlayableValueAdd", "effectCount": 1},
             "add2": {"effectType": "ProduceExamEffectType_ExamPlayableValueAdd", "effectCount": 2},
             "timer2": {"effectType": "ProduceExamEffectType_ExamEffectTimer", "effectValue1": 1, "chainProduceExamEffectIds": ["draw", "add2"]},
             "draw": {"effectType": "ProduceExamEffectType_ExamCardDraw"}},
)  # fmt: skip


def test_plays_added_from_master():
    from hiro.bench_bridge.enchants import Enchants

    e = Enchants(PLAY_CAT)
    assert e.plays_added("now", 0) == ((0, 1),)
    assert e.plays_added("later", 0) == ((1, 2),)  # 次のターン、+2
    assert e.plays_added("cond", 0) == ()  # 带触发条件的不算
    assert e.plays_added("plain", 0) == ()


def test_plays_left_counts_known_extra_plays_and_never_drops_below_one():
    """2026-11-14 run-15d：画面读不到剩余出牌次数，playable 一直填 1。现在按自己打出的卡算确定多出的次数；只是 UINet 的输入，不剪合法动作。"""
    from hiro.bench_bridge.enchants import Enchants

    t = ScreenTracker([("now", 0), ("later", 0), ("plain", 0), ("plain", 0)], enchants=Enchants(PLAY_CAT))
    st, mem = _state([_card(0, "now"), _card(1, "plain"), _card(2, "later")], turn=1)
    t.observe(st, mem)
    assert t.plays_left() == 1
    t.played_card(_card(0, "now"))  # 本回合 +1：打了一张还剩 1
    assert t.plays_left() == 1
    t.played_card(_card(1, "plain"))  # 两张打完：按 1 + 1 − 2 = 0，但不报 0
    assert t.plays_left() == 1
    t.played_card(_card(2, "later"))  # 下回合 +2
    st2, mem2 = _state([_card(0, "plain")], turn=2)
    t.observe(st2, mem2)
    assert t.plays_left() == 3
    obs, _ = from_screen(st2, mem2, st2.legal_actions(), t, exam_fields("r1", idol=None, plan=None))
    assert obs["num"]["playable"] == 3 and obs["num"]["plays"] == 0
    assert any(a[0] == "play" for a in obs["legal"])  # 合法动作照旧
