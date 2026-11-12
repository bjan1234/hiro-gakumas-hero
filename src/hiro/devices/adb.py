"""MuMu / 雷电 / 真机等安卓设备：直接调 adb 命令（不经 KAA），设备统一接口的实现。

    HIRO_ADB       adb 地址 ip:port（缺省 127.0.0.1:5555；MuMu 12 一般是 127.0.0.1:16384），也可以是 USB 序列号
    HIRO_ADB_PATH  adb 可执行文件（缺省 PATH 里的 adb）

- 截图：`adb exec-out screencap`（不压 PNG，原始 RGBA，比 `-p` 快），头 12 字节（宽、高、格式；安卓 12 起多 4 字节
  色彩空间），转成 BGR 再拉伸到逻辑分辨率。
- 点击：`input tap`。滑动：hold = 0 用 `input swipe … 毫秒`；hold > 0 用一条 shell 串起
  `input motionevent DOWN / MOVE / UP`（安卓 10 起），中间 `sleep hold`，到终点停住再松手，列表不带惯性。
  每条 input 命令要起一次进程（约 0.1 秒），所以 MOVE 只发几个点。
- 失败：设备掉线 / 找不到抛 DeviceGone（地址是 ip:port 时先 adb connect 重连一次再试）；格式不对、命令出错抛 DeviceUnavailable。
- alive()：`dumpsys window` 的 mCurrentFocus 是不是学マス的包名。
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess

import numpy as np

from .base import DeviceGone, DeviceUnavailable, LogicalScreen

PACKAGE = "com.bandainamcoent.idolmaster_gakuen"
DEFAULT_SERIAL = "127.0.0.1:5555"
GONE_WORDS = ("offline", "not found", "no devices", "unauthorized", "closed", "cannot connect", "failed to connect")


def focus_package(text: str) -> str | None:
    """「mCurrentFocus=Window{… u0 包名/Activity}」→ 包名（和 hiro.loop.game_app 同一写法）。"""
    m = re.search(r"mCurrentFocus=Window\{\S+ \S+ ([\w.]+)/", text or "")
    return m.group(1) if m else None


def parse_screencap(data: bytes) -> np.ndarray:
    """`screencap` 的原始输出 → BGR。头是 宽、高、格式（小端 uint32），安卓 12 起再多一个色彩空间。"""
    if len(data) < 12:
        raise DeviceUnavailable(f"screencap 输出太短（{len(data)} 字节）")
    w, h, fmt = struct.unpack("<III", data[:12])
    n = w * h * 4
    header = len(data) - n
    if w <= 0 or h <= 0 or header not in (12, 16) or fmt not in (1, 2):  # 1 RGBA_8888，2 RGBX_8888
        raise DeviceUnavailable(f"screencap 格式不认识：{w}x{h} 格式 {fmt}，头 {header} 字节")
    rgba = np.frombuffer(data, np.uint8, count=n, offset=header).reshape(h, w, 4)
    return np.ascontiguousarray(rgba[:, :, 2::-1])  # RGBA → BGR


class AdbDevice:
    """设备统一接口：安卓设备 / 模拟器（adb）。"""

    name = "adb"

    def __init__(self, serial: str | None = None, *, adb: str | None = None, package: str = PACKAGE, run=None):
        self.serial = serial or os.environ.get("HIRO_ADB") or DEFAULT_SERIAL
        self.adb = adb or os.environ.get("HIRO_ADB_PATH") or shutil.which("adb") or "adb"
        self.package = package
        self._run = run or self._subprocess  # 测试注入：run(argv, timeout) -> (returncode, stdout, stderr)
        self.screen = LogicalScreen()

    @property
    def orientation(self) -> str:
        return self.screen.orientation

    @staticmethod
    def _subprocess(argv, timeout):
        try:
            p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        except FileNotFoundError as e:
            raise DeviceUnavailable(f"找不到 adb：{argv[0]}（装 platform-tools，或设 HIRO_ADB_PATH）") from e
        except subprocess.TimeoutExpired as e:
            raise DeviceGone(f"adb 超时（{timeout}s）：{' '.join(argv[3:])}") from e
        return p.returncode, p.stdout, p.stderr

    def _networked(self) -> bool:
        return ":" in self.serial

    def _reconnect(self) -> None:
        if self._networked():
            self._run([self.adb, "connect", self.serial], 10)

    def _cmd(self, *args: str, timeout: float = 15.0) -> bytes:
        """跑一条 adb 命令；掉线时（地址是 ip:port）先 adb connect 一次再试。"""
        argv = [self.adb, "-s", self.serial, *args]
        for attempt in (0, 1):
            code, out, err = self._run(argv, timeout)
            if code == 0:
                return out
            text = (err or b"").decode("utf-8", "replace").strip().lower()
            gone = any(w in text for w in GONE_WORDS)
            if gone and attempt == 0 and self._networked():
                self._reconnect()
                continue
            if gone:
                raise DeviceGone(f"adb 设备 {self.serial} 不在了：{text[:200]}")
            raise DeviceUnavailable(f"adb {' '.join(args)[:80]} 失败（{code}）：{text[:200]}")
        raise DeviceGone(f"adb 设备 {self.serial} 重连后还是不行")

    # -- 连接
    def connect(self) -> None:
        if self._networked():
            code, out, err = self._run([self.adb, "connect", self.serial], 10)
            text = ((out or b"") + (err or b"")).decode("utf-8", "replace").lower()
            if code != 0 or ("connected" not in text and "already" not in text):
                raise DeviceUnavailable(f"adb connect {self.serial} 失败：{text.strip()[:200]}")
        code, out, err = self._run([self.adb, "-s", self.serial, "get-state"], 10)
        state = (out or b"").decode("utf-8", "replace").strip()
        if code != 0 or state != "device":
            raise DeviceUnavailable(
                f"adb 设备 {self.serial} 状态 {state or (err or b'').decode('utf-8', 'replace').strip()}"
            )
        self.screenshot()

    def close(self) -> None:
        pass  # 不 adb disconnect：别的程序可能也在用这台设备

    def shell(self, cmd: str, *, timeout: float = 15.0) -> str:
        """可选方法（不在统一接口里）：跑一条 adb shell 命令，返回输出文本。
        只给一个调用方用：hiro.loop.game_app 的 foreground(shell) / relaunch(shell)（查前台应用、闪退后拉起游戏）。"""
        return self._cmd("shell", cmd, timeout=timeout).decode("utf-8", "replace")

    def alive(self) -> bool:
        try:
            return focus_package(self.shell("dumpsys window | grep mCurrentFocus")) == self.package
        except (DeviceGone, DeviceUnavailable):
            return False

    # -- 截图 / 输入
    def screenshot(self) -> np.ndarray:
        return self.screen.frame(parse_screencap(self._cmd("exec-out", "screencap")))

    def _native(self, x: float, y: float) -> tuple[int, int]:
        if self.screen.native is None:
            self.screenshot()
        return self.screen.to_native(x, y)

    def tap(self, x: int, y: int) -> None:
        nx, ny = self._native(x, y)
        self._cmd("shell", f"input tap {nx} {ny}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, *, duration: float = 0.3, hold: float = 0.0) -> None:
        a1, b1 = self._native(x1, y1)
        a2, b2 = self.screen.to_native(x2, y2)
        duration = duration if duration and duration > 0 else 0.3
        if hold <= 0:
            self._cmd("shell", f"input swipe {a1} {b1} {a2} {b2} {max(1, round(duration * 1000))}")
            return
        steps = max(2, min(8, round(duration / 0.1)))
        parts = [f"input motionevent DOWN {a1} {b1}"]
        for i in range(1, steps + 1):
            t = i / steps
            parts.append(f"input motionevent MOVE {round(a1 + (a2 - a1) * t)} {round(b1 + (b2 - b1) * t)}")
        parts += [f"sleep {hold:.2f}", f"input motionevent MOVE {a2} {b2}", f"input motionevent UP {a2} {b2}"]
        self._cmd("shell", "; ".join(parts), timeout=15.0 + duration + hold)
