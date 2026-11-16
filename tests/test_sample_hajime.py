"""初采样驱动（tools/sample_hajime.py）的存帧逻辑：画面变了 / KAA 页面变了才存，原尺寸，frames.jsonl；3 分钟不动就停。"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest


def _mod():
    p = Path(__file__).resolve().parents[1] / "tools" / "sample_hajime.py"
    spec = importlib.util.spec_from_file_location("sample_hajime", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_sampler_saves_on_change_and_scene_and_stalls(tmp_path):
    m = _mod()
    now = [0.0]
    s = m.Sampler(tmp_path / "frames", diff=4.0, clock=lambda: now[0])
    raws = iter([np.full((1838, 1032, 3), v, np.uint8) for v in (10, 10, 200, 200, 200)])
    dev = NS(screenshot_raw=lambda: next(raws), screenshot_hook_after=None)
    s.wrap_raw(dev)
    logical = lambda v: np.full((1280, 720, 3), v, np.uint8)  # noqa: E731
    for v, scene in ((10, "start"), (10, "start"), (200, "start"), (200, "ACTION_SELECT")):
        dev.screenshot_raw()
        s.scene = scene
        assert dev.screenshot_hook_after(logical(v)) is not None
        now[0] += 1
    rows = [json.loads(l) for l in (tmp_path / "frames" / "frames.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["scene"] for r in rows] == ["start", "start", "ACTION_SELECT"]  # 第二张没变不存；页面类型变了就存
    assert rows[0]["native"] == [1032, 1838] and (tmp_path / "frames" / rows[0]["file"]).exists()  # 原尺寸
    dev.screenshot_raw()
    now[0] += m.STALL_S
    with pytest.raises(m.SampleStall):
        dev.screenshot_hook_after(logical(200))
