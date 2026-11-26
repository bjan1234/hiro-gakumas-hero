"""工作派遣选时长：模板认不出时按字点「12時間」（11-27 DMM 实跑：缺省选中带橙色角框，模板 30 秒没认出，整项失败）。"""

from types import SimpleNamespace as NS

from hiro.daily import assignment
from hiro.runtime.frame import Frame
from hiro.vision.ocr import Box, Text

import numpy as np


def _frame(*texts):
    f = Frame(np.zeros((1280, 720, 3), np.uint8), 0.0)
    f.__dict__["texts"] = [Text(t, Box(x - 60, y - 20, x + 60, y + 20)) for t, x, y in texts]
    return f


def test_tap_hours_falls_back_to_text(monkeypatch):
    taps = []
    monkeypatch.setattr(assignment.nav, "find", lambda f, name: None)
    f = _frame(("ミニライブ Lv12", 140, 130), ("4時間", 137, 930), ("8時間", 360, 930), ("12時間", 584, 930))
    rt = NS(device=NS(tap=lambda x, y: taps.append((x, y))), drive=lambda step, timeout, what, every=0.5: step(f))
    assignment._tap_hours(rt, 12)
    assert taps == [(584, 930)]
