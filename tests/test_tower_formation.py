"""偶像之路编成决策（TOWER_FORMATION / TOWER_RETRY）：考试 × 主回忆用模拟评估排序，副回忆按倍率公式贪心挑；接近交 LLM；失败重试按差距。
层设置、倍率公式、评估函数都换成假的（只验证决策逻辑；真跑 bench 的对照在离线脚本里）。"""

import pytest

from hiro.brain.deciders import ProduceDeciders
from hiro.brain.llm import MockLLM
from hiro.brain.state import CAMPUS_HIRO
from hiro.contracts import ActionKind, GameState

LEX = {"tower_id": "tower_001-hmsz", "layer": 26, "mechanic": "exam_lesson_buff", "turns": 16, "border": 500000,
       "exam": {"produce_exam_battle_config_id": "cfg", "produce_exam_gimmick_effect_group_id": "g-0001",
                "produce_exam_battle_npc_group_id": "npc", "produce_item_ids": ["pitem_tower_001-exam_lesson_buff-1-stage_026"]}}  # fmt: skip


@pytest.fixture(autouse=True)
def _fake_tower(monkeypatch):
    from hiro.bench_bridge import tower as tw

    monkeypatch.setenv("HIRO_PRODUCE_LLM", "off")
    monkeypatch.setattr(tw, "layer_mechanics", lambda t, l: ["exam_lesson_buff"])
    monkeypatch.setattr(tw, "layer_exam", lambda t, l, m=None: dict(LEX))
    monkeypatch.setattr(tw, "score_bonus_permils", lambda cfg, params: [1000 + p for p in params])


def _cands(n=4):
    return [{"index": i, "memory_id": f"m{i}", "params": [1000 + 100 * i, 800, 600], "max_stamina": 60,
             "deck": [f"p_card-01-act-1_00{i}"], "items": ["pitem_00-3-010-0"], "drinks": []} for i in range(n)]  # fmt: skip


def _state(n=4, sub_slots=1):
    return GameState(page_fields={"tower_id": "tower_001-hmsz", "layer": 26, "idol_card_id": "i_card-hmsz-3-020", "sub_slots": sub_slots,
                                  "candidates": _cands(n)})


def _eval(table, noise=1000):
    def run(loadouts, seeds, **kw):
        return [[table[lo["produce_cards"][0][-1]] + ((i * 7) % 5 - 2) * noise for i in range(len(seeds))] for lo in loadouts]
    return run


def test_clear_winner_picked_by_sim(monkeypatch):
    monkeypatch.setattr(ProduceDeciders, "TOWER_EVAL", staticmethod(_eval({"0": 300000, "1": 520000, "2": 450000, "3": 200000})))
    d = ProduceDeciders(CAMPUS_HIRO, None).decide("TOWER_FORMATION", _state())
    assert d.source == "sim" and d.action.kind is ActionKind.SELECT_FORMATION
    a = d.action.args
    assert a["main"] == 1 and a["mechanic"] == "exam_lesson_buff" and a["subs"] and 1 not in a["subs"]
    assert a["subs"] == [3]  # 副回忆按倍率和挑：属性最高的（主回忆除外）


def test_close_call_goes_to_llm(monkeypatch):
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "tower_formation")
    monkeypatch.setattr(ProduceDeciders, "TOWER_EVAL", staticmethod(_eval({"0": 540000, "1": 541000, "2": 100000, "3": 100000}, noise=40000)))
    llm = MockLLM(replies=[{"choice": 1, "reason": "牌组更合这一层的机关"}])
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("TOWER_FORMATION", _state())
    assert d.source == "llm" and llm.calls


def test_eval_unavailable_falls_back_by_bonus(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("没有 GKMS")
    monkeypatch.setattr(ProduceDeciders, "TOWER_EVAL", staticmethod(boom))
    d = ProduceDeciders(CAMPUS_HIRO, None).decide("TOWER_FORMATION", _state())
    assert d.source == "fallback" and d.action.args["main"] == 3 and "模拟评估不可用" in d.reason


def test_missing_candidates_waits():
    d = ProduceDeciders(CAMPUS_HIRO, None).decide("TOWER_FORMATION", GameState(page_fields={"tower_id": "x", "layer": 1, "candidates": []}))
    assert d.action.kind is ActionKind.WAIT


def test_retry_rules(monkeypatch):
    monkeypatch.setattr(ProduceDeciders, "TOWER_EVAL", staticmethod(_eval({"0": 300000, "1": 520000, "2": 450000, "3": 200000})))
    dec = ProduceDeciders(CAMPUS_HIRO, None)
    first = dec.decide("TOWER_FORMATION", _state()).action.args
    base = {"tower_id": "tower_001-hmsz", "layer": 26, "border": 500000, "last_pick": first}
    near = dec.decide("TOWER_RETRY", GameState(page_fields={**base, "attempt": 1, "last_score": 480000})).action.args
    assert near["confirm"] and near["pick"] == first  # 差得不多：同编成再打
    far = dec.decide("TOWER_RETRY", GameState(page_fields={**base, "attempt": 2, "last_score": 200000})).action.args
    assert far["confirm"] and far["pick"]["main"] == 2  # 差得多：换评估排第二的
    stop = dec.decide("TOWER_RETRY", GameState(page_fields={**base, "attempt": 3, "last_score": 480000})).action.args
    assert stop == {"kind": "tower_retry", "confirm": False}
