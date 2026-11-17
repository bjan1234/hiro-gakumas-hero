"""日程列表（ScheduleListView）采样探针：初 / N.I.A 第一次到选行动页时点开日程列表，存帧 + OCR 文字，再关掉（协调 11-17 ①）。

服务器开局就把整局日程下发了（UserProduceProgressSchedule，每周一条 StepTypes / RefreshStamina 等，逆向 10.2），游戏里能在选行动页
点开日程列表看到。现有样本里一帧都没有，入口按钮和版面都不知道：先采样，拿到帧再写读数（page_fields.schedule）。

开关 HIRO_SCHEDULE_PROBE=1（默认关）。做法：点选行动页左上的页头框（「中間まで / 1次まで N週」，ENTRY）→ 等画面变 → 存帧、记 OCR 文字 →
最多往下滑 SCROLLS 屏、每屏存帧 → 点「閉じる」/ × 关掉 → 确认回到选行动页（右上「審査基準」或 N.I.A 的「P手帳」）。点开后画面没变：
当作入口不对，什么也不做（记一笔）。关不回去：停机，不在未知页面上乱点。帧和文字写在 trace 目录的 schedule-probe/ 下。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

ENTRY = (112, 92)  # 选行动页左上页头框（初「中間まで 5週」框中心约 (112, 95)；N.I.A 同位置）
SCROLLS = 3
CHANGE_DIFF = 6.0  # 灰度缩略图平均差：点开后画面变了
CLOSE_WORDS = ("閉じる", "戻る")


def enabled() -> bool:
    return os.environ.get("HIRO_SCHEDULE_PROBE") == "1"


def _thumb(img) -> np.ndarray:
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (90, 160)).astype(np.float32)


def _changed(a, b) -> bool:
    return float(np.abs(_thumb(a) - _thumb(b)).mean()) >= CHANGE_DIFF


def _at_action_select(img) -> bool:
    from hiro.vision.classify import classify

    try:
        return classify(img).name == "ACTION_SELECT"
    except Exception:  # noqa: BLE001
        return False


def probe(out_dir: Path, *, shoot, click, swipe, sleep=None, note=None) -> dict:
    """点开日程列表、存帧、关掉。返回 {opened, frames, texts, closed}。关不回选行动页抛 ResumeBlocked。"""
    from hiro.loop.errors import ResumeBlocked
    from hiro.vision.ocr import screen_texts
    from hiro.vision.ui_templates import tpl

    if sleep is None:
        from hiro.devices.active import sleep  # 过运行时检查点（暂停旗标等），不用裸 time.sleep（test_exec_checkpoint）
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    before = shoot()
    cv2.imwrite(str(out_dir / "00-before.jpg"), before, [cv2.IMWRITE_JPEG_QUALITY, 95])
    click(*ENTRY)
    sleep(1.5)
    img = shoot()
    result = {"opened": _changed(before, img), "frames": [], "texts": [], "closed": None}
    if not result["opened"]:
        logger.info("日程列表探针：点 %s 后画面没变，入口不对，不再试", ENTRY)
        if note:
            note(f"日程列表探针：点页头 {ENTRY} 画面没变（入口不对），没采到")
        (out_dir / "probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        return result
    for k in range(SCROLLS + 1):
        name = f"{k + 1:02d}-list.jpg"
        cv2.imwrite(str(out_dir / name), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        result["frames"].append(name)
        result["texts"].append([(t.text, list(t.rect.center)) for t in screen_texts(img)])
        if k == SCROLLS:
            break
        swipe(360, 900, 360, 500, 0.5)
        sleep(1.0)
        nxt = shoot()
        if not _changed(img, nxt):
            break  # 到底了
        img = nxt
    for _ in range(4):  # 关掉：先找「閉じる」字样，再找 × 图标；都没有就停
        img = shoot()
        if _at_action_select(img):
            result["closed"] = True
            break
        btn = next((t for t in screen_texts(img) if t.text.replace(" ", "").strip() in CLOSE_WORDS), None)
        m = None if btn is not None else (tpl("Common.ButtonIconClose").find(img) or tpl("Common.ButtonClose").find(img))
        if btn is None and m is None:
            break
        click(*(btn.rect.center if btn is not None else m.rect.center))
        sleep(1.2)
    (out_dir / "probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if note:
        note(f"日程列表探针：采了 {len(result['frames'])} 屏，帧在 {out_dir}")
    if not result["closed"] and not _at_action_select(shoot()):
        raise ResumeBlocked(f"日程列表探针：点开后关不回选行动页（帧在 {out_dir}），停机")
    result["closed"] = True
    return result
