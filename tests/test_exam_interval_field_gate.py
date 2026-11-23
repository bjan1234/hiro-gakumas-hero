"""考试引擎：带场面条件的出牌计数触发，只计出牌开始时条件成立的那几次（#43）。

莉波的 P 道具「憧れ続けた輝き」：好調 8 回合以上时，好調类技能卡每用 4 次发动。实机上好調 6、7 回合时打的好調卡不计数，
引擎以前照样计数，到 T3 提前发动、提前抽走了牌。GKMS rev383（card_play_select，HIF-97）同样只计条件成立时的出牌。
Python / Rust 两个后端都要这样。"""

import json

import hiro.sim  # noqa: F401  把 vendor/gakumas-player 放上 sys.path

import pytest

ITEM = "pitem_01-3-312-0"  # 憧れ続けた輝き
TRIGGER = "e_trigger-exam_play_count_interval-4-parameter_buff_up-8-p_card_search-target-effect_group-visible-exam_parameter_buff-000"
CARD = "p_card-01-act-1_002"  # 軽い足取り：好調类，检索命中
PHASE = 23  # ExamPlayCountInterval


def _exam(kocho):
    from gakumas_exam.master import load
    from gakumas_exam.setup import new_exam

    ex = new_exam(None, load(), 1, deck=[(CARD, 0)] * 20, items=[ITEM], turn_types=[1] * 12, stamina=30, plan_type=1)
    ex.status._try_add("TryAddParameterBuffStatus", turn=kocho)
    assert ex.status.GetParameterBuffTurn(False) == kocho
    return ex


def _py_count(ex):
    from gakumas_exam.status import TriggerEffect

    (s,) = [s for s in ex.status.effects if isinstance(s, TriggerEffect) and s.trigger.get("id") == TRIGGER]
    return s.phase_count.get(PHASE, 0)


def _rs_count(rx):
    effects = json.loads(rx.export_json())["status"]["effects"]
    (s,) = [s for s in effects if s.get("trig") and s["trig"]["trigger"]["id"] == TRIGGER]
    return dict(map(tuple, s["trig"]["phase_count"])).get(PHASE, 0)


@pytest.mark.sim_master  # 真跑模拟：要主数据（fetch_master.py）
@pytest.mark.parametrize(("kocho", "counted"), [(6, 0), (7, 0), (8, 1)])
def test_python_counts_only_plays_with_field_condition(kocho, counted):
    ex = _exam(kocho)
    ex.step(("play", 0))
    assert _py_count(ex) == counted


@pytest.mark.sim_master
@pytest.mark.parametrize(("kocho", "counted"), [(6, 0), (7, 0), (8, 1)])
def test_rust_counts_only_plays_with_field_condition(kocho, counted):
    from gakumas_exam import native

    if not native.available():
        pytest.skip("没装 gakumas_exam_rs")
    rx = native.to_native(_exam(kocho))
    rx.step(("play", 0))
    assert _rs_count(rx) == counted
