"""选行动页的提交（去 KAA 第 5/6 步，替换 KAA ActionSelectContext.commit 和我们打在它上面的 kaa_patches.action_commit）。

- 休息：一直点「休む」直到出现休息确认框，再一直点确认框里的按钮直到它消失（同 KAA）。
- 其余：按钮点 3 下（间隔 0.3 秒；KAA 原版之后还固定睡 2 秒，action_commit 早就去掉了），再等按钮模板消失（KAA wait_disappear，10 秒）。
KAA 的两个休息循环没有超时，这里各给 10 秒，超时抛 TimeoutError（HifCore._act 按「点了没反应」处理）。
"""

from __future__ import annotations

import logging
import time

from hiro.devices.active import device, sleep
from hiro.vision.action_buttons import ActionButton
from hiro.vision.ui_templates import tpl

logger = logging.getLogger(__name__)

DISAPPEAR_TIMEOUT = 10.0
REST_TIMEOUT = 10.0


def action_commit(button: ActionButton, *, clock=time.monotonic) -> None:
    if button.option == "rest":
        _rest(clock)
        return
    for _ in range(3):
        device.click(*button.rect.center)
        sleep(0.3)
    logger.info("选行动：点了 %s", button.label)
    end = clock() + DISAPPEAR_TIMEOUT
    while tpl(button.template).exists(device.screenshot()):
        if clock() >= end:
            raise TimeoutError(f"点了 {button.label} {DISAPPEAR_TIMEOUT:.0f}s 按钮还在")
        sleep(0.2)


def _rest(clock) -> None:
    end = clock() + REST_TIMEOUT
    while True:  # 点「休む」直到确认框出来
        img = device.screenshot()
        if tpl("InProduce.RestConfirmBtn").exists(img):
            break
        if (m := tpl("InProduce.Rest").find(img)) is not None:
            device.click(*m.center)
        if clock() >= end:
            raise TimeoutError(f"点「休む」{REST_TIMEOUT:.0f}s 确认框没出来")
        sleep(0.5)
    end = clock() + REST_TIMEOUT
    while (m := tpl("InProduce.RestConfirmBtn").find(device.screenshot())) is not None:  # 点确认直到框消失
        if clock() >= end:
            raise TimeoutError(f"休息确认框 {REST_TIMEOUT:.0f}s 没关掉")
        device.click(*m.center)
        sleep(0.5)
    logger.info("选行动：休息")
