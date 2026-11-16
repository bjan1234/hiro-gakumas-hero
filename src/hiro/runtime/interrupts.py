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


TAP_GAP_S = 1.5  # 同一个中断点了同一个框之后，这么久之内框还在就不再点（框淡出要时间：カスタマイズ確認 0.5 秒点了两次「決定」，h10 11-15）


def _recently(rt, key: str) -> bool:
    last = getattr(rt, "_interrupt_tap", None)
    now = rt.clock() if callable(getattr(rt, "clock", None)) else 0.0
    return last is not None and last[0] == key and now - last[1] < TAP_GAP_S


def _tapped(rt, key: str) -> None:
    rt._interrupt_tap = (key, rt.clock() if callable(getattr(rt, "clock", None)) else 0.0)


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


COMM_RETRY_MAX = 10  # 通信エラー 连着点リトライ 这么多次还在就停机报警（11-17 Mac：10 分钟点了 162 次，没上限）
COMM_RETRY_MAX_S = 300.0  # 或者从第一次点起这么久还在
COMM_RESET_S = 60.0  # 这么久没再见到通信エラー 才重新计数（两次之间是读取画面，不能每拍清零）


def _comm_frame(rt, f) -> str | None:
    try:
        return rt.session.trace.save_frame(rt.session.trace.next_seq(), f.img) if rt.session is not None else None
    except Exception:  # noqa: BLE001
        return None


def comm(frame, rt) -> str | None:
    """通信エラー：只点リトライ；只能回标题时点閉じる并抛 CommErrorToTitle（hiro.loop.comm_error）。
    点之前确认弹窗确实在：标题条读出来是通信エラー、リトライ 在标题条下面，重截一帧还在同一个位置（11-17：リトライ 的位置 (299,1019)
    在首页上靠近「プロデュース中」）。连着点 COMM_RETRY_MAX 次 / COMM_RETRY_MAX_S 秒还在：存帧、停机报警。"""
    if not frame.has_dialog:
        return None
    e = comm_error.comm_error(frame.boxes)
    if e is None:
        return None
    d = frame.dialog or {}
    if d.get("kind") != "comm_error" and not any(h in (d.get("title") or "") for h in comm_error.TITLE_HINTS):
        return None  # 画面上有「通信」字样，但最上层的弹窗标题不是通信エラー：不点
    if e["kind"] == "retry" and d.get("y") is not None and e["retry"][1] <= d["y"]:
        return None  # 「リトライ」不在这个弹窗里（在标题条上面）
    f2 = rt.screen.shot()  # 重截核对：弹窗还在、按钮没挪
    e2 = comm_error.comm_error(f2.boxes) if f2.has_dialog else None
    if e2 is None or e2["kind"] != e["kind"] or (e["retry"] and (e2["retry"] is None or abs(e2["retry"][1] - e["retry"][1]) > 20)):
        return "通信エラー：重截时弹窗不在了 / 变了，这一拍不点"
    if e2["kind"] == "retry":
        now = rt.clock() if callable(getattr(rt, "clock", None)) else 0.0
        st = getattr(rt, "_comm_retry", None)  # (第一次, 最近一次, 次数)
        if st is not None and now - st[1] > COMM_RESET_S:
            st = None
        n = (st[2] if st else 0) + 1
        first = st[0] if st else now
        if n > COMM_RETRY_MAX or now - first > COMM_RETRY_MAX_S:
            shot = _comm_frame(rt, f2)
            raise ResumeBlocked(f"通信エラー 点了 {n - 1} 次リトライ（{now - first:.0f}s）还在，停机（帧 {shot}）")
        rt._comm_retry = (first, now, n)
    r = comm_error.handle(f2.boxes, rt.device.tap, sleep=rt.sleep)
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
    """日期切换 / 数据更新（日本时间凌晨 5 点）：抛 DateChanged，run_hif 回首页从「プロデュース中」续跑。"""
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
    if _recently(rt, "customize_confirm"):
        return f"P 道具定制确认「{d['title']}」：刚点过「決定」，等框关"
    btn = next((t for t in frame.texts if t.text.strip() == "決定" and t.rect.center.x > 360 and t.rect.center.y > 1000), None)
    if btn is None:
        raise ResumeBlocked(f"P 道具定制确认框「{d['title']}」：没读到「決定」，不点，停机")
    rt.device.tap(*btn.rect.center)
    _tapped(rt, "customize_confirm")
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
    if _recently(rt, f"tutorial:{word}"):
        return f"教程框：刚点过「{word}」，等换页"
    rt.device.tap(*btn.rect.center)
    _tapped(rt, f"tutorial:{word}")
    return f"教程框：点「{word}」"


def reroll_confirm(frame, rt) -> str | None:
    """「スキルカード再抽選確認」开着（选卡处理器点了再抽選后进程停了、续跑时框已经在；或在页面之间撞上）：点「再抽選する」；
    框上有ジュエル等消耗字样点キャンセル，读不到キャンセル 停机。「次回以降表示しない」勾着也每次刷新都弹（协调 11-14）。"""
    from hiro.produce.ops import reroll_confirm_action

    if not frame.has_dialog or "再抽選確認" not in ((frame.dialog or {}).get("title") or ""):
        return None
    act = reroll_confirm_action(frame.texts)
    if act is None:
        return None
    kind, hit, cost = act
    if _recently(rt, "reroll_confirm"):
        return "再抽選确认框：刚点过，等框关"
    if kind == "cost":
        if hit is None:
            raise ResumeBlocked(f"再抽選确认框上有消耗字样「{cost}」，又没读到キャンセル：不点，停机")
        rt.device.tap(*hit.rect.center)
        _tapped(rt, "reroll_confirm")
        return f"再抽選确认框有消耗字样「{cost}」：点キャンセル"
    rt.device.tap(*hit.rect.center)
    _tapped(rt, "reroll_confirm")
    return f"再抽選确认框：点「{hit.text}」"


# 成就达成提示条（「手札の多さが武器 / 花海 咲季のPアイドルを合計5種類入手 ✓」）：白色圆角横条盖在画面顶部（y 36–150），
# 开局第 1 步的页头被它挡住认不出（Mac 账号 2 11-16）。几秒后自己消失：不点（点了可能跳到成就页），这一拍当「处理过」等它走。
# 判据：横条上下两段白（x 120–580，y 40–56 / 124–146 白色比例 ≥ 0.9）+ 右边蓝色对勾（x 590–665，y 60–130 蓝像素 ≥ 150）。
# fixtures + Mac 实机帧 699 张里只有两张成就帧命中（517 个蓝像素）。
TOAST_MAX_S = 20.0  # 一直在超过这么久就不再当中断（交回判页 / 看门狗，防真卡住时死等）


def _achievement_toast(img) -> bool:
    import cv2
    import numpy as np

    if img is None or img.shape[:2] != (1280, 720):
        return False
    hsv = cv2.cvtColor(img[:170], cv2.COLOR_BGR2HSV)

    def white(y1, y2):
        b = hsv[y1:y2, 120:580]
        return float(((b[..., 1] < 25) & (b[..., 2] > 235)).mean())

    if white(40, 56) < 0.9 or white(124, 146) < 0.9:
        return False
    chk = hsv[60:130, 590:665]
    return int(np.count_nonzero((chk[..., 0] >= 95) & (chk[..., 0] <= 118) & (chk[..., 1] >= 120) & (chk[..., 2] >= 180))) >= 150


def achievement_toast(frame, rt) -> str | None:
    """成就达成提示条盖住页头：不点，等它自己消失（连续 TOAST_MAX_S 秒还在就不再拦）。"""
    now = rt.clock() if callable(getattr(rt, "clock", None)) else 0.0
    if not _achievement_toast(frame.img):
        rt._toast_since = None
        return None
    since = getattr(rt, "_toast_since", None)
    if since is None:
        rt._toast_since = since = now
    if now - since >= TOAST_MAX_S:
        return None
    return "成就提示条盖住页头：等它消失"


Interrupt = Callable[[object, object], "str | None"]
DEFAULT: tuple[Interrupt, ...] = (red_line, comm, stop_notice, date_changed, settings, customize_confirm, tutorial, reroll_confirm,
                                   achievement_toast)


def check(frame, rt, interrupts: tuple[Interrupt, ...] = DEFAULT) -> str | None:
    """按顺序过中断，第一个处理了的返回它的说明；都不是返回 None。"""
    for fn in interrupts:
        if (done := fn(frame, rt)) is not None:
            return done
    return None
