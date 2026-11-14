"""新主循环里不带弹窗标题条的场景（设计稿 §2.2、§3.4 的「非弹窗中断」）：剧情逐句播放点 SKIP、横屏 LIVE 曲目页点开始、
重新登录后的一次性设置框。判据和点法照搬旧主循环 hiro.loop.controller（_skip_commu、_live_tick、_first_run_settings），
不依赖 KAA。都只点 OCR 认出来的字 / 固定的安全位置，点之前重新截图核对。

    handled = commu_skip(rt, frame) or live_start(rt, frame) or first_run_settings(rt, frame)
"""

from __future__ import annotations

import logging

from hiro.vision.ocr import screen_texts

logger = logging.getLogger(__name__)

LIVE_START_TEXT = "TAPTOSTART"
LIVE_INFO_TEXTS = ("作詞", "作曲", "編曲")
# 一次性设置框（标题, 要选的项, 确认按钮）：q13 重新登录后「サポートイベント設定」；q14 剧情点 SKIP 后「スキップ確認」
FIRST_RUN_SETTINGS = (("サポートイベント設定", "強化済みで獲得する", "決定"), ("スキップ確認", None, "決定"))


def live_start_tap(img, texts) -> tuple[int, int] | None:
    """横屏曲目页：认到「TAP TO START」点它；只认到曲目信息（作詞 / 作曲 / 編曲）点下方中间；其余 None。texts 是 ocr.Text 列表。"""
    for t in texts:
        if LIVE_START_TEXT in t.text.replace(" ", "").upper():
            return t.rect.center
    if any(k in t.text for t in texts for k in LIVE_INFO_TEXTS):
        h, w = img.shape[:2]
        return w // 2, int(h * 0.85)
    return None


def live_start(rt, frame) -> bool:
    """横屏（LIVE）帧：曲目页就点开始；其余横屏帧不点（演出中）。返回是否点了。"""
    img = frame.img
    if img is None or img.shape[1] <= img.shape[0]:
        return False
    tap = live_start_tap(img, frame.texts)
    if tap is None:
        return False
    logger.info("横屏 LIVE 曲目页：点 %s 开始演出", tap)
    rt.device.tap(*tap)
    return True


def commu_skip(rt, frame) -> bool:
    """培育剧情逐句播放（底栏有「早送り」+ ログ / AUTO / SKIP）：点认出来的 SKIP（左下、y > 1120）。点之前重新截图核对。"""
    texts = [t.text for t in frame.texts]
    if not any("早送" in t for t in texts) or not any("ログ" in t or "AUT" in t.upper() or "SKI" in t.upper() for t in texts):
        return False
    fresh = screen_texts(rt.screen.shot().img)
    if not any("早送" in b.text for b in fresh):
        return False
    btn = next((b for b in fresh if "SKI" in b.text.upper() and b.rect.center.y > 1120 and b.rect.center.x < 360), None)
    if btn is None:
        return False
    rt.device.tap(*btn.rect.center)
    logger.info("培育剧情：点 SKIP")
    return True


def first_run_settings(rt, frame) -> bool:
    """重新登录后游戏重置本地设置弹的一次性设置框：选推荐项（有的话）→ 点「決定」。"""
    from hiro.loop.skip_settings import is_ok_text

    texts = [t.text for t in frame.texts]
    hit = next((x for x in FIRST_RUN_SETTINGS if any(x[0] in t for t in texts)), None)
    if hit is None:
        return False
    boxes = screen_texts(rt.screen.shot().img)
    opt = next((b for b in boxes if hit[1] in b.text), None) if hit[1] else None
    if opt is not None:
        rt.device.tap(*opt.rect.center)
        rt.sleep(0.5)
    btn = next((b for b in boxes if b.text.strip() == hit[2] or (hit[2] == "決定" and is_ok_text(b.text))), None)
    if btn is None:
        return False
    rt.device.tap(*btn.rect.center)
    logger.warning("一次性设置「%s」：选「%s」→「%s」", hit[0], hit[1], hit[2])
    if rt.session is not None:
        rt.session.recover("dialog", f"一次性设置「{hit[0]}」选「{hit[1]}」")
    return True
