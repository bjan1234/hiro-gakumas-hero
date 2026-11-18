"""审查日程探测（HIRO_EXAM_SCHEDULE_PROBE，默认关）：点开 → 存帧 → 关掉 → 回到考试画面才继续；关不掉就停机。
面板没有实拍帧：用考试帧压暗代替「盖上来的面板」，OCR 用假的。"""

from pathlib import Path

import cv2
import pytest

from hiro.exec import schedule_probe as sp
from hiro.loop.errors import ResumeBlocked

FIX = Path(__file__).parent / "fixtures" / "exam" / "status" / "dmmw1q-133-faint-slot.jpg"


class Screen:
    def __init__(self, exam_img, close_by):
        self.exam, self.panel = exam_img, (exam_img * 0.3).astype(exam_img.dtype)
        self.state, self.close_by, self.taps, self.t, self.logged = "exam", close_by, [], 0.0, []

    def shoot(self):
        return self.exam if self.state == "exam" else self.panel

    def click(self, x, y):
        self.taps.append((x, y))
        if self.state == "exam" and (x, y) == sp.BONUS_TAP and self.close_by != "never_opens":
            self.state = "panel"
        elif self.state == "panel" and ((self.close_by == "text" and (x, y) == (360, 1180)) or (self.close_by == "retap" and (x, y) == sp.BONUS_TAP)):
            self.state = "exam"

    def ocr(self, img):
        return [("閉じる", 0.99, (320, 1160, 400, 1200))] if self.state == "panel" and self.close_by == "text" else []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def run(self):
        return sp.probe(self.exam, exam="qualify-1", shoot=self.shoot, click=self.click, ocr_boxes=self.ocr, is_exam=lambda im: im is self.exam,
                        log=lambda kind, **k: self.logged.append(kind), clock=self.clock, sleep=self.sleep)  # fmt: skip


@pytest.fixture
def exam_img():
    if not FIX.exists():
        pytest.skip(f"需要样例 {FIX}")
    return cv2.imread(str(FIX))


def test_default_off(monkeypatch):
    monkeypatch.delenv(sp.ENABLED_ENV, raising=False)
    assert not sp.enabled()


def test_closes_with_close_text(exam_img):
    s = Screen(exam_img, "text")
    out = s.run()
    assert out["opened"] and out["closed"] and out["close_by"] == "close_text" and s.state == "exam"
    assert s.taps == [sp.BONUS_TAP, sp.CLOSE_X, (360, 1180)]  # 先点底部 ✕（这个假面板不认），再点「閉じる」
    assert s.logged == ["exam_schedule_probe_open", "exam_schedule_probe_closed"]
    assert out["total_ms"] >= out["open_ms"]


def test_retap_when_no_close_text(exam_img):
    s = Screen(exam_img, "retap")
    out = s.run()
    assert out["closed"] and out["close_by"] == "retap" and s.taps == [sp.BONUS_TAP, sp.CLOSE_X, sp.BONUS_TAP]


def test_not_opened_taps_once(exam_img):
    s = Screen(exam_img, "never_opens")
    out = s.run()
    assert not out["opened"] and out["closed"] and s.taps == [sp.BONUS_TAP]


def test_stuck_panel_stops(exam_img):
    s = Screen(exam_img, "stuck")
    with pytest.raises(ResumeBlocked):
        s.run()
    assert s.state == "panel" and s.taps == [sp.BONUS_TAP, sp.CLOSE_X, sp.BONUS_TAP]  # 只试了 ✕ 和点同一块，没在考试里乱点


def test_tap_far_from_hand():
    x, y = sp.BONUS_TAP
    assert 9 <= x <= 222 and 40 <= y <= 140 and y < 600  # BonusButtonArea 内，远离手牌（y≈860 以下）


# ---------------------------------------------------------------- 只在考试 / 试镜点；关闭后认课程 / 初 / N.I.A 考试 HUD（协调 11-18 初 PRO 实机停机）
@pytest.mark.parametrize(("label", "ok"), [
    ("qualify-1", True), ("r1", True), ("r2", True), ("hajime-mid1", True), ("hajime-final", True), ("nia-mid1", True),
    ("nia-final#audition-2", True), ("hajime-lesson-da", False), ("hajime-lesson-vi-hard", False), ("hajime-lesson", False),
    ("tower", False), ("tower-12", False), (None, False), ("", False),
])  # fmt: skip
def test_should_probe_only_exams(label, ok):
    assert sp.should_probe(label) is ok


@pytest.mark.parametrize(("name", "ok"), [
    ("hajime-lesson-probe-stuck.png", True),  # 课程画面（原来只认 H.I.F 考试，判成没关掉停机）
    ("hajime-lesson-vo.jpg", True), ("hajime-exam.jpg", True),  # 初的考试判页认成 TOWER_EXAM
    ("hajime-action-lessons.jpg", False),
])  # fmt: skip
def test_back_in_exam_recognizes_lesson_and_hajime_exam(name, ok):
    p = Path(__file__).parent / "fixtures" / "pages" / name
    if not p.exists():
        pytest.skip(f"需要实机截图 pages/{name}")
    from hiro.vision.offline import load

    assert sp.back_in_exam(load(cv2.imread(str(p)))) is ok


# ---------------------------------------------------------------- 面板读数（初 PRO 中間第 1 回合前实拍，协调 11-18）
PANEL = Path(__file__).parent / "fixtures" / "pages" / "exam-schedule-panel-hajime-mid1.png"


def _panel_img():
    if not PANEL.exists():
        pytest.skip("需要实机截图 pages/exam-schedule-panel-hajime-mid1.png")
    return cv2.imread(str(PANEL))


def test_read_schedule_panel_real_frame():
    from hiro.vision.schedule import read_schedule_panel, turn_types

    p = read_schedule_panel(_panel_img())
    assert p["current_turn"] == 1 and p["pass_rank"] == 3 and p["pass_score"] == 1700
    assert p["permil"] == {"Vo": 6440, "Da": 6800, "Vi": 4280}
    assert turn_types([p], 9) == ["Vo", "Vi", "Da", "Da", "Vo", "Vo", "Vi", "Da", "Vo"]  # 协调核对的真值


def test_panel_rows_by_icon_not_text():
    """属性按每行图标颜色认（文字只兜底）：9 行图标单独读也全对。"""
    from hiro.vision import schedule as sc

    hsv = cv2.cvtColor(_panel_img(), cv2.COLOR_BGR2HSV)
    assert [sc._attr_by_icon(hsv, y) for y in (356, 445, 533, 621, 710, 797, 885, 974, 1061)] == ["Vo", "Vi", "Da", "Da", "Vo", "Vo", "Vi", "Da", "Vo"]


def test_turn_types_merges_scrolled_screens_and_marks_missing():
    from hiro.vision.schedule import turn_types

    first = {"current_turn": 1, "rows": {i: "Vo" for i in range(9)}}
    second = {"current_turn": 1, "rows": {8: "Vo", 9: "Da", 10: None, 11: "Vi"}}
    assert turn_types([first, second], 12) == ["Vo"] * 9 + ["Da", None, "Vi"]
    assert turn_types([{"current_turn": 3, "rows": {0: "Da", 1: "Vi"}}], 5) == [None, None, "Da", "Vi", None]  # 第 3 回合才点开
    assert turn_types([{"current_turn": None, "rows": {0: "Da"}}], 5) is None


def test_probe_reads_panel_and_closes_with_x():
    """面板读数 + 关闭先点底部 ✕ (360,1160)（原来先找文字再点左上，面板盖在 y≥107，点左上关不掉）。"""
    from hiro.vision.schedule import read_schedule_panel

    exam_img, panel_img = (_panel_img() * 0.5).astype("uint8"), _panel_img()
    state = {"s": "exam"}
    taps = []

    def click(x, y):
        taps.append((x, y))
        if state["s"] == "exam" and (x, y) == sp.BONUS_TAP:
            state["s"] = "panel"
        elif state["s"] == "panel" and (x, y) == (360, 1160):
            state["s"] = "exam"

    t = [0.0]
    out = sp.probe(exam_img, exam="hajime-mid1", shoot=lambda: exam_img if state["s"] == "exam" else panel_img, click=click,
                   ocr_boxes=lambda img: [], is_exam=lambda im: im is exam_img, clock=lambda: t[0],
                   sleep=lambda s: t.__setitem__(0, t[0] + s), read_panel=read_schedule_panel, total_turns=9)  # fmt: skip
    assert out["closed"] and out["close_by"] == "close_x" and taps == [sp.BONUS_TAP, (360, 1160)]
    assert out["panel"]["turn_types"] == ["Vo", "Vi", "Da", "Da", "Vo", "Vo", "Vi", "Da", "Vo"]


def test_apply_panel_writes_exam_state():
    from types import SimpleNamespace as NS

    from hiro.contracts import GameState

    st = GameState(exam={"attr_permil": {"Vo": 1000}})
    mem = NS(attr_permil={})
    sp.apply_panel({"turn_types": ["Vo", "Da"], "permil": {"Vo": 6440, "Da": 6800, "Vi": 4280}, "pass_rank": 3, "pass_score": 1700},
                   NS(state=st), mem)  # fmt: skip
    assert st.exam["turn_types"] == ["Vo", "Da"] and st.sources["exam.turn_types"].origin == "screen"
    assert st.exam["attr_permil"] == {"Vo": 6440, "Da": 6800, "Vi": 4280} and mem.attr_permil["Da"] == 6800
    assert st.exam["pass_line"] == {"rank": 3, "score": 1700}
