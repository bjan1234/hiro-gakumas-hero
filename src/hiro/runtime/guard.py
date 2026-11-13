"""危险点击拦截：所有点击都经过这里，处理器拿到的设备就是 GuardedDevice，绕不过去。

规则（去 KAA 设计稿 §2.3 第 2 条、§3.4）：
1. 当前画面开着危险弹窗（リタイア 确认、培育数据破棄 / 别的端末进行中「開始する」，hiro.vision.pages.read_dialog 的 danger）：
   只放行点在「キャンセル / 閉じる」上的点击，其余一律拦下。
2. 点的位置落在含 ジュエル / 購入 / 課金 / 有償 / 破棄 / リタイア 的文字上：拦下（不管有没有弹窗）。
   培育中 ≡ 菜单、「プロデュース再開」框上也有「リタイア」字样，只要不点在它上面就不拦。
拦下就抛 DangerBlocked（ResumeBlocked：停机交给人，不重试），画面留给人看。
"""

from __future__ import annotations

from hiro.loop.errors import ResumeBlocked
from hiro.runtime.frame import Screen

HARD_WORDS = ("ジュエル", "購入", "課金", "有償", "破棄", "リタイア")
SAFE_ON_DANGER = ("キャンセル", "閉じる")


class DangerBlocked(ResumeBlocked):
    """要点的地方危险（见模块说明）：停机，不点。"""


def check_tap(screen: Screen, x: int, y: int) -> None:
    """按最近一帧判断 (x, y) 能不能点；不能就抛 DangerBlocked。还没截过图时放行（没有画面可判）。"""
    f = screen.frame
    if f is None:
        return
    word = None
    if f.has_dialog and (d := f.dialog) is not None and d["danger"]:
        word = f.text_at(x, y)
        if not word or not any(s in word for s in SAFE_ON_DANGER):
            raise DangerBlocked(f"危险弹窗「{d['title']}」开着，只能点キャンセル：拦下 ({x}, {y}) {word or '（空白处）'}")
    word = word if word is not None else f.text_at(x, y)
    if word and (hit := next((w for w in HARD_WORDS if w in word), None)):
        raise DangerBlocked(f"要点的「{word}」含「{hit}」：拦下 ({x}, {y})")


class GuardedDevice:
    """hiro.devices 的设备 + 点击前检查。swipe 不检查（只用于滚动列表）；其余方法原样转发。"""

    def __init__(self, device, screen: Screen):
        self._device, self._screen = device, screen
        self.name = device.name

    def tap(self, x: int, y: int) -> None:
        check_tap(self._screen, x, y)
        self._device.tap(x, y)

    def __getattr__(self, name):
        return getattr(self._device, name)
