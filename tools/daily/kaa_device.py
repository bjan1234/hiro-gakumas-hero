# 调用 KAA / kotonebot（kotones-auto-assistant，GPL-3.0）
"""日常任务 KAA 那条路（run_daily.py 不带 --own）用的 kotonebot 设备，720x1280 逻辑坐标。

原来是 src/hiro/device.py + hiro.kaa_env.kaa_backend*，2026-11-24 随 KAA 主循环删掉时挪到这里：
只剩 assignment / contest 两项还没迁到 hiro.daily，迁完连这个文件一起删。
后端按 HIRO_DEVICE 选：maatools（macOS + hguandl 分支 PlayCover，客户端在 hiro.devices.maatools）；
adb / mumu / leidian / dmm 交给 KAA 的设备工厂，配置按 HIRO_ADB / HIRO_SCREENSHOT / HIRO_EMULATOR_INSTANCE /
HIRO_MUMU_BACKGROUND 写。
"""

from __future__ import annotations

import logging
import os
import sys

from hiro.devices.maatools import MAATOOLS_PORT, MaaToolsImpl

logger = logging.getLogger(__name__)

# HIRO_DEVICE → (KAA lifecycle.type, 缺省截图方式)；截图方式的可选值以 kaa.config.validation 为准
KAA_BACKENDS = {
    "adb": ("custom", "adb"),
    "mumu": (
        "mumu12v5",
        "adb",
    ),  # Windows 上 nemu_ipc 的点击送不到 MuMu 6 的应用显示；要试 nemu_ipc 就显式写 HIRO_SCREENSHOT
    "leidian": ("leidian", "adb"),
    "dmm": ("dmm", "windows_background"),
}


def backend_name() -> str:
    name = (os.environ.get("HIRO_DEVICE") or "auto").strip().lower()
    if name == "auto":
        if sys.platform == "darwin":
            return "maatools"
        raise RuntimeError("这台机器不是 macOS，请设 HIRO_DEVICE：adb / mumu / leidian / dmm")
    if name != "maatools" and name not in KAA_BACKENDS:
        raise ValueError(f"HIRO_DEVICE={name!r} 不认识；可选：auto、maatools、{'、'.join(KAA_BACKENDS)}")
    return name


def kaa_backend(name: str):
    """KAA 的 BackendConfig（name 是 KAA_BACKENDS 里的键）。"""
    from kaa.config.base_config import (
        AutoConnection,
        BackendConfig,
        CustomDevice,
        DmmDevice,
        LeidianDevice,
        MuMu12V5Device,
        TcpConnection,
    )  # fmt: skip

    kind, shot = KAA_BACKENDS[name]
    shot = os.environ.get("HIRO_SCREENSHOT") or shot
    instance = os.environ.get("HIRO_EMULATOR_INSTANCE")
    lifecycle = {
        "custom": lambda: CustomDevice(type="custom"),
        # KAA 不设实例 ID 会报错，单开就是 0；后台模式按游戏包名截它所在的显示（MuMu 6 把应用放在单独的显示里）
        "mumu12v5": lambda: MuMu12V5Device(type="mumu12v5", instance_id=instance or "0",
                                           mumu_background_mode=os.environ.get("HIRO_MUMU_BACKGROUND") != "0"),
        "leidian": lambda: LeidianDevice(type="leidian", instance_id=instance),
        "dmm": lambda: DmmDevice(type="dmm"),
    }[kind]()  # fmt: skip
    if adb := os.environ.get("HIRO_ADB"):
        host, _, port = adb.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError(f"HIRO_ADB 要写成 ip:port，例如 127.0.0.1:16384，收到 {adb!r}")
        connection = TcpConnection(type="tcp", ip=host, port=int(port))
    elif kind == "mumu12v5":
        connection = AutoConnection(type="auto")
    else:
        connection = TcpConnection(type="tcp")  # 127.0.0.1:5555；dmm 不用 adb
    return BackendConfig(lifecycle=lifecycle, connection=connection, screenshot_impl=shot)


def _keep_swipe_duration(device) -> None:
    """模拟器后端的滑动保留时长：KotoneBot 的 AdbImpl.swipe 会丢掉 duration，列表带惯性多滚。
    有 MuMu 的 nemu_ipc 触摸就交给它，否则用 adb 的「input touchscreen swipe … 毫秒」。"""
    parts = [getattr(device, a, None) for a in ("_touch", "_multitouch", "commands")]
    nemu = next((c for c in parts if type(c).__name__ == "NemuIpcImpl"), None)
    adb = next((c for c in parts if type(c).__name__ == "AdbImpl"), None)
    if nemu is None and adb is None:
        return
    plain = device.swipe

    def swipe(x1: int, y1: int, x2: int, y2: int, duration: float | None = None, **kw) -> None:
        if not duration:
            return plain(x1, y1, x2, y2, duration, **kw)
        (a1, b1), (a2, b2) = device.scaler.logic_to_physical((x1, y1)), device.scaler.logic_to_physical((x2, y2))
        a1, b1, a2, b2 = int(a1), int(b1), int(a2), int(b2)
        if nemu is not None:
            nemu.swipe(a1, b1, a2, b2, duration)
        else:
            adb.adb.shell(f"input touchscreen swipe {a1} {b1} {a2} {b2} {max(1, round(duration * 1000))}")

    device.swipe = swipe


def connect(config):
    """按 HIRO_DEVICE 建并启动 kotonebot 设备。config 是已 kaa_init 的 KaaConfig（KAA 后端写进它的 backend）。"""
    from kotonebot.client.scaler import PortraitGameScaler
    from kotonebot.config.config import conf
    from kotonebot.primitives.geometry import Size

    name = backend_name()
    conf().device.default_scaler_factory = lambda: PortraitGameScaler()
    conf().device.default_logic_resolution = Size(720, 1280)
    if name in KAA_BACKENDS:
        from kaa.main.kaa import KaaDeviceFactory

        config.backend = kaa_backend(name)
        device = KaaDeviceFactory().create_device_for_config(config)
        _keep_swipe_duration(device)
    else:
        from kotonebot.client.device import MacOSDevice

        device = MacOSDevice()
        maatools = MaaToolsImpl(device)
        device.setup(screenshot=maatools, touch=maatools)
    logger.info("设备后端：%s", name)
    try:
        device.start()
    except Exception as e:  # kotonebot 把连不上包成它自己的 DeviceConnectRefusedError
        if name != "maatools":
            raise
        raise RuntimeError(
            f"连不上 MaaTools（127.0.0.1:{MAATOOLS_PORT}）：要 hguandl 分支 PlayCover 并在游戏设置里打开 maaTools（{e}）"
        ) from e
    device.screenshot()  # 缩放器要靠首张截图确定物理分辨率，之后才能换算点击坐标
    return device
