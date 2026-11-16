"""hiro.search.exam_env：通用考试开局（初 / N.I.A 试镜、偶像之路共用）的写法换算。开局本身要主数据和引擎，另由离线脚本对 GKMS 核。"""

import pytest

from hiro.search import exam_env as E
from hiro.search.loadout import parse_deck_entry


def test_bonus_permils_list_and_dict():
    assert E.bonus_permils([1, 2, 3]) == {1: 1, 2: 2, 3: 3}
    assert E.bonus_permils({"1": 10, "2": 20, "3": 30}) == {1: 10, 2: 20, 3: 30}
    assert E.bonus_permils({1: 7, 2: 8, 3: 9}) == {1: 7, 2: 8, 3: 9}


def test_parse_deck_entry_accepts_gkms_card_dict():
    """bench 模板展开后的牌（初 / N.I.A 题）：{produce_card_id, current_upgrade_count, customizes}。"""
    card = {
        "produce_card_id": "p_card-x",
        "current_upgrade_count": 1,
        "customizes": [{"id": "c1", "customize_count": 2}],
    }
    assert parse_deck_entry(card) == ("p_card-x", 1, {"c1": 2})
    assert parse_deck_entry({"produce_card_id": "p_card-y", "base_upgrade_count": 1}) == ("p_card-y", 1, {})
    assert parse_deck_entry({"id": "p_card-z", "upgrade_count": 1}) == ("p_card-z", 1, {})
    assert parse_deck_entry("p_card-a+1/c1*2") == ("p_card-a", 1, {"c1": 2})


def test_support_number_is_permil(monkeypatch):
    """支援卡 "id:数字" 的数字是考试内强化概率（千分比），不是等级（gkbench 展开时叫 permil）。"""
    monkeypatch.setattr("gakumas_exam.loadout._support", lambda m, sid: {"produceCardUpgradeLessonParameterType": "T", "upgradeProduceCardSearchId": "S"},
                        raising=False)  # fmt: skip
    for s in ("s_card-3-0010:64", {"support_card_id": "s_card-3-0010", "permil": 64}):
        e = E._support(None, s)
        assert e["_supportCardId"] == "s_card-3-0010" and e["_produceCardUpgradePermil"] == 64


def test_lesson_and_unknown_round_are_unsupported():
    with pytest.raises(E.ExamUnsupported, match="课程"):
        E.from_hif_loadout({"round": "lesson", "produce_id": "produce-001", "idol_card_id": "x"})


def test_audition_row_picks_by_number(monkeypatch):
    rows = {("d", "produce-005", "ProduceStepType_AuditionMid2"): [{"number": 1, "id": "d"}, {"number": 3, "id": "d"}]}
    monkeypatch.setattr(E, "_difficulty_rows", lambda: rows)
    monkeypatch.setattr(E, "_idol_card", lambda cid: {"produceStepAuditionDifficultyId": "d"})
    assert E.audition_row("i", "produce-005", "mid2", 3)["number"] == 3
    with pytest.raises(E.ExamUnsupported, match="2 行"):
        E.audition_row("i", "produce-005", "mid2")  # 有几个可选、又没给编号：不猜
    with pytest.raises(E.ExamUnsupported, match="不是试镜"):
        E.audition_row("i", "produce-005", "lesson")


def test_objective_prefers_given_rivals():
    assert E.objective({}, [100, 300, 200])["rivals"] == [300, 200, 100]
