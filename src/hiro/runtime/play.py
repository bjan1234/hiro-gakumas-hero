"""新主循环跑一局（HIRO_RUNTIME=own，去 KAA 第 6 步接线）：设备（hiro.devices）→ Runtime（自有判页 + HifCore 处理器 + 中断层）
→ 开局 / 续跑（hiro.runtime.opening / finish）→ rt.run 到培育结束。不 import KAA / kotonebot。

run_hif 在 HIRO_RUNTIME=own 时调 run(args, session)；其余参数、trace、报告、退出码和旧主循环一样。
没有处理器的页面交给 advance：剧情 SKIP → 横屏 LIVE 曲目页 → 一次性设置框 → 安全空白连点（hiro.loop.advance.burst，同旧主循环）。
日切换（DateChanged）按旧主循环的做法回首页再续跑，一局最多 MAX_DATE_CHANGES 次。
"""

from __future__ import annotations

import logging

from hiro.loop.errors import ResumeBlocked

logger = logging.getLogger(__name__)

MAX_DATE_CHANGES = 2
ADVANCE_PAGES = ("unknown", "IDLE", "TRANSITION", "LOADING", "commu", "LIVE")  # 只在这些页上安全连点


def advance(rt, frame, hit) -> bool:
    """没有处理器的页面：先认非弹窗场景，再按旧主循环的规则安全连点。返回是否点了。"""
    from hiro.loop import advance as adv
    from hiro.runtime import scenes
    from hiro.vision.pages import dialog_header

    if scenes.live_start(rt, frame):
        return True
    if frame.img is not None and frame.img.shape[1] > frame.img.shape[0]:
        return False  # 横屏演出中：不点
    if scenes.commu_skip(rt, frame) or scenes.first_run_settings(rt, frame):
        return True
    if hit.name not in ADVANCE_PAGES:
        return False
    n = adv.burst([t.text for t in frame.texts], shoot=lambda: rt.screen.shot().img, click=rt.device.tap, sleep=rt.sleep,
                  in_live=lambda img: img is not None and img.shape[1] > img.shape[0], header=dialog_header)  # fmt: skip
    return n > 0


def build(args, session, device):
    """HifCore + Runtime（调用方负责 device.connect / close 和 active.use）。"""
    from hiro.produce.handlers import make_handlers
    from hiro.produce.hif import HifCore
    from hiro.runtime.loop import Runtime
    from hiro.vision.classify import classify

    for k, v in {"session": session, "use_llm": not args.no_llm, "llm_spec": args.llm, "main_attr": args.main_attr,
                 "exams_done": args.exams_done}.items():  # fmt: skip
        setattr(HifCore, k, v)
    core = HifCore(scenario=args.mode, idol=args.idol)
    return core, Runtime(raw_device=device, classify=classify, handlers=make_handlers(core), advance=advance, session=session)


def run(args, session) -> int:
    """跑一段：new = 开局后打到结束；resume = 续跑到结束。返回退出码（0 正常，3 停机交给人）。"""
    from hiro import kaa_env
    from hiro.devices import active, open_device
    from hiro.loop.date_change import DateChanged
    from hiro.runtime import finish, opening

    kaa_env.apply_formation_plan(args.idol)
    if args.command == "new" and (kaa_env.SUPPORT_SET is None or kaa_env.MEMORY_SET is None):
        logger.error("new 开局要编成号：设 HIRO_SUPPORT_SET / HIRO_MEMORY_SET，或先生成开局编成方案")
        return 2
    device = open_device()
    device.connect()
    core, rt = build(args, session, device)
    active.use(rt)
    try:
        if args.command == "new":
            finish.finish_produce_end(rt, go_home=True)  # 上一局停在结算 / 开始确认页时先回首页（开始确认页不点）
            opening.new_produce(rt, args.mode, idol=args.idol, support_set=kaa_env.SUPPORT_SET, memory_set=kaa_env.MEMORY_SET,
                                plan=kaa_env.ACTIVE_PLAN, rental_attr=args.main_attr, main_attr=args.main_attr,
                                expect_memory=tuple(v.strip() for v in args.expect_memory.split(",") if v.strip()))  # fmt: skip
        else:
            finish.resume_produce(rt)
        for attempt in range(MAX_DATE_CHANGES + 1):
            try:
                rt.run(until=lambda: False)
                return 0
            except DateChanged:
                if attempt >= MAX_DATE_CHANGES:
                    raise
                logger.warning("日切换：回首页后续跑（第 %d 次）", attempt + 1)
                session.recover("crash_restart", "日切换「日付変更」：回首页后续跑")
                finish.finish_produce_end(rt, go_home=True)
                finish.resume_produce(rt)
    except ResumeBlocked as e:
        logger.error("%s", e)
        print(str(e))
        return 3
    finally:
        active.use(None)
        device.close()
    return 0
