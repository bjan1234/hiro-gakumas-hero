"""协调 11-17（逆向 10 节）三件：② N.I.A 营业场所的花费类型 / 数值 / 大成功概率；③ N.I.A PRO 简单模式的 N.I.Aキー（黄緑）；
① 日程列表采样探针（开关 HIRO_SCHEDULE_PROBE，默认关）。实机帧在私有 fixtures pages/nia-sales-place*。"""

from pathlib import Path
from types import SimpleNamespace as NS

import cv2
import numpy as np
import pytest

FIXP = Path(__file__).with_name("fixtures") / "pages"


def _read(name):
    from hiro.vision.nia import read_nia_page
    from hiro.vision.ocr import screen_texts

    p = FIXP / name
    if not p.exists():
        pytest.skip(f"需要实机截图 pages/{name}")
    img = cv2.imread(str(p))
    return read_nia_page(screen_texts(img), img)


def _costs(places):
    return [(p["cost_type"], p["cost"], p["hp_cost"], p["p_cost"]) for p in places]


def test_sales_place_cost_types():
    _, f = _read("nia-sales-place.png")
    assert _costs(f["places"]) == [("stamina", 5, 5, 0), (None, 0, 0, 0), ("stamina", 5, 5, 0)]
    assert all("great_success_pct" not in p for p in f["places"])  # 没展开：看不到大成功


@pytest.mark.parametrize(("name", "i", "pct", "votes"), [("nia-sales-place-camp-expanded.png", 0, 90, 840), ("nia-sales-place-expanded.png", 2, 100, 720)])
def test_expanded_great_success(name, i, pct, votes):
    _, f = _read(name)
    assert f["selected"] == i
    assert (f["places"][i]["great_success_pct"], f["places"][i]["great_success_votes"]) == (pct, votes)
    assert all("great_success_pct" not in p for k, p in enumerate(f["places"]) if k != i)


def _pill(hue: int, n: int = 600):
    """合成一条药丸：HEART_X 里放 n 个指定色相的高亮像素。"""
    from hiro.vision.nia import HEART_X

    hsv = np.zeros((60, 720, 3), np.uint8)
    hsv[..., 2] = 120
    ys, xs = np.unravel_index(np.arange(n), (40, HEART_X[1] - HEART_X[0]))
    hsv[ys + 10, xs + HEART_X[0]] = (hue, 220, 240)
    return hsv


def test_cost_icon_by_color():
    from hiro.vision.nia import _cost_icon

    assert _cost_icon(_pill(60), 0, 59) == "stamina"  # 爱心：黄绿渐变，绿占多数
    assert _cost_icon(_pill(25), 0, 59) == "produce_point"  # P 图标：黄色
    assert _cost_icon(_pill(110), 0, 59) is None  # 认不出：不定类型
    assert _cost_icon(_pill(60, n=50), 0, 59) is None  # 没有图标（消費なし）


# ---------------------------------------------------------------- ③ N.I.Aキー（黄緑）
def _obs(seq, page, fields):
    from hiro.contracts import Observation, PageObs

    return Observation(seq=seq, t=0.0, page=PageObs(name=page, area="produce", stable_frames=1), fields=fields)


def test_easy_key_seen_on_acquire_even_while_debouncing():
    from hiro.contracts import GameState
    from hiro.loop.reduce import reduce

    st = GameState(produce={"mode": "produce-004"})
    st = reduce(st, _obs(3, "ACQUIRE", {"kind": "pitem", "pitem_id": "pitem_00-3-330-0", "pitem_ids": ["pitem_00-3-330-0"]}))
    assert st.produce["nia_easy_key"] is True and st.sources["produce.nia_easy_key"].seq == 3


def test_easy_key_from_exam_pitems_and_absent_otherwise():
    from hiro.contracts import GameState
    from hiro.loop.reduce import reduce

    st = reduce(GameState(produce={"mode": "produce-004"}), _obs(1, "HIF_EXAM", {"pitems": [{"pitem_id": "pitem_00-3-330-0"}]}))
    assert st.produce["nia_easy_key"] is True
    st = reduce(GameState(produce={"mode": "produce-004"}), _obs(1, "ACQUIRE", {"kind": "pitem", "pitem_id": "pitem_02-3-102-0"}))
    assert "nia_easy_key" not in st.produce  # 没看到不写（不断言没有）


# ---------------------------------------------------------------- ① 日程列表探针
def _frames(*vals):
    return [np.full((1280, 720, 3), v, np.uint8) for v in vals]


def _probe(tmp_path, monkeypatch, shots, at_action, texts=()):
    from hiro.produce import schedule_probe as sp

    seq = iter(shots)
    last = {"img": shots[0]}

    def shoot():
        last["img"] = next(seq, last["img"])
        return last["img"]

    clicks, swipes = [], []
    monkeypatch.setattr(sp, "_at_action_select", at_action)
    monkeypatch.setattr("hiro.vision.ocr.screen_texts", lambda img: list(texts))
    r = sp.probe(tmp_path / "p", shoot=shoot, click=lambda x, y: clicks.append((x, y)), swipe=lambda *a: swipes.append(a), sleep=lambda s: None)
    return r, clicks, swipes


def test_probe_entry_wrong_does_nothing(tmp_path, monkeypatch):
    r, clicks, swipes = _probe(tmp_path, monkeypatch, _frames(100, 100), lambda img: True)
    assert r["opened"] is False and clicks == [(112, 92)] and swipes == [] and (tmp_path / "p" / "probe.json").exists()


def test_probe_saves_list_and_closes(tmp_path, monkeypatch):
    from hiro.vision.ocr import Box, Text

    close = Text("閉じる", Box(320, 1140, 400, 1180))
    # 选行动 → 列表第 1 屏 → 第 2 屏 → 到底（不变）→ 关之前一帧（列表）→ 回到选行动
    shots = _frames(100, 30, 60, 60, 60, 100)
    r, clicks, swipes = _probe(tmp_path, monkeypatch, shots, lambda img: float(img.mean()) == 100, texts=[close])
    assert r["opened"] and r["closed"] and r["frames"] == ["01-list.jpg", "02-list.jpg"] and len(swipes) == 2
    assert clicks == [(112, 92), (360, 1160)]


def test_probe_cannot_close_stops(tmp_path, monkeypatch):
    from hiro.loop.errors import ResumeBlocked

    with pytest.raises(ResumeBlocked):
        _probe(tmp_path, monkeypatch, _frames(100, 30, 30), lambda img: False)


def test_probe_off_by_default(monkeypatch):
    from hiro.produce import schedule_probe
    from hiro.produce.hif import HifCore

    monkeypatch.delenv("HIRO_SCHEDULE_PROBE", raising=False)
    called = []
    monkeypatch.setattr(schedule_probe, "probe", lambda *a, **k: called.append(1))
    class Core:
        _schedule_probed = False
        s = NS(state=NS(produce={"mode": "produce-004"}))

    HifCore._maybe_probe_schedule(Core())
    assert called == []
    monkeypatch.setenv("HIRO_SCHEDULE_PROBE", "1")
    Core.s = NS(state=NS(produce={"mode": "produce-007"}))  # H.I.F 不探
    HifCore._maybe_probe_schedule(Core())
    assert called == []
