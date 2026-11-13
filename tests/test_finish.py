"""续跑进培育、结算收尾回首页、活動支給（hiro.runtime.finish）：假设备 + 假帧（复用 test_opening 的 rig / frame）。"""

import pytest

from hiro.runtime import UNKNOWN, finish
from hiro.vision.classify import PageHit
from hiro.vision.ocr import Box, Text
from test_opening import HOME, frame, rig  # 同目录（pytest 把测试目录放进 sys.path）


def T(text, x, y):
    return Text(text, Box(x - 20, y - 10, x + 20, y + 10))


def test_resume_taps_resume_then_enters(monkeypatch):
    monkeypatch.setattr("hiro.vision.quick.quick_page", lambda img: None)
    dlg = frame({}, [T("プロデュース再開", 360, 500), T("キャンセル", 200, 1160), T("再開する", 500, 1160)])
    rt, _ = rig(monkeypatch, [frame(HOME)], on_tap=lambda taps: [dlg] if len(taps) == 1 else [frame({})])
    assert finish.resume_produce(rt) == "resumed"
    assert rt.raw_device.taps[0] == tuple(finish.box("Produce.BoxProduceOngoing").center) and rt.raw_device.taps[1] == (500, 1160)


def test_resume_already_in_produce(monkeypatch):
    monkeypatch.setattr("hiro.vision.quick.quick_page", lambda img: None)
    monkeypatch.setattr("hiro.vision.classify.classify_scene", lambda img: PageHit("ACTION_SELECT", "pixel"))
    rt, _ = rig(monkeypatch, [frame({})])
    assert finish.resume_produce(rt) == "already" and rt.raw_device.taps == []


def test_finish_stops_at_start_confirm_and_never_presses_start(monkeypatch):
    confirm = frame({}, [T("2.開始確認", 360, 100), T("本戦へ", 500, 1160)])
    rt, _ = rig(monkeypatch, [confirm])
    assert finish.finish_produce_end(rt) is True and rt.raw_device.taps == []
    rt, _ = rig(monkeypatch, [confirm], on_tap=lambda taps: [frame(HOME)])
    assert finish.finish_produce_end(rt, go_home=True) is True
    assert rt.raw_device.taps == [(85, 1185)]  # go_home：点左下首页图标，不点「本戦へ」


def test_finish_clicks_through_result_screens(monkeypatch):
    pages = [frame({}, [T("プロデュース完了", 360, 300), T("次へ", 360, 1160)]),
             frame({"InProduce.End.ButtonGenerate": (360, 1100)}),
             frame({}, [T("ログインボーナス", 360, 400)]), frame(HOME)]  # fmt: skip
    rt, _ = rig(monkeypatch, [pages[0]], on_tap=lambda taps: [pages[len(taps)]])
    assert finish.finish_produce_end(rt)
    assert rt.raw_device.taps == [(360, 1160), (360, 1100), (360, 1180)]  # 次へ、生成、领奖页点底部空白


def test_allowance_and_produce_end_handlers(monkeypatch):
    rt, _ = rig(monkeypatch, [frame({"InProduce.LootboxSliverLock": (360, 700)})])
    assert finish.on_allowance(rt, rt.screen.shot(), UNKNOWN).kind == "done"
    assert rt.raw_device.taps == [(360, 700), finish.BLANK_TAP]
    monkeypatch.setattr(finish, "finish_produce_end", lambda rt: True)
    assert finish.on_produce_end(rt, rt.screen.shot(), UNKNOWN) is finish.END


def test_run_stops_on_end(monkeypatch):
    rt, _ = rig(monkeypatch, [frame({})])
    rt.classify = lambda img: PageHit("PRODUCE_END", "template")
    rt.handlers = {"PRODUCE_END": lambda rt, f, hit: finish.END}
    assert rt.run(until=lambda: False) == 1
