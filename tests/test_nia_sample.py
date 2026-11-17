"""N.I.A 采样模式（hiro.runtime.nia_sample）：开局选难度、认不出的页不点且存帧停下、考试标签、存帧去重。假设备，不连游戏。"""

import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from hiro.loop.errors import ResumeBlocked
from hiro.runtime import nia_sample as ns
from hiro.vision.classify import UNKNOWN, PageHit
from test_opening import _texts, frame, rig  # 同目录（pytest 把测试目录放进 sys.path）


def test_choose_difficulty_taps_pro_then_waits_step1(monkeypatch):
    page = frame({}, _texts(("プロ", 180, 876), ("マスター", 540, 876)))
    step1 = frame({"Produce.TextStepIndicator1": (93, 49)})
    rt, _ = rig(monkeypatch, [page], on_tap=lambda taps: [step1])
    ns.choose_difficulty(rt, "pro")
    assert rt.raw_device.taps == [(180, 876)]


def test_choose_difficulty_master(monkeypatch):
    page = frame({}, _texts(("プロ", 180, 876), ("マスター", 540, 876)))
    rt, _ = rig(monkeypatch, [page], on_tap=lambda taps: [frame({"Produce.TextStepIndicator1": (93, 49)})])
    ns.choose_difficulty(rt, "master")
    assert rt.raw_device.taps == [(540, 876)]


def _rt(tmp_path, now):
    from hiro.runtime.frame import Frame

    taps = []
    rt = NS(clock=lambda: now[0], device=NS(tap=lambda x, y: taps.append((x, y))), session=None, sleep=lambda s: None,
            screen=NS(shot=lambda: Frame(np.zeros((1280, 720, 3), np.uint8), now[0])))  # fmt: skip
    return rt, taps


def test_unknown_page_not_tapped_then_stops_with_frame(tmp_path, monkeypatch):
    from hiro.runtime import play
    from hiro.runtime.frame import Frame

    monkeypatch.setattr(play, "advance", lambda *a: pytest.fail("认不出的画面不该交给 play.advance 连点"))
    now = [0.0]
    rt, taps = _rt(tmp_path, now)
    sampler = ns.Sampler(lambda img: UNKNOWN, tmp_path / "frames")
    adv = ns.make_advance(sampler, stop_s=15)
    f = Frame(np.full((1280, 720, 3), 90, np.uint8), 0.0)
    f.__dict__["texts"] = []
    assert adv(rt, f, UNKNOWN) is False
    now[0] = 10.0
    assert adv(rt, f, UNKNOWN) is False and taps == []
    now[0] = 16.0
    with pytest.raises(ResumeBlocked, match="认不出"):
        adv(rt, f, UNKNOWN)
    assert list((tmp_path / "frames").glob("stop-*-unknown.jpg"))


def test_known_advance_page_delegates(tmp_path, monkeypatch):
    from hiro.runtime import play
    from hiro.runtime.frame import Frame

    called = []
    monkeypatch.setattr(play, "advance", lambda rt, f, hit: called.append(hit.name) or True)
    now = [0.0]
    rt, _ = _rt(tmp_path, now)
    adv = ns.make_advance(ns.Sampler(lambda img: UNKNOWN, tmp_path / "frames"))
    f = Frame(np.zeros((1280, 720, 3), np.uint8), 0.0)
    assert adv(rt, f, PageHit("ACQUIRE", "quick")) is True and called == ["ACQUIRE"]


def test_sampler_saves_on_change_and_maps_tower_exam(tmp_path):
    hits = iter([PageHit("ACTION_SELECT", "x"), PageHit("ACTION_SELECT", "x"), PageHit("TOWER_EXAM", "tower_ocr"), PageHit("TOWER_LIST", "ocr")])
    s = ns.Sampler(lambda img: next(hits), tmp_path / "frames")
    a, b = np.full((1280, 720, 3), 10, np.uint8), np.full((1280, 720, 3), 200, np.uint8)
    assert s(a).name == "ACTION_SELECT"
    assert s(a).name == "ACTION_SELECT"  # 没变：不存
    assert s(b).name == "EXAM"  # N.I.A 试镜被偶像之路的考试判据认中：当考试
    assert s(b).name == "unknown"  # 其余 TOWER_* 当认不出
    rows = [json.loads(line) for line in (tmp_path / "frames" / "frames.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["page"] for r in rows] == ["ACTION_SELECT", "EXAM", "unknown"]


def test_exam_labels_by_count():
    Core = ns.nia_core("produce-004")
    c = Core.__new__(Core)
    c.exam_count = 0
    assert [c._battle_label(None) for _ in range(4)] == ["nia-mid1", "nia-mid2", "nia-final", "nia-final"]


def test_set_mode():
    s = NS(state=NS(produce={"step": 3}))
    ns.set_mode(s, "produce-004")
    assert s.state.produce == {"step": 3, "mode": "produce-004"}
