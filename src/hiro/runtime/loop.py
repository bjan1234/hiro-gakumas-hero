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

import logging
from hiro.loop import pause_flag
from hiro.loop.errors import ResumeBlocked
from hiro.runtime import interrupts as _interrupts
from hiro.runtime.frame import Frame, Screen
from hiro.runtime.guard import GuardedDevice

logger = logging.getLogger(__name__)

TICK = 0.3  # wait_until 两拍之间至少隔这么久
UNKNOWN_ALERT_S = 30.0  # 认不出的画面连续这么久起报警
UNKNOWN_STOP_S = 180.0  # 连续这么久停机（同 repeat_guard.STALL_S）


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
class PageHit:
    """判页结果。source 沿用 PageObs.source 的取值（quick / interval_title / exam_ocr / pixel / … / none）。"""

    name: str
    source: str | None = None
    fields: dict | None = None
    confidence: float = 1.0


UNKNOWN = PageHit("unknown", "none")


@dataclass(frozen=True)
class Outcome:
    kind: str  # done（已离开本页）/ stay（还在本页，下一拍再来）/ stop（停机）
    reason: str = ""


DONE, STAY = Outcome("done"), Outcome("stay")


def stop(reason: str) -> Outcome:
    return Outcome("stop", reason)


Handler = Callable[["Runtime", Frame, PageHit], Outcome]


@dataclass
class Runtime:
    """一局的运行环境。device 是原始设备（hiro.devices），对外给的 self.device 是带拦截的。"""

    raw_device: object
    classify: Callable[[object], PageHit]  # img → PageHit，纯函数
    handlers: dict[str, Handler] = field(default_factory=dict)
    advance: Callable[["Runtime", Frame, PageHit], bool] = lambda rt, f, hit: False  # 没有处理器的页：安全推进，点了返回 True
    session: object | None = None  # hiro.loop.session.Session；有就每拍观测
    interrupts: tuple = _interrupts.DEFAULT
    clock: Callable[[], float] = pause_flag.active_clock
    sleep: Callable[[float], None] = time.sleep
    flow: _Flow = field(default_factory=_Flow)

    def __post_init__(self) -> None:
        self.screen = Screen(self.raw_device, self.clock)
        self.device = GuardedDevice(self.raw_device, self.screen)
        self._unknown_since: float | None = None

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

    # ---------------------------------------------------------------- 主循环
    def step(self) -> Outcome:
        """主循环一拍。stop 时抛 ResumeBlocked。"""
        f, done = self.tick()
        if done is not None:
            return STAY
        hit = self.classify(f.img)
        if self.session is not None:
            self.session.observe(scene=hit.name, img=f.img, fields=hit.fields if hit.fields is not None else True,
                                 page_source=hit.source)  # fmt: skip
        handler = self.handlers.get(hit.name)
        if handler is not None:
            self._unknown_since = None
            out = handler(self, f, hit)
        else:
            out = DONE if self.advance(self, f, hit) else STAY
            self._watch_unknown(hit, f.t)
        if out.kind == "stop":
            raise ResumeBlocked(f"{hit.name}：{out.reason}")
        return out

    def _watch_unknown(self, hit: PageHit, now: float) -> None:
        if hit.name != UNKNOWN.name:
            self._unknown_since = None
            return
        if self._unknown_since is None:
            self._unknown_since = now
        stuck = now - self._unknown_since
        if stuck >= UNKNOWN_STOP_S:
            raise ResumeBlocked(f"画面连续 {stuck:.0f}s 认不出，停机")
        if stuck >= UNKNOWN_ALERT_S:
            logger.warning("画面已连续 %.0fs 认不出", stuck)

    def run(self, until: Callable[[], bool], *, max_steps: int | None = None) -> int:
        """跑到 until() 为真（或 max_steps 拍），返回跑了几拍。录屏暂停看守在这期间开着。"""
        watcher = pause_flag.Watcher(self.flow, session=self.session).start()
        n = 0
        try:
            while not until() and (max_steps is None or n < max_steps):
                self.step()
                n += 1
        finally:
            watcher.stop()
        return n
