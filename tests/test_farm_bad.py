"""刷回忆：「初」BAD 育成（HIRO_FARM=bad，hiro.brain.farm）：13 周固定日程、练习课刚好不通关、相談删掉这局拿到的卡。"""

from types import SimpleNamespace as NS

from hiro.brain import farm

import pytest

CRIT = {"Vo": 0.2, "Da": 0.5, "Vi": 0.3}  # 审查基准：Da 第 1、Vi 第 2


def _opt(option, attr=None, sp=None, oikomi=None):
    return {"option": option, "attr": attr, "sp": sp, "oikomi": oikomi}


def test_switch():
    assert farm.mode({}) is None and farm.mode({"HIRO_FARM": "bad"}) == "bad" and farm.mode({"HIRO_FARM": "x"}) is None
    assert farm.margin_ratio({}) == farm.DEFAULT_MARGIN and farm.margin_ratio({"HIRO_FARM_BAD_MARGIN": "0.2"}) == 0.2


def test_lesson_week_takes_sp_of_top_criteria():
    opts = [_opt("training", "Vo", True), _opt("training", "Da", False), _opt("training", "Da", True), _opt("rest")]
    i, why = farm.pick_action(1, opts, CRIT)
    assert opts[i]["attr"] == "Da" and opts[i]["sp"] and "故意不通关" in why


def test_lesson_index_zero_is_found():
    opts = [_opt("training", "Vo", False), _opt("rest")]
    assert farm.pick_action(3, opts, None)[0] == 0  # 审查基准没读到：唯一一节课在第 0 个


def test_oikomi_takes_second_criteria():
    opts = [_opt("training", a, oikomi=True) for a in ("Vo", "Da", "Vi")]
    i, _ = farm.pick_action(5, opts, CRIT)
    assert opts[i]["attr"] == "Vi"


def test_rest_weeks_and_week7():
    opts = [_opt("rest"), _opt("outing"), _opt("shop"), _opt("training", "Da", True)]
    for week in (2, 4, 8, 11):
        assert opts[farm.pick_action(week, opts, CRIT)[0]]["option"] == "rest"
    assert opts[farm.pick_action(7, opts, CRIT, has_junk=True)[0]]["option"] == "shop"
    assert opts[farm.pick_action(7, opts, CRIT, has_junk=False)[0]]["option"] == "outing"
    assert opts[farm.pick_action(7, opts, CRIT, has_junk=True, shop_ok=False)[0]]["option"] == "outing"


def test_unknown_week_or_missing_option_falls_back():
    assert farm.pick_action(None, [_opt("rest")], CRIT) is None
    assert farm.pick_action(6, [_opt("rest")], CRIT) is None  # 考试周不在日程里
    assert farm.pick_action(2, [_opt("training", "Da", True)], CRIT) is None  # 休息周没有休息可选


def test_junk_cards(monkeypatch):
    import hiro.brain.deciders as d

    monkeypatch.setattr(d, "_is_basic", lambda cid: cid.endswith("basic"))
    monkeypatch.setattr(d, "_is_trouble_card", lambda cid: cid == "sleepy")
    cards = [{"index": 0, "card_id": "a-basic"}, {"index": 1, "card_id": "p_card-01-ido-3_1"}, {"index": 2, "card_id": "target"},
             {"index": 3, "card_id": "picked"}, {"index": 4, "card_id": "sleepy"}, {"index": 5, "card_id": None},
             {"index": 6, "card_id": "custom", "customized": True}]  # fmt: skip
    assert [c["card_id"] for c in farm.junk_cards(cards, {"target"})] == ["sleepy", "picked"]


def test_target_cards_env():
    assert farm.target_cards({"HIRO_FARM_TARGET": "p_card-01-men-3_036, p_card-x"}) == {
        "p_card-01-men-3_036",
        "p_card-x",
    }


def test_bad_lesson_advisor_skips_near_clear():
    from hiro.contracts import Action, ActionKind

    inner = NS(decide=lambda *a: "inner")
    live = {}
    adv = farm.BadLessonAdvisor(inner, live, lambda: 100, 0.3)
    legal = [Action.play_card(0), Action.skip()]
    assert adv.decide(None, None, None, legal) == "inner"  # 还没读到离通关多少
    live["left"] = 45
    assert adv.decide(None, None, None, legal) == "inner"  # 还差 45 > 30：照常出牌
    live["left"] = 25
    d = adv.decide(None, None, None, legal)
    assert d.action.kind is ActionKind.SKIP and "刚好没过" in d.reason
    assert adv.decide(None, None, None, [Action.play_card(0)]) == "inner"  # 不能跳过时照常


@pytest.mark.master
def test_action_select_uses_schedule(monkeypatch):
    """接进初的选行动：HIRO_FARM=bad 时第 2 周休息（原来的规则会去上课）。"""
    from hiro.brain.deciders import ProduceDeciders
    from hiro.brain.state import profile_for
    from hiro.contracts import GameState

    monkeypatch.setenv("HIRO_FARM", "bad")
    prod = {"idol_card_id": "i_card-fktn-3-000", "mode": "produce-001", "step": 2, "stamina": 30, "max_stamina": 30, "produce_point": 0,
            "params": {"Vo": 100, "Da": 100, "Vi": 100}, "growth_permil": {}, "deck": []}  # fmt: skip
    opts = [_opt("training", "Da", True), _opt("rest")]
    d = ProduceDeciders(profile_for("i_card-fktn-3-000"), None).decide(
        "ACTION_SELECT", GameState(produce=prod, page_fields={"options": opts})
    )
    assert d.action.args.get("option") == "rest" and "刷回忆" in d.reason


def test_target_accepts_card_names(monkeypatch):
    """11-27 实机：界面里填的是卡名；id 原样，名字按资料库找（完全一致优先），找不到的丢掉。"""
    from hiro.brain import farm
    from hiro.cli import catalog

    def search(q, kind=None, lang="ja"):
        return [{"id": "p_card-02-act-3_050", "name": "輝くキミへ"}] if q == "輝くキミへ" and lang == "ja" else []

    monkeypatch.setattr(catalog, "search", search)
    got = farm.target_cards({"HIRO_FARM_TARGET": "輝くキミへ+，p_card-02-act-3_186,没有这张"})
    assert got == {"p_card-02-act-3_050", "p_card-02-act-3_186"}


def test_impression_passive_gain_counts_in_margin():
    """11-27 实机：好印象流停手后每回合还自动加分，差 5 停手照样过线。余量算上之后好印象自动加的分。"""
    from types import SimpleNamespace as NS

    from hiro.brain import farm
    from hiro.contracts import Action, ActionKind

    assert farm.impression_gain(5, 3) == 5 + 4 + 3
    assert farm.impression_gain(2, 5) == 2 + 1
    assert farm.impression_gain(None, 3) == 0

    class Inner:
        def decide(self, *a):
            return "inner"

    legal = [Action.skip(), Action(ActionKind.PLAY_CARD, {"slot": 0})]
    adv = farm.BadLessonAdvisor(Inner(), {"left": 30}, 50, 0.4)  # 只按比例：余量 20，差 30 照常出牌
    assert adv.decide(NS(impression=None, remaining_turns=3), None, None, legal) == "inner"
    d = adv.decide(NS(impression=5, remaining_turns=3), None, None, legal)  # 20 + 12×1.2 = 34.4 ≥ 30：停手
    assert d.action.kind is ActionKind.SKIP and "好印象" in d.reason


def test_week7_goes_shop_when_deck_unread_but_cards_picked(monkeypatch):
    """11-27 DMM：牌组按钮认不出、牌组为空 → 以为没卡可删去了外出。牌组读不到时按这局拿过的卡判断。"""
    from hiro.brain import farm

    monkeypatch.setenv("HIRO_FARM_TARGET", "p_card-02-act-3_050")
    picked = {"p_card-02-act-1_010", "p_card-02-act-3_050"}
    junk = farm.junk_cards([{"card_id": c} for c in picked], farm.target_cards())
    assert [c["card_id"] for c in junk] == ["p_card-02-act-1_010"]  # 目标卡不算要删的


def test_remove_card_page_never_deletes_target(monkeypatch):
    """CodeRabbit #198：删卡页（相談没带 card_id / 删卡事件）刷回忆时也只删这局拿到的卡，转写目标不删。"""
    from hiro.brain.deciders import ProduceDeciders
    from hiro.brain.state import profile_for
    from hiro.contracts import GameState

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setenv("HIRO_FARM_TARGET", "p_card-02-act-3_186")
    prod = {"idol_card_id": "i_card-hski-3-000", "mode": "produce-001", "step": 7, "deck": []}
    cards = [
        {"index": 0, "card_id": "p_card-02-act-3_186", "upgrade": 0},  # 目标
        {"index": 1, "card_id": "p_card-02-act-1_010", "upgrade": 0},  # 这局拿的
    ]
    d = ProduceDeciders(profile_for("i_card-hski-3-000"), None).decide(
        "SKILL_CARD_REMOVAL", GameState(produce=prod, page_fields={"cards": cards})
    )
    assert d.action.args.get("index") == 1 and d.action.args.get("card_id") == "p_card-02-act-1_010", d
    cards = cards[:1]  # 只剩目标卡：取消，不删
    d = ProduceDeciders(profile_for("i_card-hski-3-000"), None).decide(
        "SKILL_CARD_REMOVAL", GameState(produce=prod, page_fields={"cards": cards})
    )
    assert d.action.args.get("cancel"), d


def test_consult_delete_carries_card_id(monkeypatch):
    """CodeRabbit #198：刷回忆相談删卡带上 card_id（删卡页按它选，不让 remove_card 重选），也不选转写目标。"""
    from hiro.brain.deciders import ProduceDeciders
    from hiro.brain.state import profile_for
    from hiro.contracts import GameState

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setenv("HIRO_FARM_TARGET", "p_card-02-act-3_186")
    deck = ["p_card-02-act-3_186", "p_card-02-act-1_010"]
    prod = {"idol_card_id": "i_card-hski-3-000", "mode": "produce-001", "step": 7, "stamina": 20, "max_stamina": 30,
            "produce_point": 300, "params": {"Vo": 1, "Da": 1, "Vi": 1}, "growth_permil": {}, "rerolls_left": 0,
            "excludes_left": 0, "deck": [{"card_id": c, "upgrade": 0} for c in deck]}  # fmt: skip
    pf = {"shelf": [], "services": {"delete": {"price": 100, "available": True}}}
    d = ProduceDeciders(profile_for("i_card-hski-3-000"), None).decide(
        "CONSULT", GameState(produce=prod, page_fields=pf)
    )
    assert d.action.args.get("service") == "delete" and d.action.args.get("card_id") == "p_card-02-act-1_010", d


def _boxes(*items):
    from types import SimpleNamespace as NS

    return [NS(text=t, rect=NS(center=NS(x=x, y=y))) for t, x, y in items]


RESULT = ("獲得可能スキルカード", 163, 685), ("中間試験/1次オーディション後に獲得", 485, 690), ("リズミカル", 270, 730), \
    ("あと1回可能", 85, 1115), ("再生成", 130, 1160), ("次へ", 360, 1160)  # fmt: skip


def test_regen_once_when_not_target(monkeypatch):
    """11-27 实机：回忆带「リズミカル」不是目标「輝くキミへ」，旁边写着再生成还能 1 次，程序直接点了次へ。现在再生成一次。"""
    from hiro.brain import farm

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setattr(farm, "_target_names", lambda: {"輝くキミへ"})
    monkeypatch.setattr(farm, "_regen", {"done": 0, "pending": False, "reported": set()})
    assert farm.memory_result(_boxes(*RESULT))["name"] == "リズミカル"
    assert farm.regen_step(_boxes(*RESULT)) == (130, 1160)  # 点再生成
    dlg = _boxes(
        ("メモリー再生成", 360, 500),
        ("メモリー再生成チケットを1枚使用します", 360, 640),
        ("キャンセル", 218, 1000),
        ("再生成する", 500, 1000),
    )
    assert farm.regen_step(dlg) == (500, 1000)  # 确认（用券，没有钻石）
    assert farm.regen_step(_boxes(*RESULT)) is None  # 只再生成一次：照常点次へ


def test_regen_never_spends_jewels(monkeypatch):
    from hiro.brain import farm

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setattr(farm, "_target_names", lambda: {"輝くキミへ"})
    monkeypatch.setattr(farm, "_regen", {"done": 0, "pending": False, "reported": set()})
    farm.regen_step(_boxes(*RESULT))
    dlg = _boxes(
        ("ジュエルを50個使用して再生成しますか", 360, 640), ("キャンセル", 218, 1000), ("再生成する", 500, 1000)
    )
    assert farm.regen_step(dlg) == (218, 1000)  # 有钻石：取消


def test_regen_skipped_when_hit_or_off(monkeypatch):
    from hiro.brain import farm

    monkeypatch.setattr(farm, "_regen", {"done": 0, "pending": False, "reported": set()})
    monkeypatch.setattr(farm, "_target_names", lambda: {"リズミカル"})
    monkeypatch.setenv("HIRO_FARM", "bad")
    assert farm.regen_step(_boxes(*RESULT)) is None  # 刷到了
    monkeypatch.setenv("HIRO_FARM", "")
    assert farm.regen_step(_boxes(*RESULT)) is None  # 没开刷回忆


def test_regen_ignores_unrelated_dialog(monkeypatch):
    """点了再生成没弹确认框（直接重抽）：之后别的弹窗哪怕有「決定」也不替它点。"""
    from hiro.brain import farm

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setattr(farm, "_target_names", lambda: {"輝くキミへ"})
    monkeypatch.setattr(farm, "_regen", {"done": 0, "pending": False, "reported": set()})
    now = [0.0]
    monkeypatch.setattr(farm, "_clock", lambda: now[0])
    assert farm.regen_step(_boxes(*RESULT)) == (130, 1160)
    other = _boxes(("フォトを保存しますか", 360, 640), ("キャンセル", 218, 1000), ("決定", 500, 1000))
    assert farm.regen_step(other) == (218, 1000)  # 不替它点「決定」：点キャンセル
    assert farm.regen_step(_boxes(*RESULT)) == farm.WAIT  # 刚点了再生成：框可能还会弹，先等
    now[0] = 5
    assert farm.regen_step(_boxes(*RESULT)) is None  # 回到结果页：不再等确认框，也不再生成第二次
    assert farm._regen["pending"] is False


def test_regen_dialog_needs_ticket_or_free(monkeypatch):
    """白名单：确认框里没读到「チケット」「無料」（钻石只显示成图标 + 数字）就キャンセル；
    框是半透明的、底下结果页的字还读得到时也由这里管，不交回通用分支去点「決定」。"""
    from hiro.brain import farm

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setattr(farm, "_target_names", lambda: {"輝くキミへ"})
    monkeypatch.setattr(farm, "_regen", {"done": 0, "pending": False, "reported": set()})
    farm.regen_step(_boxes(*RESULT))
    dlg = _boxes(
        *RESULT,
        ("メモリーを再生成しますか", 360, 600),
        ("50", 400, 650),
        ("キャンセル", 218, 1000),
        ("決定", 500, 1000),
    )
    assert farm.regen_step(dlg) == (218, 1000)


def _regen_started(monkeypatch, now):
    from hiro.brain import farm

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setattr(farm, "_target_names", lambda: {"輝くキミへ"})
    monkeypatch.setattr(farm, "_regen", {"done": 0, "pending": False, "reported": set()})
    monkeypatch.setattr(farm, "_clock", lambda: now[0])
    assert farm.regen_step(_boxes(*RESULT)) == (130, 1160)
    return farm


def test_regen_dialog_without_cancel_waits_then_stops(monkeypatch):
    """CodeRabbit #198：等确认框时认不出キャンセル（只读到费用和「決定」）：不交回通用分支（会点決定），等着；20 秒还这样就停下。"""
    from hiro.loop.errors import ResumeBlocked

    now = [0.0]
    farm = _regen_started(monkeypatch, now)
    dlg = _boxes(*RESULT, ("50", 400, 650), ("決定", 500, 1000))
    assert farm.regen_step(dlg) == farm.WAIT
    now[0] = 25
    with pytest.raises(ResumeBlocked, match="再生成"):
        farm.regen_step(dlg)


def test_regen_confirm_must_be_on_cancel_row(monkeypatch):
    """CodeRabbit #198：框里认不出确认按钮时，不能把底下结果页的「再生成」（y 1160）当确认按钮。"""
    farm = _regen_started(monkeypatch, [0.0])
    dlg = _boxes(*RESULT, ("再生成チケットを1枚使用します", 360, 640), ("キャンセル", 218, 1000))
    assert farm.regen_step(dlg) == (218, 1000)


def test_regen_keeps_watching_after_cancel(monkeypatch):
    """CodeRabbit #198：点了キャンセル框还开着：照样按白名单处理（不放给通用分支）；框关了回到干净的结果页才结束。"""
    farm = _regen_started(monkeypatch, [0.0])
    dlg = _boxes(
        ("メモリーを再生成しますか", 360, 600), ("50", 400, 650), ("キャンセル", 218, 1000), ("決定", 500, 1000)
    )
    assert farm.regen_step(dlg) == (218, 1000)
    assert farm.regen_step(dlg) == (218, 1000)  # 还开着：再点キャンセル，绝不点決定
    now = farm._clock()
    monkeypatch.setattr(farm, "_clock", lambda: now + 5)
    assert farm.regen_step(_boxes(*RESULT)) is None and not farm._regen["pending"]


def test_bad_wrapper_goes_outside_strategy_plugin(monkeypatch):
    """CodeRabbit #198：strategy.json 换了出牌插件时，BAD 停手包在最后选定的出招外面（原来被放进 GuardedAdvisor 的退路里，插件出牌时不停手）。"""
    from hiro.exec import exam as ex

    plugin_adv, given = object(), object()
    monkeypatch.setattr(ex, "_plugin", lambda kind: None)  # 没有局面来源：包完之后报错停下，正好看包的是谁
    monkeypatch.setattr(ex, "pick_advisor", lambda exam, mode, given=None: plugin_adv)
    seen = []

    def wrap(a):
        seen.append(a)
        return a

    with pytest.raises(RuntimeError):
        ex.run_exam(None, "hajime-lesson-da", None, lambda shot: True, advisor=given, wrap=wrap)
    assert len(seen) == 1 and isinstance(seen[0], ex.GuardedAdvisor)


def test_regen_late_dialog_is_still_handled(monkeypatch):
    """自检：点了再生成后第一帧还是干净的结果页（框还没弹）：先等，框晚弹出来照样按白名单处理，不交给通用分支。"""
    now = [0.0]
    farm = _regen_started(monkeypatch, now)
    now[0] = 1.0
    assert farm.regen_step(_boxes(*RESULT)) == farm.WAIT
    dlg = _boxes(
        *RESULT,
        ("メモリーを再生成しますか", 360, 600),
        ("50", 400, 650),
        ("キャンセル", 218, 1000),
        ("決定", 500, 1000),
    )
    now[0] = 2.0
    assert farm.regen_step(dlg) == (218, 1000)


def test_regen_after_confirm_hands_back_when_no_dialog(monkeypatch):
    """自检：确认以后重抽的演出画面（不是结果页、也没有框）：不等到超时，交回收尾照常走。"""
    now = [0.0]
    farm = _regen_started(monkeypatch, now)
    dlg = _boxes(
        ("メモリー再生成チケットを1枚使用します", 360, 640), ("キャンセル", 218, 1000), ("再生成する", 500, 1000)
    )
    assert farm.regen_step(dlg) == (500, 1000)
    assert farm.regen_step(_boxes(("TAP", 360, 1200))) is None and not farm._regen["pending"]


def test_free_regen_whitelist():
    from hiro.brain import farm

    assert farm._free_regen(["メモリー再生成チケットを1枚使用します"])
    assert farm._free_regen(["本日1回無料"])
    assert not farm._free_regen(["メモリーを再生成しますか", "所持チケット 0"])
    assert not farm._free_regen(["チケットが不足しています"])
    assert not farm._free_regen(["メモリーを再生成しますか", "50"])


def test_free_regen_ticket_count_ten_is_not_zero():
    """审查 #198 第 6 条：券数 10 / 20 / 30 张不能判成 0 张（原来 .*? 吃掉前面的 1，整数倍券时白名单无声失效）。"""
    from hiro.brain import farm

    for n in ("10", "20", "30"):
        assert farm._free_regen(["メモリー再生成チケットを1枚使用します", f"所持チケット{n}"]), n
        assert farm._free_regen(["メモリー再生成チケットを1枚使用します", f"所持チケット{n}枚"]), n
    assert not farm._free_regen(["メモリー再生成チケットを1枚使用します", "所持チケット0"])
    assert not farm._free_regen(["メモリー再生成チケットを1枚使用します", "所持チケット：0枚"])


def _late_dialog(*extra):
    return _boxes(*RESULT, *extra)


def test_regen_dialog_after_grace_never_goes_to_generic_branch(monkeypatch):
    """审查 #198 第 1 条：点了再生成 5.5 秒才弹出带ジュエル的框（pending 已经结束）：原来返回 None，交给通用分支点「決定」花钻石。
    现在 farm 开着时照样由这里接管：有钻石取消。"""
    now = [0.0]
    farm = _regen_started(monkeypatch, now)
    now[0] = 4.5
    assert farm.regen_step(_boxes(*RESULT)) is None and not farm._regen["pending"]  # 4 秒没框：交回收尾
    now[0] = 5.5
    dlg = _late_dialog(
        ("ジュエルを50個使用して再生成しますか", 360, 640), ("キャンセル", 218, 1000), ("決定", 500, 1000)
    )
    assert farm.regen_step(dlg) == (218, 1000)
    assert farm.regen_step(dlg) == (218, 1000)  # 还开着：再点キャンセル，绝不点決定


def test_regen_late_free_dialog_is_confirmed_once(monkeypatch):
    """审查 #198 第 1 条：晚弹的框是用券的（白名单）：照样确认；确认后淡出那几帧等着，不交回通用分支。"""
    now = [0.0]
    farm = _regen_started(monkeypatch, now)
    now[0] = 4.5
    assert farm.regen_step(_boxes(*RESULT)) is None
    now[0] = 5.5
    dlg = _boxes(
        ("メモリー再生成チケットを1枚使用します", 360, 640), ("キャンセル", 218, 1000), ("再生成する", 500, 1000)
    )
    assert farm.regen_step(dlg) == (500, 1000)
    assert farm.regen_step(dlg) == farm.WAIT  # 淡出中：不再点
    assert farm.regen_step(_boxes(("TAP", 360, 1200))) is None and not farm._regen["pending"]
    assert farm.regen_step(dlg) == (218, 1000)  # 已经确认过一次：再弹一次的框取消（REGEN_MAX）


def test_regen_dialog_after_restart_is_handled(monkeypatch):
    """审查 #198 第 1 条：进程在框开着时重启（_regen 清空、pending=False），框后面结果页读不全：照样按白名单处理，
    有钻石取消；之后不会再点第二次再生成。"""
    from hiro.brain import farm

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setattr(farm, "_target_names", lambda: {"輝くキミへ"})
    monkeypatch.setattr(farm, "_regen", {"done": 0, "pending": False, "reported": set()})
    monkeypatch.setattr(farm, "_clock", lambda: 0.0)
    dlg = _boxes(
        ("メモリーを再生成しますか", 360, 600),
        ("ジユエル 50", 400, 650),
        ("キャンセル", 218, 1000),
        ("決定", 500, 1000),
    )
    assert farm.regen_step(dlg) == (218, 1000)
    monkeypatch.setattr(farm, "_clock", lambda: 10.0)
    assert farm.regen_step(_boxes(*RESULT)) is None  # 框关了：回到结果页，不再生成第二次
    assert farm._regen["done"] == 1


def test_unrelated_cancel_dialog_without_pending_is_left_alone(monkeypatch):
    """没在等再生成、画面上的框和再生成 / 钻石无关（照片保存确认）：不归这里管，交回收尾（结果页的「再生成」按钮不算）。"""
    from hiro.brain import farm

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setattr(farm, "_target_names", lambda: {"リズミカル"})
    monkeypatch.setattr(farm, "_regen", {"done": 0, "pending": False, "reported": set()})
    other = _boxes(*RESULT, ("フォトを保存しますか", 360, 640), ("キャンセル", 218, 1000), ("決定", 500, 1000))
    assert farm.regen_step(other) is None
    monkeypatch.setenv("HIRO_FARM", "")
    jewel = _boxes(("ジュエルを50個使用して再生成しますか", 360, 640), ("キャンセル", 218, 1000), ("決定", 500, 1000))
    assert farm.regen_step(jewel) is None  # 刷回忆没开：完全不管


def test_regen_whitelist_only_reads_dialog_area(monkeypatch):
    """审查 #198 第 7 条：白名单只看确认框区域（キャンセル那一行往上）。框外（屏幕顶上）的「無料」不能把付费框当成免费。"""
    farm = _regen_started(monkeypatch, [0.0])
    dlg = _boxes(("本日1回無料", 360, 120), ("メモリーを再生成しますか", 360, 600), ("50", 400, 650),
                 ("キャンセル", 218, 1000), ("決定", 500, 1000))  # fmt: skip
    assert farm.regen_step(dlg) == (218, 1000)


def test_regen_jewel_variants_anywhere_cancel(monkeypatch):
    """审查 #198 第 7 条：ジュエル看整屏、认 OCR 变体；框里写「50個」（钻石只显示成图标）也不算免费。"""
    from hiro.brain import farm as f

    for jewel in ("シュエル 50", "ジュェル×50"):
        farm = _regen_started(monkeypatch, [0.0])
        dlg = _boxes((jewel, 360, 60), ("メモリー再生成チケットを1枚使用します", 360, 640), ("キャンセル", 218, 1000),
                     ("再生成する", 500, 1000))  # fmt: skip
        assert farm.regen_step(dlg) == (218, 1000), jewel
    assert not f._free_regen(["チケットを使用して再生成", "50個消費します"])
    assert f._free_regen(["メモリー再生成チケットを1枚使用します", "所持数 3個"])  # 持有数不算付费


def test_target_match_is_conservative():
    """审查 #198 第 5 条：卡名比较有容错，读得不确定时不再生成（宁可留下非目标）。"""
    from hiro.brain import farm

    t = {"輝くキミへ"}
    assert farm.target_match("輝くキミへ", t) == "hit"
    assert farm.target_match("輝くキミヘ", t) == "hit"  # 平假名「へ」读成片假名「ヘ」
    assert farm.target_match("輝くキミへ+", t) == "hit"
    assert farm.target_match("輝くキミ", t) == "hit"  # 只读出前几个字
    assert farm.target_match("耀くキミへ", t) == "unsure"  # 错一个字：像目标，不再生成
    assert farm.target_match("輝", t) == "unsure"  # 太短：读不准
    assert farm.target_match("リズミカル", t) == "miss"
    assert farm.target_match("リズミカル", set()) == "unsure"


def test_regen_skipped_when_name_looks_like_target(monkeypatch):
    """审查 #198 第 5 条：结果页卡名 OCR 错了一个字（其实是目标）：不点再生成，照常点次へ。"""
    from hiro.brain import farm

    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setattr(farm, "_target_names", lambda: {"輝くキミへ"})
    monkeypatch.setattr(farm, "_regen", {"done": 0, "pending": False, "reported": set()})
    page = [b if b[0] != "リズミカル" else ("耀くキミへ", 270, 730) for b in RESULT]
    assert farm.regen_step(_boxes(*page)) is None
    page = [b if b[0] != "リズミカル" else ("輝くキミヘ", 270, 730) for b in RESULT]
    assert farm.regen_step(_boxes(*page)) is None


def _fake_catalog(monkeypatch):
    from hiro.brain import farm
    from hiro.cli import catalog

    calls = []

    def search(q, kind=None, lang="ja"):
        calls.append(q)
        return [{"id": "p_card-02-act-3_050", "name": "輝くキミへ"}] if q == "輝くキミへ" and lang == "ja" else []

    monkeypatch.setattr(catalog, "search", search)
    monkeypatch.setattr(farm, "_TARGET_CACHE", {})
    return farm, calls


def test_check_targets_blocks_on_unresolved(monkeypatch):
    """审查 #198 第 2 条：填了的转写目标有一项解析不出（片假名写错 / 资料库没下载）：开局前 ResumeBlocked，不静默丢掉。"""
    from hiro.loop.errors import ResumeBlocked

    farm, _ = _fake_catalog(monkeypatch)
    with pytest.raises(ResumeBlocked, match=r"輝くキミヘ.*卡名"):
        farm.check_targets({"HIRO_FARM_TARGET": "輝くキミヘ"})
    with pytest.raises(ResumeBlocked, match="没有这张"):
        farm.check_targets({"HIRO_FARM_TARGET": "輝くキミへ,没有这张"})  # 多个目标只有一个解析不出也停
    assert farm.check_targets({"HIRO_FARM_TARGET": "輝くキミへ，p_card-02-act-3_186"}) == {
        "p_card-02-act-3_050",
        "p_card-02-act-3_186",
    }


def test_check_targets_blocks_when_no_target(monkeypatch):
    from hiro import formation_env
    from hiro.loop.errors import ResumeBlocked

    farm, _ = _fake_catalog(monkeypatch)
    monkeypatch.setattr(formation_env, "MEMORY_CARDS", [])
    with pytest.raises(ResumeBlocked, match="没有转写目标"):
        farm.check_targets({})


def test_target_resolution_is_cached(monkeypatch):
    """审查 #198 第 2 条：每次决策都调 target_cards，解析结果按原文缓存，不再每次查资料库。"""
    farm, calls = _fake_catalog(monkeypatch)
    env = {"HIRO_FARM_TARGET": "輝くキミへ"}
    assert farm.target_cards(env) == farm.target_cards(env) == {"p_card-02-act-3_050"}
    assert calls == ["輝くキミへ"]


def test_hajime_run_stops_before_device_on_bad_target(monkeypatch, capsys):
    """审查 #198 第 2 条：初开局（new / resume 都一样）在连设备之前核对转写目标，解析不出退出码 3。"""
    from types import SimpleNamespace as NS

    from hiro import formation_env
    from hiro.brain import guides
    from hiro.runtime import hajime

    _fake_catalog(monkeypatch)
    monkeypatch.setenv("HIRO_FARM", "bad")
    monkeypatch.setenv("HIRO_FARM_TARGET", "輝くキミヘ")
    monkeypatch.setattr(guides, "refresh_if_stale", lambda: None)
    monkeypatch.setattr(formation_env, "apply_formation_plan", lambda idol: None)
    opened = []
    monkeypatch.setattr("hiro.devices.open_device", lambda: opened.append(1))
    assert hajime.run(NS(idol="i_card-hski-3-000", command="resume")) == 3
    assert not opened and "輝くキミヘ" in capsys.readouterr().out


def _consult(monkeypatch, farm_on: bool, deck: list):
    from hiro.brain.deciders import ProduceDeciders
    from hiro.brain.state import profile_for
    from hiro.contracts import GameState

    monkeypatch.setenv("HIRO_FARM", "bad" if farm_on else "")
    monkeypatch.setenv("HIRO_FARM_TARGET", "p_card-02-act-3_186")
    prod = {"idol_card_id": "i_card-hski-3-000", "mode": "produce-001", "step": 7, "stamina": 20, "max_stamina": 30,
            "produce_point": 300, "params": {"Vo": 1, "Da": 1, "Vi": 1}, "growth_permil": {}, "rerolls_left": 0,
            "excludes_left": 0, "deck": deck}  # fmt: skip
    pf = {"shelf": [], "services": {"delete": {"price": 100, "available": True}}}
    dec = ProduceDeciders(profile_for("i_card-hski-3-000"), None)
    return dec, dec.decide("CONSULT", GameState(produce=prod, page_fields=pf))


def test_consult_deck_unread_still_opens_delete_dialog(monkeypatch):
    """审查 #198 第 3 条 / CodeRabbit deciders.py:2403：牌组没读到时，选行动按这局拿过的卡判断去了相談，
    进去却直接结束不删卡（白花一周、垃圾卡进抽选池）。刷回忆时改为打开删卡对话框，在对话框里由 remove_card 选。"""
    from hiro.contracts import ActionKind

    dec, d = _consult(monkeypatch, True, [])
    assert d.action.kind is ActionKind.SHOP_BUY and d.action.args == {"service": "delete"}, d
    assert "delete" in dec.consult_used  # 一次相談只删一张：对话框里取消了也不再开


def test_consult_deck_unread_normal_mode_unchanged(monkeypatch):
    from hiro.contracts import ActionKind

    _, d = _consult(monkeypatch, False, [])
    assert d.action.kind is ActionKind.SHOP_END and "牌组没识别" in d.reason, d


def test_bad_lesson_advisor_reads_left_at_decision_time():
    """审查 #198 第 4 条 / CodeRabbit hajime.py:276：live 是循环开头那张截图读的（出牌后还在分数动画里、偏大），
    决策时现读一次；现读读不到 / 出错再退回 live 的值。"""
    from hiro.contracts import Action, ActionKind

    inner = NS(decide=lambda *a: "inner")
    legal = [Action.play_card(0), Action.skip()]
    live = {"left": 60}  # 动画帧：还差 60，按它会继续出牌
    fresh = [20]
    adv = farm.BadLessonAdvisor(inner, live, lambda: 100, 0.3, read_left=lambda: fresh[0])
    d = adv.decide(None, None, None, legal)
    assert d.action.kind is ActionKind.SKIP and "20" in d.reason and live["left"] == 20
    fresh[0] = None  # 现读读不到：退回 live
    live["left"] = 45
    assert adv.decide(None, None, None, legal) == "inner"
    live["left"] = 25
    assert adv.decide(None, None, None, legal).action.kind is ActionKind.SKIP

    def boom():
        raise RuntimeError("ocr")

    adv = farm.BadLessonAdvisor(inner, {"left": 25}, lambda: 100, 0.3, read_left=boom)
    assert adv.decide(None, None, None, legal).action.kind is ActionKind.SKIP
    calls = []
    adv = farm.BadLessonAdvisor(inner, {}, lambda: 100, 0.3, read_left=lambda: calls.append(1))
    assert adv.decide(None, None, None, [Action.play_card(0)]) == "inner" and not calls  # 不能跳过时不多截图


def test_lesson_clear_left_only_on_clear_goal():
    from hiro.runtime.hajime import lesson_clear_left

    hv = NS(lesson_goal=lambda shot: shot["goal"], read_lesson_hud=lambda shot: {"left": shot.get("left")})
    assert lesson_clear_left({"goal": "clear", "left": 12}, hv) == 12
    assert lesson_clear_left({"goal": "perfect", "left": 12}, hv) is None
    assert lesson_clear_left({"goal": "clear"}, hv) is None
    assert lesson_clear_left({"goal": None, "left": 3}, hv) is None
