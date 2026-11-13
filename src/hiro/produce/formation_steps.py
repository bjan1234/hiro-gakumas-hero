"""开局第 2 / 3 步的核对、自动编成、租借（不依赖 KAA）：编成方案和设备由调用方给。
旧主循环经 kaa_patches 的同名包装用（方案取 kaa_env.ACTIVE_PLAN、设备是 kotonebot）；新主循环（hiro.runtime.opening）直接用。"""

from __future__ import annotations

import logging
import os

from hiro.produce.formation_check import FormationMismatch

logger = logging.getLogger(__name__)


def check_support(img, plan: dict | None, set_no=None) -> None:
    """有开局编成方案时核对第 2 步的 5 格支援卡；对不上抛 FormationMismatch（不开局）。核对本身出错只记日志。"""
    if not plan:
        return
    from hiro.produce.formation_check import check_support_step2

    try:
        from hiro.vision.support_screens import read_support_formation

        problems, warnings = check_support_step2(read_support_formation(img), plan)
    except Exception as e:  # noqa: BLE001
        logger.warning("支援卡编成核对失败（不拦开局）：%s", e)
        return
    for w in warnings:
        logger.warning("支援卡编成核对：%s", w)
    if problems:
        logger.error("支援卡编成和方案对不上，不开局：%s", "；".join(problems))
        raise FormationMismatch("支援卡编成和方案对不上：" + "；".join(problems))
    logger.info("支援卡编成核对通过（编成 %s）", set_no)


def autofix_on(plan: dict | None) -> bool:
    """开局自动编成（produce.formation_writer）：HIRO_FORMATION_AUTOFIX=1 且有开局编成方案时才启用（默认关，执行步骤待实机验证）。"""
    return os.environ.get("HIRO_FORMATION_AUTOFIX") == "1" and bool(plan)


def autofix_support(dev, plan: dict | None) -> None:
    """第 2 步：编成和方案不一致的格子自动改（切到方案编成号之后）。dev：formation_writer.Device。失败抛 FormationMismatch。"""
    if not autofix_on(plan):
        return
    from hiro.produce.formation_writer import FormationWriteError, fix_support
    from hiro.vision.support_screens import read_support_formation, read_support_list

    try:
        done = fix_support(dev, plan, read_formation=read_support_formation, read_list=read_support_list)
    except FormationWriteError as e:
        logger.error("开局自动编成（支援卡）失败，不开局：%s", e)
        raise FormationMismatch(f"开局自动编成（支援卡）失败：{e}") from e
    if done:
        logger.info("开局自动编成（支援卡）：改了 %d 格 %s", len(done), done)


def rental_pick(plan: dict | None, attr: str | None, main_attr: str | None = None) -> bool:
    """租借格：有开局编成方案时按「加上这张后编成的价值」挑（support_select.rental_scorer，自己 5 张取方案的）；
    没有方案：主属性、等级最高（hiro.produce.rental）。设备用 rental 当前的（新主循环用 rental.use(dev) 换）。"""
    from hiro.produce import rental

    plan = plan or {}
    own = [{"support_card_id": o["support_card_id"], "level": o.get("level")} for o in (plan.get("support") or {}).get("own") or []]
    scorer = None
    if own:
        from hiro.brain.support_select import rental_scorer

        scorer = rental_scorer(own, attr or main_attr, (plan.get("idol") or {}).get("plan"))
    return rental.pick_rental(attr=attr or rental.WANT_ATTR, scorer=scorer)
