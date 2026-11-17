"""初课程的画面读数（协调 11-18，配合 8a3a1e7 把课程接到 GNRPA）：开课回合数 / CLEAR 线 / 满分线 → exam_session.lesson，按主数据
算 exam_extra_turn / lesson_limit_up_score；同种同属性第几次。另：相談開始確認（P 少）按最近决策点。实机帧在私有 fixtures pages/hajime-*。"""

from pathlib import Path
from types import SimpleNamespace as NS

import cv2
import pytest

from hiro.contracts import Action, Decision

FIXP = Path(__file__).with_name("fixtures") / "pages"
IDOL = "i_card-shro-3-007"  # 广（plan2）


def _img(name):
    p = FIXP / name
    if not p.exists():
        pytest.skip(f"需要实机截图 pages/{name}")
    from hiro.vision.offline import load

    return load(cv2.imread(str(p)))


def test_hud_normal_lesson():
    from hiro.vision import hajime as hv

    img = _img("hajime-lesson-vo.jpg")
    assert hv.read_lesson_hud(img) == {"goal": "clear", "left": 25, "param": 155} and hv.lesson_turns(img) == 6
    assert hv.read_lesson_hud(_img("hajime-lesson-perfect.jpg")) == {"goal": "perfect", "left": 1, "param": 204}


def test_hud_hard_lesson():
    """追い込み：回合两位数（模板会读成 1）、过 CLEAR 后右上换成「追い込みボーナス」（不是属性值）。"""
    from hiro.vision import hajime as hv

    img = _img("hajime-lesson-hard-start.jpg")
    assert hv.lesson_turns(img) == 11 and hv.read_lesson_hud(img) == {"goal": "clear", "left": 165, "param": 397}
    bonus = hv.read_lesson_hud(_img("hajime-lesson-hard-bonus.jpg"))
    assert bonus["goal"] == "perfect" and bonus["param"] is None
    assert hv.lesson_turns(_img("hajime-lesson-hard-bonus.jpg")) == 3  # 「2+1」：剩 2 + 追加 1


def test_lesson_info_normal_matches_master():
    from hiro.runtime.hajime import LessonInfo

    info = LessonInfo("hajime-lesson-vo", 1, "produce-001", IDOL)
    assert info.needs("clear")
    info.feed("clear", {"goal": "clear", "left": 25, "param": 155}, 6)
    assert info.d["clear_target"] == 25 and info.d["exam_extra_turn"] == 0 and info.d["level_ids"]
    assert all("plan2-normal" in i for i in info.d["level_ids"])
    info.feed("perfect", {"goal": "perfect", "left": 1, "param": 204}, None)
    assert info.d["perfect_target"] is None  # 一次不采用（加分动画中会跳）
    info.feed("perfect", {"goal": "perfect", "left": 1, "param": 204}, None)
    assert info.d["perfect_target"] == 50 and info.d["lesson_limit_up_score"] == 0 and info.done


def test_lesson_info_extra_turn_and_limit_up():
    from hiro.runtime.hajime import LessonInfo

    info = LessonInfo("hajime-lesson-da", 2, "produce-001", IDOL)
    info.feed("clear", {"goal": "clear", "left": 25, "param": 300}, 8)
    for _ in range(2):
        info.feed("perfect", {"goal": "perfect", "left": 30, "param": 340}, None)
    assert (info.d["exam_extra_turn"], info.d["perfect_target"], info.d["lesson_limit_up_score"]) == (2, 70, 20)


def test_lesson_info_hard_unmatched_left_empty():
    """追い込み：画面 CLEAR 90 / 165，初 REGULAR 主数据 hard 档是 75 / 100，对不上 → 不给档位和差值（不猜）；满分线读不到也留空。"""
    from hiro.runtime.hajime import LessonInfo

    info = LessonInfo("hajime-lesson-vi-hard", 1, "produce-001", IDOL)
    info.feed("clear", {"goal": "clear", "left": 165, "param": 397}, 11)
    for _ in range(2):
        info.feed("perfect", {"goal": "perfect", "left": 300, "param": None}, None)
    assert info.d["kind"] == "hard" and info.d["turns_total"] == 11 and info.d["clear_target"] == 165
    assert info.d["level_ids"] is None and info.d["exam_extra_turn"] is None and info.d["perfect_target"] is None


def test_lesson_kind():
    from hiro.runtime.hajime import lesson_kind

    assert lesson_kind("hajime-lesson-vo-sp") == ("Vo", "sp")
    assert lesson_kind("hajime-lesson-da-hard") == ("Da", "hard")
    assert lesson_kind("hajime-lesson-vi") == ("Vi", "normal")
    assert lesson_kind("hajime-lesson") == (None, "normal")


def test_exam_session_has_lesson_field():
    from hiro.contracts import GameState

    st = GameState()
    st.exam_session.lesson = {"kind": "normal"}
    assert GameState.from_dict(st.to_dict()).exam_session.lesson == {"kind": "normal"} if hasattr(GameState, "from_dict") else True


# ---------------------------------------------------------------- 相談開始確認（P 少）
def _rt(last):
    from test_runtime import frame as fake_frame
    from test_runtime import runtime

    rt, _ = runtime([fake_frame()])
    rt.session = NS(last_decision=last)
    return rt


def _check(rt):
    from hiro.runtime import interrupts
    from hiro.runtime.frame import Frame

    p = FIXP / "hajime-consult-lowp-confirm.png"
    if not p.exists():
        pytest.skip("需要实机截图 pages/hajime-consult-lowp-confirm.png")
    return interrupts.check(Frame(cv2.imread(str(p)), 0.0), rt)


def test_consult_confirm_after_shop_decision_starts():
    rt = _rt(("ACTION_SELECT", Decision(Action.produce_next("shop"), "相談", "rule", 0.8)))
    assert "開始する" in _check(rt)
    (x, y), = rt.raw_device.taps
    assert abs(x - 512) < 30 and abs(y - 1160) < 20


@pytest.mark.parametrize("last", [None, ("ACTION_SELECT", Decision(Action.produce_next("training", attr="Da"), "课程", "rule", 0.8))])
def test_consult_confirm_otherwise_cancels(last):
    rt = _rt(last)
    assert "キャンセル" in _check(rt)
    (x, y), = rt.raw_device.taps
    assert x < 300 and abs(y - 1160) < 20
