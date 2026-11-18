"""考试审查日程探测（HIRO_EXAM_SCHEDULE_PROBE=1 打开，默认关）。

任务 ①（实战局面读准）：UINet 要后面回合的属性顺序，画面路径现在是按配额猜的（3.4% 的选择因此不同）。
考试左上角「残りターン / ビジュアル 900%」那块在客户端布局里是 ExamAuditionBonusScheduleView，带可点的 BonusButtonArea
（x 9–222，y 40–140）；点开后的面板没有布局、也没有截图。这个探测只做一件事：每场考试第 1 回合出牌前点开一次，
存下打开后的帧和关闭过程，记耗时，回到考试画面再继续。读面板内容等拿到帧以后再写。

关闭：先找面板上的「閉じる」/ ✕，找不到再点同一块（可能是开关式）。两次都回不到考试画面就停机（ResumeBlocked），
不在考试里乱点。点的位置在左上角，离手牌（y≈860 以下）和出牌区很远。
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable

import numpy as np

import logging

from hiro.devices.active import sleep as _sleep

logger = logging.getLogger(__name__)

ENABLED_ENV = "HIRO_EXAM_SCHEDULE_PROBE"
BONUS_TAP = (115, 95)  # BonusButtonArea 中部（720x1280）
CLOSE_TEXTS = ("閉じる", "とじる", "✕", "×")
OPEN_WAIT = 3.0  # 点了以后等面板出来
CLOSE_WAIT = 3.0  # 每次关闭后等回到考试画面
CHANGED_MIN = 8.0  # 整屏灰度平均差：面板盖上来远大于这个；同一考试画面两帧（角色在动）实测 < 4


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV) == "1"


# 只在有审查日程面板的考试 / 试镜里点（协调 11-18 初 PRO 实机：课程第 1 回合前点开了「残りターン数」框的回合详情，
# 关闭判定只认 H.I.F 考试画面、认不出课程画面，停机）。课程（hajime-lesson-*）、偶像之路（tower*）不点。
EXAM_LABEL = re.compile(r"^(qualify-\d|r[12]|hajime-(mid1|final)|nia-(mid1|mid2|final))(#.*)?$")


def should_probe(label: str | None) -> bool:
    return bool(label) and EXAM_LABEL.match(str(label)) is not None


def back_in_exam(img) -> bool:
    """回到考试画面了：H.I.F 考试、初 / N.I.A 考试（判页用偶像之路那套判据认中，TOWER_EXAM）、课程 HUD 任一认得出就算。"""
    from hiro.vision.hajime import in_lesson
    from hiro.vision.hif import is_hif_exam
    from hiro.vision.tower import is_tower_exam

    try:
        return bool(is_hif_exam(img) or is_tower_exam(img) or in_lesson(img))
    except Exception:  # noqa: BLE001  识别异常当没回来，交给超时
        return False


def screen_diff(a: np.ndarray, b: np.ndarray) -> float:
    import cv2

    ga = cv2.cvtColor(cv2.resize(a, (180, 320)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    gb = cv2.cvtColor(cv2.resize(b, (180, 320)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.abs(ga - gb).mean())


def _wait(pred: Callable[[np.ndarray], bool], timeout: float, shoot, clock, sleep) -> tuple[bool, np.ndarray]:
    end = clock() + timeout
    img = shoot()
    while not pred(img):
        if clock() >= end:
            return False, img
        sleep(0.25)
        img = shoot()
    return True, img


def probe(
    before: np.ndarray,
    *,
    exam: str,
    shoot: Callable[[], np.ndarray],
    click: Callable[[int, int], None],
    ocr_boxes: Callable[[np.ndarray], list],
    is_exam: Callable[[np.ndarray], bool],
    log: Callable[..., object] | None = None,
    note: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = _sleep,
) -> dict:
    """点开审查日程、存帧、关掉，返回 {opened, closed, close_by, open_ms, close_ms, total_ms, texts}。关不掉抛 ResumeBlocked。"""
    from hiro.loop.errors import ResumeBlocked
    from hiro.produce.ops import find_text

    t0 = clock()
    click(*BONUS_TAP)
    opened, img = _wait(lambda im: screen_diff(before, im) >= CHANGED_MIN, OPEN_WAIT, shoot, clock, sleep)
    t_open = clock()
    sleep(0.5)  # 面板入场动画
    img = shoot()
    boxes = ocr_boxes(img)
    texts = [t for t, _, _ in boxes]
    if log:
        log("exam_schedule_probe_open", image=img, exam=exam, opened=opened, texts=texts)
    out = {"opened": opened, "closed": None, "close_by": None, "open_ms": round((t_open - t0) * 1000), "texts": texts}
    if not opened:
        # 画面没变：点了没反应（或者不是可点的区域）。没有面板要关，照常继续
        out.update(closed=True, close_by="not_opened", close_ms=0, total_ms=round((clock() - t0) * 1000))
        _report(out, exam, note)
        return out
    attempts = []
    hit = find_text(boxes, CLOSE_TEXTS)
    if hit is not None:
        attempts.append(("close_text", hit))
    attempts.append(("retap", BONUS_TAP))
    t_close = clock()
    back = False
    for how, xy in attempts:
        click(*xy)
        back, img = _wait(lambda im: is_exam(im) and screen_diff(before, im) < CHANGED_MIN, CLOSE_WAIT, shoot, clock, sleep)
        if back:
            out["close_by"] = how
            break
        boxes = ocr_boxes(img)
        if (h2 := find_text(boxes, CLOSE_TEXTS)) is not None and ("close_text", h2) not in attempts:
            attempts.append(("close_text", h2))
    out.update(closed=back, close_ms=round((clock() - t_close) * 1000), total_ms=round((clock() - t0) * 1000))
    if log:
        log("exam_schedule_probe_closed", image=img, exam=exam, closed=back, close_by=out["close_by"])
    _report(out, exam, note)
    if not back:
        raise ResumeBlocked(f"[{exam}] 审查日程探测：点开后 {len(attempts)} 种关法都没回到考试画面，停机（帧见 trace）")
    return out


def _report(out: dict, exam: str, note) -> None:
    msg = (f"[{exam}] 审查日程探测：{'打开了' if out['opened'] else '点了没打开'}，"
           f"{'关闭方式 ' + str(out['close_by']) if out['closed'] else '没关掉'}；打开 {out['open_ms']}ms，"
           f"关闭 {out.get('close_ms')}ms，共 {out.get('total_ms')}ms；面板文字 {out['texts'][:12]}")  # fmt: skip
    logger.info(msg)
    if note:
        note(msg)
