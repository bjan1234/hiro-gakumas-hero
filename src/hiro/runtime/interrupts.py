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

# 维护进行中 / 别处登录被踢：用户 11-14 定直接停机，不重试、不等待。宁窄勿宽：登录后的「メンテナンスのお知らせ」（预告）
# 不能停，所以只认进行中的说法，或者标题就是「メンテナンス」的弹窗。还没有实机样本，碰到新说法再补（配实机帧当用例）。
STOP_WORDS = ("メンテナンス中", "メンテナンスを実施", "他の端末でログイン", "別の端末でログイン")


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
    title = (frame.dialog or {}).get("title") or ""
    hit = next((t.text for t in frame.texts if any(w in t.text for w in STOP_WORDS)), None)
    if hit is None and title.startswith("メンテナンス") and "お知らせ" not in title:
        hit = title
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


def customize_confirm(frame, rt) -> str | None:
    """P 道具定制三选一选完、点了「受け取る」后游戏弹的「カスタマイズ確認」（「以下のPアイテムにカスタマイズを実行します」）：点右下「決定」。
    选哪个已经由 SELECT_PITEM 的决策定了，这里只是确认（旧主循环由 KAA 自动确认；框上勾了「次回以降表示しない」就不再弹）。
    只认 P 道具定制（正文带「Pアイテム」），特別指導的「カスタマイズ実行確認」由它自己的执行器处理。读不到「決定」停机。"""
    if not frame.has_dialog or (d := frame.dialog) is None or d["kind"] != "customize_confirm":
        return None
    if not any("Pアイテム" in t.text for t in frame.texts):
        return None
    btn = next((t for t in frame.texts if t.text.strip() == "決定" and t.rect.center.x > 360 and t.rect.center.y > 1000), None)
    if btn is None:
        raise ResumeBlocked(f"P 道具定制确认框「{d['title']}」：没读到「決定」，不点，停机")
    rt.device.tap(*btn.rect.center)
    return f"P 道具定制确认「{d['title']}」：点「決定」"


# 教程框（新账号 / 新赛季第一次进 H.I.F 弹，「H.I.F開幕!」「3回の選抜試験を突破しよう」「スター性を獲得しよう」…）：
# 白底大卡片（x 27–693）+ 卡片下面一排页码点（当前页是橙色菱形，y≈1068）+ 底部正中只有一个按钮「次へ」/「閉じる」（y≈1160）。
# 没有橙黄标题条，走不到 has_dialog：先看像素（左右两条白边、页码点那一带白底里有少量橙色），对上了才 OCR 底部按钮。
TUTORIAL_EDGE_WHITE = 0.98  # 卡片左右白边（x 32–60 / 662–688，y 160–1100）白色比例：教程框 0.995–1.0；声音设置页 0.976、其他全屏页更低
TUTORIAL_DOT_ORANGE = (30, 200)  # 页码点那一带（y 1040–1100）的橙色像素：教程框 81–84；声音设置页的橙色滑条 379
TUTORIAL_BAND_WHITE = 0.97  # 同一带的白色比例：教程框 0.993；声音设置页 0.929
TUTORIAL_BUTTONS = ("次へ", "閉じる")


def _tutorial_card(img) -> bool:
    import cv2
    import numpy as np

    if img is None or img.shape[:2] != (1280, 720):
        return False
    hsv = cv2.cvtColor(img[150:1110], cv2.COLOR_BGR2HSV)

    def white(x1, x2, y1, y2):
        b = hsv[y1 - 150 : y2 - 150, x1:x2]
        return float(((b[..., 1] < 25) & (b[..., 2] > 235)).mean())

    if white(32, 60, 160, 1100) < TUTORIAL_EDGE_WHITE or white(662, 688, 160, 1100) < TUTORIAL_EDGE_WHITE:
        return False
    band = hsv[1040 - 150 : 1100 - 150, 70:650]
    orange = int(np.count_nonzero((band[..., 0] >= 5) & (band[..., 0] <= 22) & (band[..., 1] > 120) & (band[..., 2] > 200)))
    return TUTORIAL_DOT_ORANGE[0] <= orange <= TUTORIAL_DOT_ORANGE[1] and white(70, 650, 1030, 1100) >= TUTORIAL_BAND_WHITE


def tutorial(frame, rt) -> str | None:
    """教程框：点底部唯一的按钮（次へ / 閉じる）。底部那一带读到的不是正好一个、或者不是这两个字，不点（交给判页 / 看门狗）。"""
    import re

    if not _tutorial_card(frame.img):
        return None
    # 按钮左边的「→」「×」图标会被读成单独的一个框：只数带假名 / 汉字的
    bottom = [(w, t) for t in frame.texts if 1120 <= t.rect.center.y <= 1200 and (w := re.sub(r"[^\u3040-\u30ff\u4e00-\u9fff]", "", t.text))]
    if len(bottom) != 1 or bottom[0][0] not in TUTORIAL_BUTTONS:
        return None
    word, btn = bottom[0]
    rt.device.tap(*btn.rect.center)
    return f"教程框：点「{word}」"


Interrupt = Callable[[object, object], "str | None"]
DEFAULT: tuple[Interrupt, ...] = (red_line, comm, stop_notice, date_changed, settings, customize_confirm, tutorial)


def check(frame, rt, interrupts: tuple[Interrupt, ...] = DEFAULT) -> str | None:
    """按顺序过中断，第一个处理了的返回它的说明；都不是返回 None。"""
    for fn in interrupts:
        if (done := fn(frame, rt)) is not None:
            return done
    return None
