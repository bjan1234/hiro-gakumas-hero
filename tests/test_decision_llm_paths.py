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


# ---- 饮料（select_drink / consult / drink_overflow 共用 drinks.choose + _drink_decision）
COFFEE, BLEND, COPY = "pdrink_02-1-008", "pdrink_02-3-007", "pdrink_02-3-010"  # やる気 2 档 ×2、特製 0 档


def _select_drink(ids):
    return GameState(page_fields={"candidates": [{"drink_id": d} for d in ids]})


def test_drink_same_tier_without_sim_goes_to_llm(monkeypatch):
    from hiro.brain import drinks as dk

    monkeypatch.setattr(dk, "SIM", False)
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "select_drink")
    llm = MockLLM(replies=[{"choice": 1, "reason": "ブレンド 更适合", "line": "こっちかな"}])
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("SELECT_DRINK", _select_drink([COFFEE, BLEND]))
    assert d.source == "llm" and dc.action_key(d.action) == "pick:1" and d.line == "こっちかな" and d.llm
    opts = __import__("json").loads(llm.calls[0][1])["候选"]
    assert len(opts) == 3 and opts[0]["社区排名"] == 1  # 规则的选择在第 0 个；不拿也在候选里


def test_drink_clear_tier_stays_rule(monkeypatch):
    from hiro.brain import drinks as dk

    monkeypatch.setattr(dk, "SIM", False)
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "all")
    llm = MockLLM(replies=[{"choice": 0}])
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("SELECT_DRINK", _select_drink([COFFEE, COPY]))
    assert d.source == "rule" and dc.action_key(d.action) == "pick:1" and not llm.calls


def test_drink_switch_off_and_bad_output(monkeypatch):
    from hiro.brain import drinks as dk

    monkeypatch.setattr(dk, "SIM", False)
    llm = MockLLM(replies=[{"choice": 7}])
    plain = ProduceDeciders(CAMPUS_HIRO, llm).decide("SELECT_DRINK", _select_drink([COFFEE, BLEND]))
    assert plain.source == "rule" and not llm.calls
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "select_drink")
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("SELECT_DRINK", _select_drink([COFFEE, BLEND]))
    assert d.source == "fallback" and d.action.args == plain.action.args and d.llm


def _fake_sim(monkeypatch, gains):
    """模拟换成固定结果：第 0 个是社区默认，gains 是其余候选的 (gain, se)。"""
    from hiro.sim import interval as iv
    from hiro.sim import resource as rv

    monkeypatch.setattr(rv, "setup_for", lambda exam, drinks=None, **_: ({"drinks": drinks}, []))
    monkeypatch.setattr(iv, "_with", lambda base, **kw: dict(base, **kw))
    rows = [{"mean": 1000, "gain": 0, "gain_se": 0, "n": 100}] + [{"mean": 1000 + g, "gain": g, "gain_se": se, "n": 100} for g, se in gains]
    monkeypatch.setattr(rv, "adaptive_eval", lambda setups, **_: rows[: len(setups)])
    from hiro.brain import drinks as dk

    monkeypatch.setattr(dk, "SIM", True)


def test_choose_marks_noise_level_gain_unsure(monkeypatch):
    from hiro.brain import drinks as dk

    opts = [dk.Option("a", "拿 A", [COFFEE]), dk.Option("b", "拿 B", [BLEND])]
    _fake_sim(monkeypatch, [(300, 400)])
    res = dk.choose(opts, "selection", 4, sim_context={"exam": "selection"})
    assert res["pick"].key == "a" and "噪声内" in res["unsure"]
    _fake_sim(monkeypatch, [(-300, 100)])
    assert dk.choose(opts, "selection", 4, sim_context={"exam": "selection"})["unsure"] is None  # 别的都不如社区默认：拿得准
    _fake_sim(monkeypatch, [(3000, 100)])
    monkeypatch.setattr(dk, "log_deviation", lambda rec: None)
    res = dk.choose(opts, "selection", 4, sim_context={"exam": "selection"})
    assert res["pick"].key == "b" and res["unsure"] is None  # 显著更好：模拟直接偏离


def test_golden_drink_cases_keep_llm_trace(monkeypatch):
    """相談走 go（预算记账）那条路时，LLM 的调用记录、来源也要带到最终决策上。"""
    from hiro.brain import cases

    monkeypatch.setenv("HIRO_PRODUCE_LLM", "consult,select_drink")
    case = next(c for c in cases.load_cases() if c["id"] == "consult-qualifydmmw1-254")
    st = GameState.from_dict(case["state"])
    from hiro.brain import drinks as dk

    monkeypatch.setattr(dk, "SIM", True)
    _fake_sim(monkeypatch, [(2000, 5000), (-100, 50), (-200, 50)])
    llm = MockLLM(replies=[{"choice": 1, "reason": "青汁"}])
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("CONSULT", st)
    assert d.source == "llm" and d.llm and llm.calls
    assert dc.action_key(d.action) != "buy:7"  # 改成了 LLM 选的第 1 个候选


# ---- 轮间：plan_tiered 标出拿不准（模拟方案更好但在噪声内）时，LLM 在社区默认 / 模拟方案里二选一
def _interval_setup(monkeypatch, unsure=True):
    import json
    from pathlib import Path

    from hiro.sim import interval as iv

    fix = json.loads((Path(__file__).parent / "fixtures" / "main18_interval.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(ProduceDeciders, "INTERVAL_DRINK_STEP", False)
    monkeypatch.setattr(dc, "_sim_ready", lambda: True)
    alt = {"target_hp": 0, "buy": [7], "upgrade": None, "labels": ["买饮料 初星スペシャル青汁"], "gain": 9000, "gain_se": 6000, "cost": 100}
    plan = {"target_hp": 0, "buy": [6], "upgrade": None, "labels": ["买饮料 ブーストエキス"], "gain": 8000, "gain_se": 6000, "cost": 100,
            "significant": True, "final": True, "rule_labels": ["买饮料 ブーストエキス"], "rule_notes": [], "deviation": None,
            "unsure": "模拟方案 买饮料 初星スペシャル青汁 比社区默认 +1,000 ± 8,000，在噪声内" if unsure else None, "alt": alt if unsure else None,
            "rows": [], "seconds": 1.0, "policy": "community", "seeds": [0]}  # fmt: skip
    monkeypatch.setattr(iv, "plan_tiered", lambda *a, **k: __import__("copy").deepcopy(plan))
    monkeypatch.setattr(iv, "CONTEXT", {"deck": fix["finals_context"]["deck"], "permil": fix["finals_context"]["permil"], "drinks": []})
    f = fix["121"]
    return GameState(page_fields=f["page_fields"], produce=dict(f["produce"], drink_capacity=4))


def test_interval_unsure_plan_llm_picks_sim_plan(monkeypatch):
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "interval")
    st = _interval_setup(monkeypatch)
    llm = MockLLM(replies=[{"choice": 1, "reason": "青汁更好", "line": "青汁で"}])
    dec = ProduceDeciders(CAMPUS_HIRO, llm)
    d = dec.decide("HIF_ROUND_INTERVAL", st)
    assert d.source == "llm" and d.action.args == {"index": 7} and d.llm and "LLM：青汁更好" in d.reason
    d2 = dec.decide("HIF_ROUND_INTERVAL", st)  # 同一次轮间不再问，来源仍是 LLM，调用记录只带一次
    assert len(llm.calls) == 1 and d2.source == "llm" and not d2.llm


def test_interval_unsure_off_or_sure_keeps_rule_plan(monkeypatch):
    llm = MockLLM(replies=[{"choice": 1}])
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("HIF_ROUND_INTERVAL", _interval_setup(monkeypatch))
    assert d.source == "rule" and d.action.args == {"index": 6} and not llm.calls
    monkeypatch.setenv("HIRO_PRODUCE_LLM", "interval")
    d = ProduceDeciders(CAMPUS_HIRO, llm).decide("HIF_ROUND_INTERVAL", _interval_setup(monkeypatch, unsure=False))
    assert d.source == "rule" and d.action.args == {"index": 6} and not llm.calls
