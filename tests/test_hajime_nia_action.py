"""初 / N.I.A 选行动（hiro.brain.hajime_nia.choose_action）：通关档的社区规则，每条规则至少一个用例。
设计稿 .temp/plans-20261112/初与NIA-决策-设计.md 第四节；规则文件 src/hiro/defaults/hajime_nia_rules.json。"""

import pytest

from hiro.brain.hajime_nia import Status, choose_action


def _opt(option, attr=None, sp=None, hp_cost=None):
    return {"option": option, "attr": attr, "sp": sp, "hp_cost": hp_cost}


def _st(**kw):
    base = dict(mode="produce-001", step=3, stamina=30, max_stamina=30, produce_point=0, params={"Vo": 300, "Da": 200, "Vi": 100})
    base.update(kw)
    return Status(**base)


def _pick(st, opts):
    i, reason, rules = choose_action(st, opts)
    return opts[i], reason, rules


# ---------------------------------------------------------------- 初


def test_hajime_lesson_week_takes_sp_lesson():
    opts = [_opt("training", "Vo", False), _opt("training", "Da", True), _opt("training", "Vi", False), _opt("rest")]
    o, reason, rules = _pick(_st(), opts)
    assert (o["option"], o["attr"], o["sp"]) == ("training", "Da", True)
    assert "hajime.lesson_first" in rules and "[g8-PRO]" in reason


def test_hajime_lesson_without_sp_takes_main_attr():
    opts = [_opt("training", "Vo", False), _opt("training", "Da", False), _opt("training", "Vi", False)]
    o, _, _ = _pick(_st(main_attr="Vi"), opts)
    assert o["attr"] == "Vi"


def test_hajime_class_before_other_actions():
    opts = [_opt("class", "Vo"), _opt("allowance"), _opt("outing"), _opt("rest")]
    o, _, rules = _pick(_st(stamina=25), opts)
    assert o["option"] == "class" and "hajime.lesson_first" in rules


def test_hajime_tired_outing_with_points():
    """体力少了 15 以上、没有课程 / 授業：P 点 ≥ 100 去外出。"""
    opts = [_opt("allowance"), _opt("outing"), _opt("rest")]
    o, _, rules = _pick(_st(stamina=12, produce_point=120), opts)
    assert o["option"] == "outing" and {"hajime.outing_when", "hajime.outing_vs_rest"} <= set(rules)


def test_hajime_tired_rest_without_points():
    opts = [_opt("allowance"), _opt("outing"), _opt("rest")]
    o, _, rules = _pick(_st(stamina=12, produce_point=40), opts)
    assert o["option"] == "rest" and "hajime.outing_vs_rest" in rules


def test_hajime_not_tired_takes_allowance():
    opts = [_opt("allowance"), _opt("outing"), _opt("rest")]
    o, _, _ = _pick(_st(stamina=28), opts)
    assert o["option"] == "allowance"


def test_hajime_rest_blocked_when_full():
    """体力满了不能休息：MASTER 只剩休息和外出（外出排最后）时，休息被拦下，选外出。"""
    opts = [_opt("rest"), _opt("outing")]
    o, _, rules = _pick(_st(mode="produce-003", step=9, stamina=30), opts)
    assert o["option"] == "outing" and "hajime.rest_full" in rules


def test_hajime_master_no_rest_before_week6():
    opts = [_opt("rest"), _opt("shop")]
    o, _, rules = _pick(_st(mode="produce-003", step=4, stamina=10, produce_point=0), opts)
    assert o["option"] == "shop" and "hajime.master_rest_week6" in rules


def test_hajime_master_avoids_outing():
    opts = [_opt("outing"), _opt("allowance")]
    o, _, rules = _pick(_st(mode="produce-003", step=9, stamina=10, produce_point=150), opts)
    assert o["option"] == "allowance" and "hajime.master_outing_avoid" in rules


def test_hajime_lesson_week_very_low_stamina_rests():
    """课程周体力太低（< 8）时休息，不硬上课程。"""
    opts = [_opt("training", "Vo", True), _opt("rest")]
    o, _, _ = _pick(_st(stamina=5), opts)
    assert o["option"] == "rest"


# ---------------------------------------------------------------- N.I.A


def _nia(**kw):
    base = dict(mode="produce-004", step=3, stamina=20, max_stamina=30, produce_point=0, params={"Vo": 300, "Da": 200, "Vi": 150}, rest_left=4)
    base.update(kw)
    return _st(**base)


def test_nia_always_sp_lesson_lowest_attr():
    opts = [_opt("training", "Vo", True, 8), _opt("training", "Vi", True, 8), _opt("training", "Da", False, 6), _opt("sales")]
    o, _, rules = _pick(_nia(), opts)
    assert (o["attr"], o["sp"]) == ("Vi", True) and "nia.lesson_sp" in rules


def test_nia_lesson_needs_more_stamina_than_cost():
    """体力 ≤ 消耗不能上课（SP 耗 8）：体力 8 时 SP 上不了，改上普通课程（耗 6）。"""
    opts = [_opt("training", "Vo", True, 8), _opt("training", "Da", False, 6)]
    o, _, rules = _pick(_nia(stamina=8), opts)
    assert (o["attr"], o["sp"]) == ("Da", False) and "nia.lesson_stamina" in rules


def test_nia_sales_when_no_lesson():
    opts = [_opt("sales"), _opt("gift"), _opt("rest")]
    o, _, rules = _pick(_nia(), opts)
    assert o["option"] == "sales"


def test_nia_master_prefers_outing_over_gift():
    opts = [_opt("gift"), _opt("outing"), _opt("shop")]
    o, _, rules = _pick(_nia(mode="produce-005"), opts)
    assert o["option"] == "outing" and "nia.outing_default" in rules


def test_nia_rest_limit():
    """休息次数用完不能再休。"""
    opts = [_opt("rest"), _opt("gift")]
    o, _, rules = _pick(_nia(stamina=5, rest_left=0), opts)
    assert o["option"] == "gift" and "nia.rest_limit" in rules


def test_nia_low_stamina_rests_when_possible():
    opts = [_opt("training", "Vo", True, 8), _opt("training", "Da", False, 6), _opt("rest")]
    o, _, _ = _pick(_nia(stamina=5), opts)
    assert o["option"] == "rest"


def test_nia_special_guidance_with_points():
    """特別指導：P 点超过主数据的提醒线（ProduceSetting.stepCustomizeStartAlertProducePointThreshold）就进。"""
    opts = [_opt("special_guidance"), _opt("gift")]
    o, _, _ = _pick(_nia(produce_point=120), opts)
    assert o["option"] == "special_guidance"
    o, _, _ = _pick(_nia(produce_point=10), opts)
    assert o["option"] == "gift"


def test_teacher_suggestion_ignored():
    """不跟随老师建议（用户定）：建议的选项不加分。"""
    opts = [_opt("training", "Vo", False), _opt("training", "Da", True)]
    opts[0]["recommended"] = True
    o, _, _ = _pick(_st(), opts)
    assert o["attr"] == "Da"


def test_unknown_family_raises():
    with pytest.raises(ValueError):
        choose_action(_st(mode="produce-007"), [_opt("rest")])


def test_deciders_route_hajime_nia_to_strategy():
    """ProduceDeciders.action_select：初 / N.I.A 走策略表（来源 rule，理由带出处），不碰 H.I.F 的日程预演。"""
    from hiro.brain.deciders import ProduceDeciders
    from hiro.brain.state import CAMPUS_HIRO
    from hiro.contracts import GameState

    st = GameState(produce={"mode": "produce-004", "step": 3, "stamina": 20, "max_stamina": 30, "produce_point": 0,
                            "params": {"Vo": 300, "Da": 200, "Vi": 150}, "idol_card_id": "i_card-shro-3-007"},
                   page_fields={"options": [_opt("training", "Vo", True, 8), _opt("training", "Vi", True, 8), _opt("sales")]})  # fmt: skip
    d = ProduceDeciders(CAMPUS_HIRO, None).action_select(st)
    assert d.source == "rule" and d.action.args["option"] == "training" and d.action.args["attr"] == "Vi"
    assert "[g8-NIA]" in d.reason and d.decider == "action_select"


# ---------------------------------------------------------------- 外出 / 授業

from hiro.brain.hajime_nia import choose_outing, choose_study  # noqa: E402


def _ch(i, cost_p=0, cost_hp=0, trouble=False, text="", **kw):
    return {"index": i, "cost_p": cost_p, "cost_hp": cost_hp, "trouble": trouble, "text": text, **kw}


def test_nia_pro_outing_middle():
    i, _, rules = choose_outing(_nia(produce_point=100), [_ch(0, 60), _ch(1, 40), _ch(2, 20)])
    assert i == 1 and "nia.outing_middle" in rules


def test_nia_master_outing_bottom_first_and_affordable():
    st = _nia(mode="produce-005", produce_point=100)
    i, _, rules = choose_outing(st, [_ch(0, 60), _ch(1, 40), _ch(2, 20)])
    assert i == 2 and "nia.outing_order" in rules
    i, _, _ = choose_outing(_nia(mode="produce-005", produce_point=50), [_ch(0, 60), _ch(1, 40), _ch(2, 80)])
    assert i == 1  # 下买不起：中（削除）


def test_nia_master_middle_change_is_last():
    st = _nia(mode="produce-005", produce_point=70)
    i, _, _ = choose_outing(st, [_ch(0, 60), _ch(1, 40, text="スキルカードをチェンジ"), _ch(2, 80)])
    assert i == 0  # 下买不起、中是换卡：上（强化）


def test_hajime_outing_tired_spends_most_affordable():
    i, _, rules = choose_outing(_st(stamina=10, produce_point=120), [_ch(0, 0), _ch(1, 50), _ch(2, 150)])
    assert i == 1 and "hajime.outing_spend" in rules


def test_hajime_outing_not_tired_cheapest():
    i, _, _ = choose_outing(_st(stamina=25, produce_point=300), [_ch(0, 100), _ch(1, 50), _ch(2, 0)])
    assert i == 2


def test_hajime_study_main_attr_avoids_trouble():
    chs = [_ch(0, text="ボーカル", attr="Vo"), _ch(1, text="ビジュアル", attr="Vi"), _ch(2, trouble=True, text="トラブル追加")]
    i, _, rules = choose_study(_st(main_attr="Vi", mode="produce-002"), chs)
    assert i == 1 and "hajime.study_avoid_trouble" in rules


def test_hajime_study_trouble_when_no_stamina():
    chs = [_ch(0, cost_hp=5, attr="Vo"), _ch(1, cost_hp=5, attr="Vi"), _ch(2, trouble=True)]
    i, _, _ = choose_study(_st(stamina=4, mode="produce-002"), chs)
    assert i == 2


def test_deciders_outing_study_route_by_family():
    from hiro.brain.deciders import ProduceDeciders
    from hiro.brain.state import CAMPUS_HIRO
    from hiro.contracts import GameState

    prod = {"mode": "produce-004", "step": 5, "stamina": 20, "max_stamina": 30, "produce_point": 100, "params": {"Vo": 1, "Da": 1, "Vi": 1}}
    d = ProduceDeciders(CAMPUS_HIRO, None).outing(GameState(produce=prod, page_fields={"choices": [_ch(0, 60), _ch(1, 40), _ch(2, 20)]}))
    assert d.action.args["select"] == 1 and "[g8-NIA]" in d.reason
    prod = dict(prod, mode="produce-002", main_attr="Vo")
    chs = [_ch(0, attr="Vo"), _ch(1, attr="Vi"), _ch(2, trouble=True)]
    d = ProduceDeciders(CAMPUS_HIRO, None).study(GameState(produce=prod, page_fields={"choices": chs}))
    assert d.action.args["select"] == 0


# ---------------------------------------------------------------- N.I.A 营业 / 试镜选档

from hiro.brain.hajime_nia import choose_audition, choose_sales_event, choose_sales_place  # noqa: E402


def _pl(i, kind, hp_cost=0):
    return {"index": i, "kind": kind, "hp_cost": hp_cost}


def test_sales_place_yellow_or_purple_when_stamina_ok():
    i, _, rules = choose_sales_place(_nia(stamina=25), [_pl(0, "resort", 0), _pl(1, "local", 5), _pl(2, "commercial", 5)])
    assert i in (1, 2) and "nia.sales_yellow_purple" in rules


def test_sales_place_purple_when_points_enough_yellow_when_short():
    places = [_pl(0, "local", 5), _pl(1, "commercial", 5)]
    assert choose_sales_place(_nia(stamina=25, produce_point=200), places)[0] == 1
    assert choose_sales_place(_nia(stamina=25, produce_point=20), places)[0] == 0


def test_sales_place_resort_when_stamina_would_block_lesson():
    """营业后体力会不到 SP 课程要的 8 以上：去绿（リゾート）回体力。"""
    i, _, rules = choose_sales_place(_nia(stamina=12), [_pl(0, "resort", 0), _pl(1, "local", 5), _pl(2, "commercial", 5)])
    assert i == 0 and "nia.sales_green_low" in rules


def test_sales_place_corporate_when_low_stamina_and_no_resort():
    i, _, _ = choose_sales_place(_nia(stamina=10), [_pl(0, "corporate", 0), _pl(1, "local", 5), _pl(2, "commercial", 5)])
    assert i == 0


def test_sales_event_fills_weakest_attr():
    chs = [{"index": 0, "attr": "Vo"}, {"index": 1, "attr": "Vi"}, {"index": 2, "attr": "Da"}]
    i, _, rules = choose_sales_event(_nia(params={"Vo": 300, "Da": 250, "Vi": 120}), chs)
    assert i == 1 and "nia.sales_choice_fill" in rules


def test_audition_highest_unlocked_tier():
    tiers = [{"index": 0, "number": 1, "vote_need": 0, "locked": False}, {"index": 1, "number": 2, "vote_need": 4000, "locked": False},
             {"index": 2, "number": 3, "vote_need": 9000, "locked": True}]  # fmt: skip
    i, number, reason, _ = choose_audition(_nia(), 6000, tiers)
    assert (i, number) == (1, 2) and "4,000" in reason


def test_audition_lower_after_failure():
    """失败重来时降一档（N.I.A 失败可以降档，协调 11-17）。"""
    tiers = [{"index": 0, "number": 1, "vote_need": 0, "locked": False}, {"index": 1, "number": 2, "vote_need": 4000, "locked": False}]
    i, number, reason, _ = choose_audition(_nia(), 6000, tiers, failed=1)
    assert (i, number) == (0, 1) and "降" in reason


def test_deciders_nia_pages_registered():
    from hiro.brain.deciders import ProduceDeciders
    from hiro.brain.state import CAMPUS_HIRO
    from hiro.contracts import GameState

    prod = {"mode": "produce-004", "step": 9, "stamina": 25, "max_stamina": 30, "produce_point": 0, "params": {"Vo": 1, "Da": 1, "Vi": 1}, "votes": 5000}
    pd = ProduceDeciders(CAMPUS_HIRO, None)
    d = pd.decide("NIA_SALES_PLACE", GameState(produce=prod, page_fields={"places": [_pl(0, "resort"), _pl(1, "local", 5)]}))
    assert d.action.args["select"] == 1 and d.decider == "sales_place"
    d = pd.decide("NIA_AUDITION_SELECT", GameState(produce=prod, page_fields={"votes": 5000, "tiers": [
        {"index": 0, "number": 1, "vote_need": 0, "locked": False}, {"index": 1, "number": 2, "vote_need": 4000, "locked": False}]}))
    assert d.action.args == {"select": 1, "audition_number": 2} and d.decider == "audition_select"
    d = pd.decide("NIA_SALES_EVENT", GameState(produce=prod, page_fields={"choices": [{"index": 0, "attr": "Vo"}, {"index": 1, "attr": "Da"}]}))
    assert d.action.args["select"] in (0, 1) and d.decider == "sales_event"


# ---------------------------------------------------------------- 再挑戦（协调 11-17：只用免费 / 已有的票，每场 ≤ 3 次）


def _retry(prod_mode="produce-001", **pf):
    from hiro.brain.deciders import ProduceDeciders
    from hiro.brain.state import CAMPUS_HIRO
    from hiro.contracts import GameState

    return ProduceDeciders(CAMPUS_HIRO, None).decide("EXAM_RETRY", GameState(produce={"mode": prod_mode}, page_fields=pf))


@pytest.mark.parametrize("pf, confirm", [
    ({"stage": "result", "attempts": 0}, True),
    ({"stage": "result", "attempts": 3}, False),  # 每场最多 3 次
    ({"stage": "result", "attempts": 1, "retries_left": 0}, False),  # 游戏说没次数了
    ({"stage": "confirm", "attempts": 1, "cost": "free"}, True),
    ({"stage": "confirm", "attempts": 1, "cost": "ticket"}, True),
    ({"stage": "confirm", "attempts": 1, "cost": "jewel"}, False),  # 绝不花ジュエル
    ({"stage": "confirm", "attempts": 1}, False),  # 读不出花什么：不点
])  # fmt: skip
def test_exam_retry_rules(pf, confirm):
    d = _retry(**pf)
    assert d.action.args["kind"] == "exam_retry" and d.action.args["confirm"] is confirm and d.decider == "exam_retry"


def test_nia_retry_says_reselect():
    d = _retry("produce-004", stage="confirm", attempts=0, cost="free")
    assert d.action.args["confirm"] and d.action.args["reselect"] is True and "降" in d.reason
