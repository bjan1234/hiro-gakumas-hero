"""中断层：每一拍判页之前先过一遍，按优先级（去 KAA 设计稿 §3.4）。

每个中断是 fn(frame, rt) -> str | None：处理了返回一句说明（主循环下一拍重截），不是它管的返回 None；
要停机就抛 ResumeBlocked（维护 / 被踢 / 破弃框 / 认不出按钮的红线框），要回首页续跑就抛 DateChanged / CommErrorToTitle。
rt 是 hiro.runtime.loop.Runtime：rt.device（带危险点击拦截）、rt.screen、rt.sleep。

这里的几种都是带橙黄标题条的弹窗，先看像素（frame.has_dialog，约 20 ms），有弹窗才整帧 OCR；没弹窗的画面这一层不花 OCR 时间。
剧情 SKIP、横屏 LIVE、引导框等非弹窗的中断由页面层接（新主循环迁移时补进来）。
"""

from __future__ import annotations

from collections.abc import Callable

from hiro.loop import comm_error, date_change, skip_settings
from hiro.loop.errors import ResumeBlocked
from hiro.vision.ocr import screen_texts

# 维护 / 被踢下线 / 别处登录：用户 11-14 定直接停机，不重试、不等待
STOP_WORDS = ("メンテナンス", "他の端末でログイン", "別の端末でログイン", "ログインされました", "アカウントが停止")


def _cancel(frame):
    return next((t for t in frame.texts if "キャンセル" in t.text), None)


def red_line(frame, rt) -> str | None:
    """危险弹窗（リタイア 确认、培育数据破棄）：只点キャンセル。破棄框点完停机（是否破弃由用户决定）；找不到キャンセル 停机。"""
    if not frame.has_dialog or (d := frame.dialog) is None or not d["danger"]:
        return None
    cancel = _cancel(frame)
    if cancel is None:
        raise ResumeBlocked(f"危险弹窗「{d['title']}」：没读到「キャンセル」，不点，停机")
    rt.device.tap(*cancel.rect.center)
    if d["kind"] == "data_discard":
        raise ResumeBlocked(f"游戏提示「{d['title']}」（其他端末有进行中的培育）：已点「キャンセル」，是否破弃由用户决定")
    return f"危险弹窗「{d['title']}」：点キャンセル"


def comm(frame, rt) -> str | None:
    """通信エラー：只点リトライ；只能回标题时点閉じる并抛 CommErrorToTitle（hiro.loop.comm_error）。"""
    if not frame.has_dialog:
        return None
    r = comm_error.handle(frame.boxes, rt.device.tap, sleep=rt.sleep)
    return f"通信エラー：{r}" if r else None


def stop_notice(frame, rt) -> str | None:
    """维护 / 被踢下线：停机，写清原因。"""
    if not frame.has_dialog:
        return None
    hit = next((t.text for t in frame.texts if any(w in t.text for w in STOP_WORDS)), None)
    if hit is not None:
        raise ResumeBlocked(f"游戏维护 / 被踢下线：「{hit}」，停机（不重试）")
    return None


def date_changed(frame, rt) -> str | None:
    """日期切换 / 数据更新（凌晨 4 点）：抛 DateChanged，run_hif 回首页从「プロデュース中」续跑。"""
    if frame.has_dialog and date_change.date_change_button(frame.boxes) is not None:
        raise date_change.DateChanged("日付変更")
    return None


def settings(frame, rt) -> str | None:
    """演出スキップ / 早送り / ボイス 等设置框：按用户设置勾选后点決定（hiro.loop.skip_settings）。"""
    if not frame.has_dialog:
        return None

    def ocr(img):
        return [(t.text, t.conf, tuple(t.rect)) for t in screen_texts(img)]

    r = skip_settings.handle(frame.boxes, shoot=lambda: rt.screen.shot().img, ocr=ocr, click=rt.device.tap, sleep=rt.sleep)
    return f"设置框 {r['kind']}" if r else None


Interrupt = Callable[[object, object], "str | None"]
DEFAULT: tuple[Interrupt, ...] = (red_line, comm, stop_notice, date_changed, settings)


def check(frame, rt, interrupts: tuple[Interrupt, ...] = DEFAULT) -> str | None:
    """按顺序过中断，第一个处理了的返回它的说明；都不是返回 None。"""
    for fn in interrupts:
        if (done := fn(frame, rt)) is not None:
            return done
    return None
