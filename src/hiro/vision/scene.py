"""旧主循环的判页入口：对最近一次 kotonebot device.screenshot() 的画面分类。

判页本身已经是 hiro.vision.classify.classify_scene（纯函数、不依赖 KAA，和原来 KAA check_scene 那条链逐帧一致）；
这里只负责取 kotonebot 的截图、把结果换回旧的 SceneResult。新主循环（hiro.runtime）直接用 classify.classify。
"""

import time
from dataclasses import dataclass

from kotonebot.backend.context import device

from hiro.vision.classify import classify_scene

# 新判页给的名字 → 旧主循环认的名字（行为不变）：开局二选一 KAA 判页时双击第一项后报 IDLE；横屏没有单独的页面
_OLD_NAME = {"INITIAL_CHOICE": "IDLE", "LIVE": "unknown"}


@dataclass
class SceneResult:
    area: str  # produce / outside / unknown
    scene: str
    elapsed_ms: float


def classify_current() -> SceneResult:
    """对最近一次 device.screenshot() 的画面分类。"""
    start = time.perf_counter()
    hit = classify_scene(device.screenshot())
    name = _OLD_NAME.get(hit.name, hit.name)
    return SceneResult("unknown" if name == "unknown" else hit.area, name, (time.perf_counter() - start) * 1000)
