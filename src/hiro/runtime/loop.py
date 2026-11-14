"""新主循环的骨架（去 KAA 设计稿 §3.1、§3.3、§3.4）：暂停检查点、wait_until、页面处理器注册表、Runner。不 import KAA / kotonebot。

每一拍：暂停检查点 → 截图 → 中断层 → classify（纯函数，判页不点）→ Session 观测 → 页面处理器；没有处理器的页交给 advance。
处理器返回 done / stay / stop(原因)；stop 和停机类异常（ResumeBlocked 及其子类）一样，Runner 抛出去由调用方（run_hif）停机。
等待一律走 wait_until：每拍都过暂停检查点和中断层，都带超时，不会死等。计时用 pause_flag.active_clock（录屏暂停期间不走）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

import logging
from hiro.loop import pause_flag
from hiro.loop.errors import ResumeBlocked
from hiro.runtime import interrupts as _interrupts
from hiro.runtime.frame import Frame, Screen
from hiro.runtime.guard import GuardedDevice
from hiro.vision.classify import UNKNOWN, PageHit

logger = logging.getLogger(__name__)

TICK = 0.3  # wait_until 两拍之间至少隔这么久
UNKNOWN_ALERT_S = 30.0  # 认不出的画面连续这么久起报警
STALL_S = 180.0  # 页面没变、画面也没变（缩略图差 < repeat_guard.SCREEN_DIFF）这么久就停机；认不出的画面同样适用


class _Flow:
    """给 pause_flag.Watcher 的流控：旗标出现 → 置暂停，消失 → 解除；主线程在检查点等它解除。"""

    def __init__(self) -> None:
        self._go = threading.Event()
        self._go.set()

    def request_pause(self) -> None:
        self._go.clear()

    def request_resume(self) -> None:
        self._go.set()

    def wait(self) -> None:
        self._go.wait()




@dataclass(frozen=True)
class Outcome:
    kind: str  # done（已离开本页）/ stay（还在本页，下一拍再来）/ stop（停机）/ end（这一局打完了，run 正常结束）
    reason: str = ""


DONE, STAY = Outcome("done"), Outcome("stay")


def stop(reason: str) -> Outcome:
    return Outcome("stop", reason)


Handler = Callable[["Runtime", Frame, PageHit], Outcome]


@dataclass
class Runtime:
    """一局的运行环境。device 是原始设备（hiro.devices），对外给的 self.device 是带拦截的。"""

    raw_device: object
    classify: Callable[[object], PageHit]  # img → PageHit，纯函数（hiro.vision.classify.classify）
    handlers: dict[str, Handler] = field(default_factory=dict)
    advance: Callable[["Runtime", Frame, PageHit], bool] = lambda rt, f, hit: False  # 没有处理器的页：安全推进，点了返回 True
    session: object | None = None  # hiro.loop.session.Session；有就每拍观测
    interrupts: tuple = _interrupts.DEFAULT
    clock: Callable[[], float] = pause_flag.active_clock
    sleep: Callable[[float], None] = time.sleep
    flow: _Flow = field(default_factory=_Flow)
    dialog_words: tuple[str, ...] = ()  # 模式自带的弹窗危险词（GuardedDevice 第 3 条；偶像之路用 hiro.runtime.tower.DIALOG_WORDS）

    def __post_init__(self) -> None:
        self.screen = Screen(self.raw_device, self.clock)
        self.device = GuardedDevice(self.raw_device, self.screen, self.dialog_words)
        self._unknown_since: float | None = None
        self._base: tuple[str, object, float] | None = None  # 进展看门狗的基准：(页面, 缩略图, 时刻)

    # ---------------------------------------------------------------- 等待
    def checkpoint(self) -> None:
        """暂停检查点：录屏暂停旗标在（pause_flag.Watcher 置的）就等到恢复。"""
        self.flow.wait()

    def tick(self) -> tuple[Frame, str | None]:
        """一拍：检查点 → 截图 → 中断层。返回 (帧, 中断说明或 None)。"""
        self.checkpoint()
        f = self.screen.shot()
        done = _interrupts.check(f, self, self.interrupts)
        if done is not None:
            logger.info("中断：%s", done)
        return f, done

    def wait_until(self, pred: Callable[[Frame], bool], timeout: float, *, every: float = TICK) -> tuple[bool, Frame]:
        """每拍过检查点和中断层后看 pred(帧)；成立返回 (True, 帧)，超时返回 (False, 最后一帧)。中断处理过的那一拍不算 pred。"""
        t0 = self.clock()
        while True:
            f, done = self.tick()
            if done is None and pred(f):
                return True, f
            if self.clock() - t0 >= timeout:
                return False, f
            self.sleep(every)

    def drive(self, step: Callable[[Frame], object], timeout: float, what: str, *, every: float = TICK):
        """多步流程的一段：每拍过检查点和中断层后调 step(帧)（可以点），返回非 None 就结束并返回它；
        超时抛 ResumeBlocked（what 写进原因）。开局 / 续跑这类「看画面 → 点 → 等下一页」的步骤都用它。"""
        t0 = self.clock()
        while True:
            f, done = self.tick()
            if done is None and (r := step(f)) is not None:
                return r
            if self.clock() - t0 >= timeout:
                raise ResumeBlocked(f"{what}：{timeout:.0f}s 没完成")
            self.sleep(every)

    # ---------------------------------------------------------------- 主循环
    def step(self) -> Outcome:
        """主循环一拍。stop 时抛 ResumeBlocked。"""
        f, done = self.tick()
        if done is not None:
            return STAY
        hit = self.classify(f.img)
        self._watch_progress(hit, f)
        if self.session is not None:
            # 判页给了字段就带上；没给不在这里做完整字段提取（贵），由处理器自己观测
            self.session.observe(scene=hit.name, img=f.img, fields=hit.fields if hit.fields is not None else False,
                                 page_source=hit.source)  # fmt: skip
        handler = self.handlers.get(hit.name)
        out = handler(self, f, hit) if handler is not None else (DONE if self.advance(self, f, hit) else STAY)
        if out.kind == "stop":
            raise ResumeBlocked(f"{hit.name}：{out.reason}")
        return out

    def _watch_progress(self, hit: PageHit, f: Frame) -> None:
        """进展看门狗：页面没变、画面也没变 STALL_S 秒就停机（处理器一直 stay、没处理器的已知页、认不出的画面都管）。
        认不出的画面另外连续 UNKNOWN_ALERT_S 秒起报警、STALL_S 秒停机（不管画面变没变）。"""
        from hiro.loop.repeat_guard import SCREEN_DIFF, _thumb

        th = _thumb(f.img)
        if self._base is None or self._base[0] != hit.name or float(np.abs(th - self._base[1]).mean()) >= SCREEN_DIFF:
            self._base = (hit.name, th, f.t)
        elif (stuck := f.t - self._base[2]) >= STALL_S:
            raise ResumeBlocked(f"{hit.name} 页面和画面 {stuck:.0f}s 没变化，停机")
        if hit.name != UNKNOWN.name:
            self._unknown_since = None
        elif self._unknown_since is None:
            self._unknown_since = f.t
        elif (unknown := f.t - self._unknown_since) >= STALL_S:
            raise ResumeBlocked(f"画面连续 {unknown:.0f}s 认不出，停机")  # 画面一直在变（循环动画）也停
        elif unknown >= UNKNOWN_ALERT_S:
            logger.warning("画面已连续 %.0fs 认不出", unknown)

    def run(self, until: Callable[[], bool], *, max_steps: int | None = None) -> int:
        """跑到 until() 为真（或 max_steps 拍），返回跑了几拍。录屏暂停看守在这期间开着。"""
        watcher = pause_flag.Watcher(self.flow, session=self.session).start()
        n = 0
        try:
            while not until() and (max_steps is None or n < max_steps):
                n += 1
                if self.step().kind == "end":  # 处理器报这一局打完了（培育结束）
                    break
        finally:
            watcher.stop()
        return n
