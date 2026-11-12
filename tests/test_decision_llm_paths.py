"""决策点补全（总控 11-13）：规则 / 模拟拿得准的照旧直接给；拿不准的交 LLM；LLM 不可用或输出非法再兜底。
每条新的 LLM 路径一个开关、默认关（HIRO_PRODUCE_LLM=换卡2,删卡… 或 all 打开）。"""

import pytest

from hiro.brain import deciders as dc
from hiro.brain.deciders import ProduceDeciders
from hiro.brain.llm import MockLLM
from hiro.brain.state import CAMPUS_HIRO
from hiro.contracts import GameState

pytestmark = pytest.mark.master

JUNK = "p_card-02-act-0_037"  # 初始卡（3 档）
OK_A = "p_card-02-act-2_047"  # 一般的牌（4 档）
OK_B = "p_card-02-men-2_008"


def _change2(cards, deck=None):
    produce = {"mode": "produce-007", "step": 8}
    if deck is not None:
        produce["deck"] = [{"card_id": c, "upgrade": 0} for c in deck]
    return GameState.from_dict({"mode": "produce", "page": {"name": "SKILL_CARD_CHANGE_2", "area": "produce"}, "produce": produce,
                                "page_fields": {"cards": [dict(index=i, card_id=c, upgrade=0) for i, c in enumerate(cards)]}})


@pytest.fixture(autouse=True)
def _paths_off(monkeypatch):
    monkeypatch.delenv("HIRO_PRODUCE_LLM", raising=False)


def test_switch_names_and_default_off(monkeypatch):
    assert not dc.llm_path_on("change_remove")
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "change_remove")
    assert dc.llm_path_on("change_remove") and not dc.llm_path_on("remove_card")
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "all")
    assert dc.llm_path_on("remove_card")


def test_change2_clear_junk_stays_rule_even_with_llm(monkeypatch):
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "all")
    llm = MockLLM(replies=[{"choice": 1, "reason": "不该被问到"}])
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("SKILL_CARD_CHANGE_2", _change2([JUNK, OK_A, OK_B], deck=[JUNK, OK_A, OK_B]))
    assert d.source == "rule" and d.action.args["remove_card_id"] == JUNK and not llm.calls


def test_change2_judgment_call_goes_to_llm(monkeypatch):
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "change_remove")
    llm = MockLLM(replies=[{"choice": 1, "reason": "留 A，换 B", "line": "这张…先换掉吧"}])
    cards = [OK_A, OK_B]
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("SKILL_CARD_CHANGE_2", _change2(cards, deck=cards))
    assert d.source == "llm" and d.action.args["remove_card_id"] == cards[1]
    assert llm.calls and "候选" in llm.calls[0][1]
    assert any("规则拿不准" in w for w in d.warnings)


def test_change2_switch_off_keeps_rule(monkeypatch):
    llm = MockLLM(replies=[{"choice": 1}])
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("SKILL_CARD_CHANGE_2", _change2([OK_A, OK_B], deck=[OK_A, OK_B]))
    assert d.source == "rule" and not llm.calls


def test_change2_bad_llm_output_falls_back_to_rule_choice(monkeypatch):
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "change_remove")
    llm = MockLLM(replies=[{"choice": 9}])
    plain = ProduceDeciders(CAMPUS_HIRO, None).decide("SKILL_CARD_CHANGE_2", _change2([OK_A, OK_B], deck=[OK_A, OK_B]))
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("SKILL_CARD_CHANGE_2", _change2([OK_A, OK_B], deck=[OK_A, OK_B]))
    assert d.source == "fallback" and d.action.args["remove_card_id"] == plain.action.args["remove_card_id"]
    assert d.llm and any("LLM" in w for w in d.warnings)


def test_report_counts_fallbacks_per_decider():
    from types import SimpleNamespace

    from hiro.loop.report import _by_decider_source

    steps = [SimpleNamespace(decision=SimpleNamespace(decider=d, source=s))
             for d, s in (("card_change", "rule"), ("card_change", "llm"), ("remove_card", "fallback"), ("remove_card", "fallback"))]
    got = _by_decider_source(steps)
    assert dict(got["card_change"]) == {"rule": 1, "llm": 1} and got["remove_card"]["fallback"] == 2


def test_golden_cases_rule_only_pass():
    """黄金用例（data/brain_cases/produce）在只有规则时也要过：LLM 路径兜底时不能选禁止项。"""
    from hiro.brain import cases

    passed, total, rows = cases.run(None, out=lambda *_: None)
    assert total > 0 and passed == total, [r for r in rows if not r["ok"]]


def _remove(cards, deck=None, mode="produce-007"):
    st = _change2(cards, deck)
    d = st.to_dict()
    d["page"]["name"] = "SKILL_CARD_REMOVAL"
    d["produce"]["mode"] = mode
    return GameState.from_dict(d)


def test_remove_clear_junk_stays_rule(monkeypatch):
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "remove_card")
    llm = MockLLM(replies=[{"choice": 1}])
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("SKILL_CARD_REMOVAL", _remove([JUNK, OK_A]))
    assert d.source == "rule" and d.action.args["card_id"] == JUNK and not llm.calls


def test_remove_judgment_call_can_choose_cancel(monkeypatch):
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "remove_card")
    llm = MockLLM(replies=[{"choice": 2, "reason": "两张都有用，不花 P 删"}])
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("SKILL_CARD_REMOVAL", _remove([OK_A, OK_B]))
    assert d.source == "llm" and d.action.args.get("cancel") is True
    opts = __import__("json").loads(llm.calls[0][1])["候选"]
    assert opts[-1]["名字"] == "不删（取消）" and len(opts) == 3
