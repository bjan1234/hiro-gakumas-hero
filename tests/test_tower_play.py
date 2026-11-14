"""偶像之路跑一段（hiro.runtime.tower_play）的页面处理器：第一次实机的范围（协调 11-14）——只打当前最前沿一层、编成不动、
打完一层停；结果页按 TowerRun 重试；再挑戦确认有消耗字样就停。"""

import json
from types import SimpleNamespace as NS

import pytest

from hiro.contracts import Action, ActionKind, Decision
from hiro.loop.errors import ResumeBlocked
from hiro.runtime import tower_play as tp
from hiro.runtime.loop import DONE
from hiro.runtime.tower import TowerRun


def _rt():
    taps = []
    return NS(device=NS(tap=lambda x, y: taps.append((x, y))), sleep=lambda s: None), taps


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HIRO_TOWER_CACHE", str(tmp_path / "cache"))


def _play(tmp_path, decision=None, layers=1):
    import dataclasses

    @dataclasses.dataclass
    class State:
        page_fields: dict

    core = NS(s=NS(state=State({})), deciders=NS(decide=lambda page, st: decision))
    return tp.TowerPlay(core, TowerRun("t"), idol_name="月村手毬", layers=layers, loadout_path=tmp_path / "lo.json")


def test_layers_then_formation_keeps_current(tmp_path, monkeypatch):
    keep = Decision(Action(ActionKind.SELECT_FORMATION, {"kind": "tower", "mechanic": None, "main": 0, "subs": []}), "只有当前编成", "sim", 0.8)
    p = _play(tmp_path, keep)
    seen_pf = []
    p.core.deciders.decide = lambda page, st: seen_pf.append(st.page_fields) or keep
    rt, taps = _rt()
    assert p.on_layers(rt, None, NS(fields={"idol": "月村手毬", "stage": 15, "challenge": [446, 987]})) is DONE and p.layer == 15
    monkeypatch.setattr(tp, "idol_code", lambda name: "ttmr")
    f = {"layer": 15, "turns": 15, "score_bonus_permils": [23090, 11980, 2600], "params": [2348, 1701, 611], "max_stamina": 46,
         "challenge": [381, 1091], "omakase": [643, 1090], "idol_name": "月村手毬", "idol_card_title": "一匹狼",
         "memory_ratings": [12075, 10773, 9978]}  # fmt: skip
    monkeypatch.setattr(tp, "idol_card_id", lambda title, code: "i_card-ttmr-2-000" if (title, code) == ("一匹狼", "ttmr") else None)
    f = {**f, "page": 1, "next_page": [458, 674], "prev_page": [264, 674]}
    assert p.on_formation(rt, None, NS(fields=f)) is DONE and taps[-1] == (458, 674)  # 先翻到第 2 页读牌组
    deck = {"cards": ["p_card-01-ido-2_017+1", "p_card-00-sup-3_027"], "unread": 1}
    page2 = {"layer": 15, "turns": 15, "page": 2, "challenge": [381, 1091], "prev_page": [264, 674], "deck": deck}
    assert p.on_formation(rt, None, NS(fields=page2)) is DONE
    assert taps == [(446, 987), (458, 674), (381, 1091)]  # おまかせ 没点
    lo = json.loads((tmp_path / "lo.json").read_text(encoding="utf-8"))
    assert lo == {"produce_id": "tower", "tower_id": "tower_001-ttmr", "layer": 15, "turns": 15, "score_bonus_permils": [23090, 11980, 2600],
                  "max_stamina": 46, "idol_card_id": "i_card-ttmr-2-000", "produce_cards": ["p_card-01-ido-2_017+1", "p_card-00-sup-3_027"],
                  "formation_signature": "i_card-ttmr-2-000.12075-10773-9978"}  # fmt: skip
    assert p.run.tower_id == "tower_001-ttmr"
    assert seen_pf[-1]["idol_card_id"] == "i_card-ttmr-2-000"  # 编成评估要偶像卡（3940a9 11-15）
    assert json.loads((tmp_path / "cache" / "tower_001-ttmr-15.json").read_text(encoding="utf-8")) == lo  # 同编成重试时读这份


def test_formation_lands_on_page2_goes_back_first(tmp_path):
    p = _play(tmp_path)
    rt, taps = _rt()
    page2 = {"page": 2, "challenge": [381, 1091], "prev_page": [264, 674], "deck": {"cards": [], "unread": 0}}
    assert p.on_formation(rt, None, NS(fields=page2)) is DONE and taps == [(264, 674)]


def test_formation_change_stops(tmp_path, monkeypatch):
    change = Decision(Action(ActionKind.SELECT_FORMATION, {"kind": "tower", "mechanic": None, "main": 3, "subs": [1]}), "换", "sim", 0.8)
    p = _play(tmp_path, change)
    monkeypatch.setattr(tp, "idol_code", lambda name: "ttmr")
    with pytest.raises(ResumeBlocked, match="不换编成"):
        p.on_formation(_rt()[0], None, NS(fields={"layer": 15, "challenge": [381, 1091], "page": 1}))


def test_result_retry_until_three_stars_then_stop_after_one_layer(tmp_path):
    p = _play(tmp_path)
    p.layer = 15
    h = p.handlers()
    rt, taps = _rt()
    res = {"cleared": True, "layer": 15, "stars": 1, "retry": [129, 1160], "back": [350, 1160]}
    assert h["TOWER_RESULT"](rt, None, NS(fields=res)) is DONE and taps == [(129, 1160)]  # 没满三星：再挑戦
    # 实机 r2：确认框正在弹出时同一张结果页又被认出来——不再算一次、不再点
    assert h["TOWER_RESULT"](rt, None, NS(fields=res)) is tp.STAY and p.run.tries[15] == 1 and taps == [(129, 1160)]
    h["TOWER_RETRY_CONFIRM"](rt, None, NS(fields={"cost": None, "same": [492, 1037], "ok": [509, 1160]}))  # 换页：开门
    assert h["TOWER_RESULT"](rt, None, NS(fields={**res, "stars": 3})) is tp.END and p.finished  # 三星：这一层打完，停在结果页
    assert p.run.tries[15] == 2 and taps[-1] == (509, 1160)


def test_result_never_cleared_stops(tmp_path):
    p = _play(tmp_path)
    h = p.handlers()
    rt, _ = _rt()
    res = {"cleared": False, "layer": 15, "stars": 0, "retry": [129, 1160]}
    confirm = NS(fields={"cost": None, "same": [492, 1037], "ok": [509, 1160]})
    h["TOWER_RESULT"](rt, None, NS(fields=res))
    h["TOWER_RETRY_CONFIRM"](rt, None, confirm)
    h["TOWER_RESULT"](rt, None, NS(fields=res))
    h["TOWER_RETRY_CONFIRM"](rt, None, confirm)
    with pytest.raises(ResumeBlocked, match="没过关"):
        h["TOWER_RESULT"](rt, None, NS(fields=res))


def test_tower_id_from_idol_name_without_formation(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "idol_code", lambda name: "ttmr")
    p = tp.TowerPlay(NS(), TowerRun(None), idol_name="月村手毬", layers=1, loadout_path=tmp_path / "lo.json")
    assert p.run.tower_id == "tower_001-ttmr"  # 从名次页 / 结果页续跑也有路线（实机 r2 汇总里是 None）


def test_result_page_not_recognized_while_retry_confirm_opening():
    from hiro.vision.tower import tower_page

    boxes = [("CLEAR", (300, 210, 420, 240)), ("再挑戦", (90, 1145, 160, 1175)), ("一覧に戻る", (300, 1145, 400, 1175)),
             ("ステージを再挑戦しますか?", (100, 960, 320, 990))]  # fmt: skip
    assert tower_page(None, boxes) is None  # 确认框正文已经出来、标题条还没认出：不当结果页


def test_retry_confirm_free_only(tmp_path):
    p = _play(tmp_path)
    rt, taps = _rt()
    with pytest.raises(ResumeBlocked, match="消耗"):
        p.on_retry_confirm(rt, None, NS(fields={"cost": "ジュエル", "same": [492, 1037], "ok": [509, 1160]}))
    assert p.on_retry_confirm(rt, None, NS(fields={"cost": None, "same": [492, 1037], "ok": [509, 1160]})) is DONE
    assert taps == [(492, 1037), (509, 1160)]


def test_idol_code_from_master():
    assert tp.idol_code("月村 手毬") == "ttmr" and tp.idol_code("不存在") is None


def test_layers_locked_or_three_stars_stop(tmp_path):
    p = _play(tmp_path)
    rt, taps = _rt()
    with pytest.raises(ResumeBlocked, match="锁着"):
        p.on_layers(rt, None, NS(fields={"idol": "月村手毬", "stage": 16, "stars": 0, "locked": True, "challenge": [482, 989]}))
    with pytest.raises(ResumeBlocked, match="三星"):
        p.on_layers(rt, None, NS(fields={"idol": "月村手毬", "stage": 10, "stars": 3, "locked": False, "challenge": [480, 988]}))
    assert taps == []


def test_ranking_records_and_taps_next(tmp_path):
    p = _play(tmp_path)
    p.layer = 15
    rt, taps = _rt()
    rows = [{"rank": 1, "name": "白草四音", "score": 105438}, {"rank": 3, "name": "月村手毬", "score": 54009}]
    assert p.on_ranking(rt, None, NS(fields={"my_rank": 3, "rows": rows, "next": [361, 1160]})) is DONE and taps == [(361, 1160)]
    assert p.run.summary()["rankings"] == {15: [{"my_rank": 3, "rows": rows}]}


def test_idol_card_id_from_master():
    assert tp.idol_card_id("一匹狼", "ttmr") == "i_card-ttmr-2-000" and tp.idol_card_id("一匹狼", "hski") is None


def test_failed_ranking_retries_on_the_same_page(tmp_path):
    """不合格名次页：没有 CLEAR 结果页，在这一页按重试规则点再挑戦；确认框出来前同一页再被认出不重复算。"""
    p = _play(tmp_path)
    p.layer = 15
    h = p.handlers()
    rt, taps = _rt()
    rows = [{"rank": 1, "name": "白草四音", "score": 105438}, {"rank": 4, "name": "月村手毬", "score": 45231}]
    page = NS(fields={"my_rank": None, "rows": rows, "next": None, "failed": True, "retry": [127, 1160], "back": [351, 1160]})
    assert h["TOWER_RANKING"](rt, None, page) is DONE and taps == [(127, 1160)]
    assert h["TOWER_RANKING"](rt, None, page) is tp.STAY and taps == [(127, 1160)] and p.run.tries[15] == 1
    assert p.run.rankings[15] == [{"my_rank": 4, "rows": rows, "failed": True}] and 15 not in p.run.cleared
    h["TOWER_RETRY_CONFIRM"](rt, None, NS(fields={"cost": None, "same": [492, 1037], "ok": [509, 1160]}))
    assert h["TOWER_RANKING"](rt, None, page) is DONE and p.run.tries[15] == 2  # 第二次不合格：照样再挑戦
