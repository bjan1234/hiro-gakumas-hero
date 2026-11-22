"""考试没过线时把再挑戦交给人（用户 2026-11-21：方便排查是打牌的问题还是养成的问题）。

开关 HIRO_RETRY_HANDOFF=1（缺省关）。结算页出现「再挑戦」、程序本来要决定重不重打时，先停下：
- 发系统通知、写等人文件（同 hiro.loop.unread_story.wait_file）、DMM 版把窗口挪到屏幕正中；
- 你在游戏里自己决定：点「再挑戦」亲手打这一场，或者不打（点次へ / 结束）；
- 弄完删掉等人文件，程序从当时的画面接着走（你打的那一场程序不碰）；
- 删文件时画面还停在这张结算页（你什么都没做）：程序照自己的规则决定重不重打；
- HIRO_RETRY_HANDOFF_TIMEOUT_S 秒（缺省 1800）没人删文件：同上，照程序的规则走（不关游戏）。
等的时间按暂停计（pause_flag.hold），看门狗不算。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

POLL_S = 3.0


def enabled(env: dict | None = None) -> bool:
    return (env if env is not None else os.environ).get("HIRO_RETRY_HANDOFF", "0") == "1"


def timeout_s(env: dict | None = None) -> float:
    try:
        return max(60.0, float((env if env is not None else os.environ).get("HIRO_RETRY_HANDOFF_TIMEOUT_S") or 1800))
    except ValueError:
        return 1800.0


def wait(label: str, *, still_here: Callable[[], bool], sleep: Callable[[float], None] = time.sleep,
         clock: Callable[[], float] = time.monotonic, notifier: Callable[[str, str], None] | None = None,
         env: dict | None = None) -> str:  # fmt: skip
    """结算页上、要不要再挑戦之前调。返回 "user"（你处理过了：画面已经不是这张结算页）/ "auto"（交回程序决定）。
    still_here()：画面是不是还停在这张结算页。"""
    from hiro.loop import unread_story
    from hiro.loop.pause_flag import hold

    env = env if env is not None else os.environ
    notifier = notifier or unread_story.notify  # 通知 / 等人文件 / DMM 窗口居中 复用未读剧情那套
    path = unread_story.wait_file(env)
    unread_story._show_game(env)
    limit = timeout_s(env)
    msg = (f"{time.strftime('%Y-%m-%d %H:%M:%S')} {label} 没过线，再挑戦交给你。\n"
           f"在游戏里自己决定：点「再挑戦」亲手打，或者不打。弄完（打完这一场 / 点了次へ）删掉这个文件，程序接着走；"
           f"什么都不做直接删文件 = 交回程序按规则决定；{limit / 60:.0f} 分钟没人删也交回程序。\n")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(msg, encoding="utf-8")
    except OSError as e:
        logger.warning("写等人文件 %s 失败：%r", path, e)
    logger.warning("%s 没过线：再挑戦交给人（%s；删文件继续，%.0f 分钟没人管交回程序）", label, path, limit / 60)
    notifier("数字小广：考试没过线", f"{label} 再挑戦交给你：自己打或不打，弄完删掉 {path.name}。")
    with hold():
        start = clock()
        while path.exists() and clock() - start < limit:
            sleep(POLL_S)
    if path.exists():
        path.unlink(missing_ok=True)
        logger.warning("%s 再挑戦等了 %.0f 分钟没人管，交回程序按规则决定", label, limit / 60)
        return "auto"
    try:
        here = still_here()
    except Exception as e:  # noqa: BLE001
        logger.warning("%s 再挑戦交接：读画面失败（%r），交回程序", label, e)
        here = True
    if here:
        logger.warning("%s 等人文件删了、画面还在结算页：交回程序按规则决定再挑戦", label)
        return "auto"
    logger.warning("%s 再挑戦你处理过了（画面已离开结算页），程序从当前画面接着走", label)
    return "user"
