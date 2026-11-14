"""新主循环接线（hiro.runtime.play / scenes，HIRO_RUNTIME=own）：非弹窗场景、advance 的范围、run_hif 的分支。"""

from types import SimpleNamespace as NS

import numpy as np

from hiro.runtime import play, scenes
from hiro.vision.ocr import Box, Text


def T(text, x, y):
    return Text(text, Box(x - 20, y - 10, x + 20, y + 10))


class FakeRt:
    def __init__(self, fresh=None):
        self.taps, self.recovers = [], []
        self.device = NS(tap=lambda x, y: self.taps.append((x, y)))
        self.screen = NS(shot=lambda: NS(img=np.zeros((1280, 720, 3), np.uint8)))
        self.session = NS(recover=lambda k, d: self.recovers.append(k))
        self.sleep = lambda s: None
        self.fresh = fresh or []


def frame(texts, landscape=False):
    shape = (720, 1280, 3) if landscape else (1280, 720, 3)
    return NS(img=np.zeros(shape, np.uint8), texts=texts)


def test_live_start_only_on_landscape_track_page():
    rt = FakeRt()
    assert scenes.live_start(rt, frame([T("TAP TO START", 640, 600)], landscape=True)) and rt.taps == [(640, 600)]
    assert not scenes.live_start(rt, frame([T("TAP TO START", 640, 600)]))  # 竖屏不管
    assert scenes.live_start(rt, frame([T("作詞 なんとか", 300, 300)], landscape=True)) and rt.taps[-1] == (640, 612)


def test_commu_skip_taps_recognized_skip_only(monkeypatch):
    rt = FakeRt()
    bar = [T("早送り", 600, 1200), T("ログ", 400, 1200), T("SKIP", 200, 1200)]
    monkeypatch.setattr(scenes, "screen_texts", lambda img: bar)
    assert scenes.commu_skip(rt, frame(bar)) and rt.taps == [(200, 1200)]
    monkeypatch.setattr(scenes, "screen_texts", lambda img: [T("早送り", 600, 1200), T("SKIP", 200, 900)])  # SKIP 不在左下：不点
    assert not scenes.commu_skip(rt, frame(bar))
    assert not scenes.commu_skip(rt, frame([T("SKIP", 200, 1200)]))  # 没有「早送り」不是剧情


def test_first_run_settings_pick_then_confirm(monkeypatch):
    rt = FakeRt()
    boxes = [T("サポートイベント設定", 360, 400), T("強化済みで獲得する", 360, 700), T("決定", 520, 1160)]
    monkeypatch.setattr(scenes, "screen_texts", lambda img: boxes)
    assert scenes.first_run_settings(rt, frame(boxes)) and rt.taps == [(360, 700), (520, 1160)] and rt.recovers == ["dialog"]


def test_advance_only_bursts_on_safe_pages(monkeypatch):
    import hiro.loop.advance as adv

    rt = FakeRt()
    calls = []
    monkeypatch.setattr(adv, "burst", lambda texts, **kw: calls.append(texts) or 2)
    monkeypatch.setattr(scenes, "commu_skip", lambda rt, f: False)
    monkeypatch.setattr(scenes, "first_run_settings", lambda rt, f: False)
    assert play.advance(rt, frame([]), NS(name="unknown")) is True
    assert play.advance(rt, frame([]), NS(name="HIF_FINALS_RANKING")) is False  # 认得出、但没处理器的页：不乱点
    assert play.advance(rt, frame([], landscape=True), NS(name="LIVE")) is False  # 横屏演出中：不点
    assert len(calls) == 1


def test_run_hif_own_branch_skips_kaa_init(monkeypatch, tmp_path):
    import sys

    import hiro.run_hif as rh

    monkeypatch.setenv("HIRO_RUNTIME", "own")
    monkeypatch.chdir(tmp_path)
    called = {}
    monkeypatch.setattr(rh, "init_kaa", lambda *a, **k: called.setdefault("init_kaa", True))
    monkeypatch.setattr("hiro.runtime.play.run", lambda args, session: called.setdefault("play", args.command) and 0)
    monkeypatch.setattr(rh.manifest_mod, "collect", lambda: NS(problems=[], to_dict=lambda: {}, exam_state_source="x", exam_advisor="y"))
    monkeypatch.setattr(rh, "_write_report", lambda trace, name: called.setdefault("report", name))
    monkeypatch.setattr(sys, "argv", ["run_hif", "resume", "--mode", "main", "--trace", "t-own"])
    assert rh.main() == 0
    assert called == {"play": "resume", "report": "t-own"}
