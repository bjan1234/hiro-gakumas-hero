"""危险点击拦截：所有点击都经过这里，处理器拿到的设备就是 GuardedDevice，绕不过去。

规则（去 KAA 设计稿 §2.3 第 2 条、§3.4）：
1. 当前画面开着危险弹窗（リタイア 确认、培育数据破棄 / 别的端末进行中「開始する」，hiro.vision.pages.read_dialog 的 danger）：
   只放行点在「キャンセル / 閉じる」上的点击，其余一律拦下。
2. 点的位置落在含 ジュエル / 購入 / 課金 / 有償 / 破棄 / リタイア 的文字上：拦下（不管有没有弹窗）。
   培育中 ≡ 菜单、「プロデュース再開」框上也有「リタイア」字样，只要不点在它上面就不拦。
   （「購入」在培育里只会是ジュエル / 金币购买；日常任务的金币商店以后走 runtime 时要单独放行。）
拦下就抛 DangerBlocked（ResumeBlocked：停机交给人，不重试），画面留给人看。

代价：判弹窗先看像素（约 20 ms），有弹窗才读标题和正文；「点在什么字上」只 OCR 点击点周围 TAP_ROI 那一小块，不做整帧 OCR。
判断用的帧比 FRESH_S 旧（或还没截过图）时先重截一张：处理器截完图等了一会儿才点，期间弹出的危险框也看得见。
"""

from __future__ import annotations

from hiro.loop.errors import ResumeBlocked
from hiro.runtime.frame import Frame, Screen
from hiro.vision.ocr import screen_texts

HARD_WORDS = ("ジュエル", "購入", "課金", "有償", "破棄", "リタイア")
SAFE_ON_DANGER = ("キャンセル", "閉じる")
TAP_ROI = (160, 40)  # 点击点左右 / 上下各看这么远（320×80 的一块，够读一个按钮）
FRESH_S = 0.5
PAD = 6  # 文字框外扩这么多像素也算点在字上


class DangerBlocked(ResumeBlocked):
    """要点的地方危险（见模块说明）：停机，不点。"""


def word_at(frame: Frame, x: int, y: int) -> str | None:
    """(x, y) 落在哪段文字上：只 OCR 点击点周围一小块。落在空白处 None。"""
    h, w = frame.img.shape[:2]
    dx, dy = TAP_ROI
    x1, y1, x2, y2 = max(0, x - dx), max(0, y - dy), min(w, x + dx), min(h, y + dy)
    if x2 <= x1 or y2 <= y1:
        return None
    for t in screen_texts(frame.img, (x1, y1, x2 - x1, y2 - y1)):
        if t.rect.x1 - PAD <= x <= t.rect.x2 + PAD and t.rect.y1 - PAD <= y <= t.rect.y2 + PAD:
            return t.text
    return None


def check_tap(screen: Screen, x: int, y: int) -> None:
    """(x, y) 能不能点；不能就抛 DangerBlocked。"""
    f = screen.frame
    if f is None or screen.clock() - f.t > FRESH_S:
        f = screen.shot()
    word = word_at(f, x, y)
    if f.has_dialog and (d := f.dialog) is not None and d["danger"] and not (word and any(s in word for s in SAFE_ON_DANGER)):
        raise DangerBlocked(f"危险弹窗「{d['title']}」开着，只能点キャンセル：拦下 ({x}, {y}) {word or '（空白处）'}")
    if word and (hit := next((w for w in HARD_WORDS if w in word), None)):
        raise DangerBlocked(f"要点的「{word}」含「{hit}」：拦下 ({x}, {y})")


class GuardedDevice:
    """hiro.devices 的设备 + 点击前检查。点击类方法（tap、real_tap）都过 check_tap；
    其余只转发白名单里的（截图、滑动、连接、状态）；别的方法一律不给，免得新加的点击方法绕过检查。"""

    PASS = frozenset({"screenshot", "swipe", "alive", "orientation", "close", "connect", "shell"})

    def __init__(self, device, screen: Screen):
        self._device, self._screen = device, screen
        self.name = device.name

    def tap(self, x: int, y: int) -> None:
        check_tap(self._screen, x, y)
        self._device.tap(x, y)

    def real_tap(self, x: int, y: int) -> None:
        """MaaToolsDevice 的真实鼠标点击（PlayCover 兜底）：同样过检查。"""
        check_tap(self._screen, x, y)
        self._device.real_tap(x, y)

    def __getattr__(self, name):
        if name in self.PASS:
            return getattr(self._device, name)
        raise AttributeError(f"GuardedDevice 不转发 {name!r}（点击类方法要先过危险词拦截）")
