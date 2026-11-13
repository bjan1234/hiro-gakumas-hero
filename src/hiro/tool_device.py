"""工具脚本用的设备：hiro.devices 的统一接口 + hiro.runtime 的危险点击拦截，不经 kotonebot / KAA。

    from hiro.tool_device import open_tool_device
    d = open_tool_device()            # 按 HIRO_DEVICE 连设备
    img = d.screenshot()              # 720x1280 BGR；同时记成「最近一帧」，点击前的拦截看它
    d.tap(360, 640)                   # 点在 ジュエル / 購入 / 課金 / 有償 / 破棄 / リタイア 上、或危险弹窗开着时点别处：抛 DangerBlocked
    d.swipe(360, 900, 360, 450, duration=0.8, hold=0.3)

截图都走 Screen.shot()，所以拦截看到的是工具自己刚截的那一帧；那一帧太旧（或还没截过）时，拦截（hiro.runtime.guard.check_tap）
自己会先补拍一张再判断。
只读的工具也用它：读页面时点的翻页 / キャンセル 不会碰到上面那些词，真碰到了说明页面不是预期的那一页，停下比点下去好。
"""

from __future__ import annotations

import time

from hiro.devices import open_device
from hiro.runtime.frame import Screen
from hiro.runtime.guard import GuardedDevice

LIST_HOLD_S = 0.3  # 滚动列表时拖到终点停这么久再松手（不带惯性），读列表靠行重叠拼接的工具都用它


class ToolDevice(GuardedDevice):
    """GuardedDevice，截图顺带更新拦截用的最近一帧。"""

    def screenshot(self):
        return self._screen.shot().img


def open_tool_device(name: str | None = None, *, clock=time.monotonic) -> ToolDevice:
    """建设备、连接，包成 ToolDevice。name 缺省读 HIRO_DEVICE（见 hiro.devices.open_device）。"""
    dev = open_device(name)
    dev.connect()
    return ToolDevice(dev, Screen(dev, clock))
