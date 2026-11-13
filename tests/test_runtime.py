"""新主循环骨架 hiro.runtime：危险点击拦截、中断层、wait_until、主循环一拍、暂停检查点、不 import KAA。全用假设备和假帧。"""

import os
import subprocess
import sys
import threading

import numpy as np
import pytest

from hiro.loop.date_change import DateChanged
from hiro.loop.errors import ResumeBlocked
from hiro.runtime import DONE, STAY, UNKNOWN, DangerBlocked, Frame, PageHit, Runtime, stop
from hiro.runtime import guard, interrupts
from hiro.vision.ocr import Box, Text


def T(text, x, y):
    return Text(text, Box(x - 20, y - 10, x + 20, y + 10))


def frame(texts=(), dialog=None, t=0.0, fill=0):
    """假帧：文字和弹窗读数直接给，不跑识别。fill：画面底色（不同底色 = 画面变了）。"""
    f = Frame(np.full((1280, 720, 3), fill, np.uint8), t)
    f.__dict__.update(texts=list(texts), has_dialog=dialog is not None, dialog=dialog)
    return f


REAL_WORD_AT = guard.word_at


@pytest.fixture(autouse=True)
def _word_from_frame(monkeypatch):
    """点击点读字：用假帧给的文字，不真跑局部 OCR。"""
    def word_at(f, x, y):
        return next((t.text for t in f.texts if t.rect.x1 - 6 <= x <= t.rect.x2 + 6 and t.rect.y1 - 6 <= y <= t.rect.y2 + 6), None)

    monkeypatch.setattr(guard, "word_at", word_at)


class FakeDevice:
    name = "fake"

    def __init__(self):
        self.taps = []

    def screenshot(self):
        return np.zeros((1280, 720, 3), np.uint8)

    def tap(self, x, y):
        self.taps.append((x, y))

    def real_tap(self, x, y):
        self.taps.append(("real", x, y))

    def secret_click(self, x, y):  # 白名单外的方法：GuardedDevice 不该转发
        self.taps.append(("secret", x, y))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def runtime(frames, *, classify=lambda img: UNKNOWN, **kw):
    """Runtime，截图依次给 frames 里的帧（用完重复最后一帧）。"""
    clock = Clock()
    rt = Runtime(FakeDevice(), classify, clock=clock, sleep=clock.sleep, **kw)
    seq = list(frames)

    def shot():
        f = seq.pop(0) if len(seq) > 1 else seq[0]
        f.t = clock()
        rt.screen.frame = f
        return f

    rt.screen.shot = shot
    return rt, clock


RETIRE = {"kind": "retire", "title": "プロデュース・リタイア確認", "danger": True, "y": 600}
DISCARD = {"kind": "data_discard", "title": "プロデュースデータの破棄", "danger": True, "y": 600}
PLAIN = {"kind": "other", "title": "確認", "danger": False, "y": 600}


# ---------------------------------------------------------------- 危险点击拦截
def test_guard_on_danger_dialog_only_allows_cancel():
    rt, _ = runtime([frame([T("キャンセル", 200, 1160), T("リタイア", 500, 1160)], RETIRE)])
    rt.screen.shot()
    with pytest.raises(DangerBlocked):
        rt.device.tap(500, 1160)
    with pytest.raises(DangerBlocked):
        rt.device.tap(360, 640)  # 空白处也不行
    rt.device.tap(200, 1160)
    assert rt.raw_device.taps == [(200, 1160)]


def test_guard_hard_words_blocked_without_dialog_and_menu_ok():
    rt, _ = runtime([frame([T("ジュエルで回復", 360, 900), T("閉じる", 360, 1160), T("リタイア", 600, 1000)])])
    rt.screen.shot()
    with pytest.raises(DangerBlocked):
        rt.device.tap(360, 900)
    with pytest.raises(DangerBlocked):
        rt.device.tap(600, 1000)
    rt.device.tap(360, 1160)  # ≡ 菜单上点「閉じる」：同一画面有「リタイア」字样也照点
    rt.device.tap(100, 100)
    assert rt.raw_device.taps == [(360, 1160), (100, 100)]


def test_guard_rechecks_stale_frame_and_covers_real_tap():
    """处理器截完图等了一会儿才点：期间弹出的危险框要看见（帧比 0.5 s 旧就重截）。real_tap 同样拦；白名单外的方法不给。"""
    rt, clock = runtime([frame([T("決定", 500, 1160)]), frame([T("リタイア", 500, 1160), T("キャンセル", 200, 1160)], RETIRE)])
    rt.screen.shot()
    clock.now = 2.0
    with pytest.raises(DangerBlocked):
        rt.device.tap(500, 1160)
    with pytest.raises(DangerBlocked):
        rt.device.real_tap(500, 1160)
    rt.device.real_tap(200, 1160)
    assert rt.raw_device.taps == [("real", 200, 1160)]
    with pytest.raises(AttributeError):
        rt.device.secret_click(1, 1)
    assert rt.device.screenshot().shape == (1280, 720, 3)


def test_word_at_reads_only_a_small_region(monkeypatch):
    """点击点读字只 OCR 周围 320×80（贴边时裁到画面内），不做整帧 OCR。"""
    seen = []

    def fake(img, rect=None):
        seen.append(rect)
        return [T("決定", 500, 1160), T("キャンセル", 200, 1160)]

    monkeypatch.setattr(guard, "screen_texts", fake)
    f = frame()
    assert REAL_WORD_AT(f, 500, 1160) == "決定" and seen[-1] == (340, 1120, 320, 80)
    assert REAL_WORD_AT(f, 700, 1270) is None and seen[-1] == (540, 1230, 180, 50)


# ---------------------------------------------------------------- 中断层
def test_red_line_taps_cancel_and_discard_stops():
    rt, _ = runtime([frame([T("キャンセル", 200, 1160)], RETIRE)])
    f = rt.screen.shot()
    assert "キャンセル" in interrupts.red_line(f, rt) and rt.raw_device.taps == [(200, 1160)]
    rt, _ = runtime([frame([T("キャンセル", 200, 1160), T("開始する", 500, 1160)], DISCARD)])
    with pytest.raises(ResumeBlocked, match="破弃由用户决定"):
        interrupts.red_line(rt.screen.shot(), rt)
    assert rt.raw_device.taps == [(200, 1160)]  # 只点了キャンセル，没点開始する
    rt, _ = runtime([frame([T("リタイア", 500, 1160)], RETIRE)])
    with pytest.raises(ResumeBlocked, match="没读到"):
        interrupts.red_line(rt.screen.shot(), rt)


def test_stop_notice_and_date_change():
    rt, _ = runtime([frame([T("ただいまメンテナンス中です", 360, 640)], PLAIN)])
    with pytest.raises(ResumeBlocked, match="维护"):
        interrupts.check(rt.screen.shot(), rt)
    notice = {"kind": "other", "title": "メンテナンスのお知らせ", "danger": False, "y": 400}
    rt, _ = runtime([frame([T("11/20 15:00〜 メンテナンスを予定しております", 360, 640)], notice)])
    assert interrupts.stop_notice(rt.screen.shot(), rt) is None  # 预告不停
    rt, _ = runtime([frame([T("日付変更", 360, 600), T("タイトルへ", 360, 1160)], PLAIN)])
    with pytest.raises(DateChanged):
        interrupts.check(rt.screen.shot(), rt)


def test_comm_error_only_retry():
    rt, _ = runtime([frame([T("通信エラー", 360, 500), T("タイトルへ", 200, 1160), T("リトライ", 500, 1160)], PLAIN)])
    assert interrupts.check(rt.screen.shot(), rt) == "通信エラー：retry"
    assert rt.raw_device.taps == [(500, 1160)]


def test_no_dialog_skips_ocr():
    f = frame()
    f.__dict__.pop("texts")  # 碰 texts 就会真去 OCR：没弹窗时中断层不该碰
    rt, _ = runtime([f])
    assert interrupts.check(rt.screen.shot(), rt) is None and "texts" not in f.__dict__


# ---------------------------------------------------------------- wait_until / 主循环一拍
def test_wait_until_hits_and_times_out():
    rt, clock = runtime([frame(), frame(), frame([T("OK", 1, 1)])])
    ok, f = rt.wait_until(lambda f: any(t.text == "OK" for t in f.texts), timeout=5)
    assert ok and clock.now == pytest.approx(0.6)
    rt, clock = runtime([frame()])
    ok, _ = rt.wait_until(lambda f: False, timeout=2)
    assert not ok and clock.now == pytest.approx(2.1)


def test_step_dispatches_handler_and_stop_raises():
    seen = []

    def handler(rt, f, hit):
        seen.append(hit.name)
        return DONE if len(seen) == 1 else stop("读不出候选")

    rt, _ = runtime([frame()], classify=lambda img: PageHit("SELECT_CARD", "quick"), handlers={"SELECT_CARD": handler})
    assert rt.step() is DONE and seen == ["SELECT_CARD"]
    with pytest.raises(ResumeBlocked, match="SELECT_CARD：读不出候选"):
        rt.step()


def test_step_unknown_advances_then_watchdog_stops():
    advanced = []
    rt, clock = runtime([frame()], advance=lambda rt, f, hit: advanced.append(hit.name) or False)
    assert rt.step() is STAY and advanced == ["unknown"]
    clock.now = 179.0
    rt.step()
    clock.now = 181.0
    with pytest.raises(ResumeBlocked, match="没变化|认不出"):
        rt.step()


def test_unknown_stops_even_if_screen_keeps_changing():
    rt, clock = runtime([frame(fill=v % 2 * 200) for v in range(20)])
    for now in (0.0, 90.0, 179.0):
        clock.now = now
        rt.step()
    clock.now = 181.0
    with pytest.raises(ResumeBlocked, match="认不出"):
        rt.step()


def test_known_page_stuck_stops_but_progress_does_not():
    rt, clock = runtime([frame()], classify=lambda img: PageHit("ACTION_SELECT", "pixel"), handlers={"ACTION_SELECT": lambda rt, f, hit: STAY})
    rt.step()
    clock.now = 181.0
    with pytest.raises(ResumeBlocked, match="ACTION_SELECT 页面和画面"):
        rt.step()
    rt, clock = runtime([frame(fill=v % 2 * 200) for v in range(10)], classify=lambda img: PageHit("ACTION_SELECT", "pixel"),
                        handlers={"ACTION_SELECT": lambda rt, f, hit: STAY})  # fmt: skip
    for now in (0.0, 100.0, 200.0, 300.0):
        clock.now = now
        rt.step()  # 画面一直在变：有进展，不停


def test_interrupt_handled_tick_skips_classify():
    calls = []
    rt, _ = runtime([frame([T("キャンセル", 200, 1160)], RETIRE)], classify=lambda img: calls.append(1) or UNKNOWN)
    assert rt.step() is STAY and calls == [] and rt.raw_device.taps == [(200, 1160)]


def test_session_observes_with_page_source():
    obs = []
    session = type("S", (), {"observe": lambda self, **kw: obs.append(kw)})()
    rt, _ = runtime([frame()], classify=lambda img: PageHit("ACTION_SELECT", "pixel"), session=session)
    rt.step()
    assert obs[0]["scene"] == "ACTION_SELECT" and obs[0]["page_source"] == "pixel" and obs[0]["fields"] is False


# ---------------------------------------------------------------- 暂停检查点
def test_checkpoint_waits_for_resume():
    rt, _ = runtime([frame()])
    rt.flow.request_pause()
    passed = threading.Event()
    th = threading.Thread(target=lambda: (rt.checkpoint(), passed.set()))
    th.start()
    assert not passed.wait(0.2)  # 暂停中：卡在检查点
    rt.flow.request_resume()
    assert passed.wait(2)
    th.join()


# ---------------------------------------------------------------- 不依赖 KAA
def test_runtime_imports_no_kaa():
    code = "import sys, hiro.runtime, hiro.runtime.interrupts; print([m for m in sys.modules if m.split('.')[0] in ('kaa', 'kotonebot')])"
    env = {k: v for k, v in os.environ.items() if k != "HIRO_KAA_GAME_DATA"}  # 设了它 hiro.vision 会给 KAA 指主数据目录（KAA 还在时要）
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env).stdout.strip()
    assert out == "[]"
