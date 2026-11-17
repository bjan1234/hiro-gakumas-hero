"""初 / N.I.A 培育模拟（vendor/gakumas-player/gakumas_produce/hajime_nia.py）：主数据规则、评价公式、状态推进。

数字的出处见 docs/hajime-nia-mechanics.md。"""

import pytest

import hiro.sim  # noqa: F401  把 vendor/gakumas-player 放进 sys.path

pytestmark = pytest.mark.sim_master

HIRO = "i_card-skin-shro-3-007"


@pytest.fixture(scope="module")
def hn():
    from gakumas_produce import hajime_nia

    return hajime_nia


def test_hajime_regular_rules_from_master(hn):
    r = hn.rules("produce-001", HIRO)
    assert (r.family, r.steps, r.param_cap, r.action_points, r.drink_limit, r.retries) == ("hajime", 13, 1000, 15, 3, 3)
    # 中間：前 3 名过、900 分封顶；最終：前 3 名
    (mid,), (final,) = r.auditions["mid1"], r.auditions["final"]
    assert (mid.rank_threshold, mid.base_score, mid.force_end_score) == (3, 600, 900)
    assert (final.rank_threshold, final.base_score, final.force_end_score) == (3, 2450, 0)
    # 篠澤広（plan2 やる気）的课：通常 4 次、SP 3 次、追い込み 2 次
    da = {k[0]: [(x.turns, x.clear, x.perfect) for x in v] for k, v in r.lessons.items() if k[1] == "Da"}
    assert da["normal"] == [(6, 25, 50), (6, 25, 50), (7, 40, 80), (7, 40, 80)]
    assert da["sp"] == [(6, 40, 80), (7, 70, 140), (7, 70, 140)]
    assert da["hard"] == [(9, 75, 300), (9, 100, 400)]


def test_hajime_master_and_legend_lessons(hn):
    m = hn.rules("produce-003", HIRO)
    assert [(x.turns, x.clear, x.perfect) for x in m.lessons[("hard", "Vo")]] == [(9, 90, 360), (11, 165, 600)]
    leg = hn.rules("produce-006", HIRO)
    assert [x.perfect for x in leg.lessons[("sp", "Vi")]] == [160, 210, 310, 460, 710]


def test_nia_pro_rules_from_master(hn):
    r = hn.rules("produce-004", HIRO)
    assert (r.family, r.steps, r.param_cap) == ("nia", 27, 2000)
    assert [(t.number, t.vote_unlock, t.base_score) for t in r.auditions["final"]] == [
        (1, 0, 12800), (2, 28000, 20400), (3, 40000, 32550), (4, 57000, 58150)]
    assert all(t.rank_threshold == 1 for s in r.auditions.values() for t in s)
    assert r.self_lessons[(1, True)] == (8, 100) and r.self_lessons[(3, False)] == (6, 120)
    # 营业：卡 / 饮料 / P 点场所同票，绿（体力）少；大成功 = 1.3 倍；属性 60 / 80 / 100
    assert r.business[("before_1st", "produce_point")] == (2400, 3120, 60, {"ProducePointAddition": 50})
    assert r.business[("before_3rd", "stamina")] == (2800, 3640, 100, {"StaminaRecoverFix": 10})
    m = hn.rules("produce-005", HIRO)
    assert m.business[("before_2nd", "produce_card")][2] == 110 and m.param_cap == 2600


def test_hajime_evaluation_matches_wiki_table(hn):
    """wikiwiki「初_マスター育成」：最终属性和 3010（表里已扣掉第 1 名的 +90）时 A+ 要 15262、S 要 92100。"""
    p = {"Vo": 1003, "Da": 1003, "Vi": 1004}
    assert hn.hajime_evaluation(p, 15262, 1, 9999) == 11500
    assert hn.hajime_evaluation(p, 92100, 1, 9999) >= 13000
    p = {"Vo": 1136, "Da": 1137, "Vi": 1137}
    assert hn.hajime_evaluation(p, 6667, 1, 9999) in (11500, 11501)
    assert hn.hajime_evaluation(p, 25000, 1, 9999) in (13000, 13001)
    assert hn.hajime_evaluation(p, 150000, 1, 9999) in (14500, 14501)


def test_nia_evaluation_tiers(hn):
    assert hn.nia_vote_eval(20000, "produce-004") == 2000
    assert hn.nia_vote_eval(36036, "produce-004") == 3363
    assert hn.nia_vote_eval(150000, "produce-005") == 9700
    r = hn.rules("produce-004", HIRO)
    v = hn.nia_evaluation({"Vo": 2100, "Da": 900, "Vi": 0}, 0, "produce-004", r.param_cap)
    assert v == 6670  # (2000 + 900) × 2.3，Vo 截到上限 2000
    assert r.grade(11475) == "A"


def test_nia_sim_walk(hn):
    r = hn.rules("produce-004", HIRO)
    s = hn.Sim(r, params={"Vo": 155, "Da": 191, "Vi": 159}, growth_permil={"Vo": 1272, "Da": 1472, "Vi": 1135}, max_stamina=30)
    assert s.self_lesson("Da", sp=True) == 100 + 47 and s.stamina == 22 and s.pp == 20
    assert s.business("produce_point", "Vo", excellent=True) == 3120
    assert (s.params["Vo"], s.pp, s.stamina) == (215, 70, 17)
    assert s.business("stamina", "Vi", vote_permil=100) == 1870 and s.stamina == 22
    with pytest.raises(hn.Unsupported):
        s.audition("mid1", tier=3, score=5000, rank=1)  # 9000 票才能选第 3 档
    assert s.audition("mid1", tier=2, score=5000, rank=1, votes=4680, params={"Vo": 33, "Da": 74, "Vi": 63})
    assert s.phase() == 2
    s.self_lesson("Vo", sp=False)
    assert s.log[-1].detail["gain"] == 100 + 27
    s.stamina = 8
    with pytest.raises(hn.Unsupported):
        s.self_lesson("Da", sp=True)  # 体力 8 不高于消耗 8
    s.rest(before_audition=True)
    assert s.stamina == 8 + 15


def test_hajime_sim_walk(hn):
    r = hn.rules("produce-001", HIRO)
    s = hn.Sim(r, params={"Vo": 155, "Da": 187, "Vi": 159}, growth_permil={"Vo": 1272, "Da": 1472, "Vi": 1135}, max_stamina=30)
    assert s.lesson("Da", stamina_used=8) == 50 + 23  # 满分线 50，加成 +47.2%
    assert s.lesson("Da", score=30, stamina_used=4) == 30 + 14
    s.study({"Vo": 40, "Da": 40}, stamina_used=5)
    s.outing(pp_cost=0, recover_permil=300)
    assert s.stamina == 30 - 17 + 9
    with pytest.raises(hn.Unsupported):
        s.self_lesson("Da")
    s.rest()
    assert s.stamina == 30  # 22 + 21 截到上限
    with pytest.raises(hn.Unsupported):
        s.rest()  # 满体力不能休息
    assert s.audition("mid1", score=1200, rank=1) and s.results["mid1"]["score"] == 900  # 中間 900 封顶
    with pytest.raises(hn.Unsupported):
        s.evaluation()
    s.audition("final", score=15000, rank=1)
    e = s.evaluation()
    assert e["value"] == hn.hajime_evaluation(s.params, 15000, 1, 1000) and e["grade"]


def test_calendar(hn):
    weeks = hn.calendar("produce-003", 1)
    assert len(weeks) == 18 and weeks[7] == ["mid"] and weeks[17] == ["final"] and weeks[3] == ["outing", "consult"]
    with pytest.raises(hn.Unsupported):
        hn.calendar("produce-003")  # 三种周表要指定
    for pid in ("produce-001", "produce-002", "produce-004", "produce-005"):
        with pytest.raises(hn.Unsupported):
            hn.calendar(pid)
    doc = hn.calendar_document()
    assert doc["modes"]["produce-004"]["weeks"] == {"9": "audition", "18": "audition", "27": "audition"}
