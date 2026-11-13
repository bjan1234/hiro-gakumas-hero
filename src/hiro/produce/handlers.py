"""新主循环（hiro.runtime）的页面处理器：页面名 → handler(rt, frame, hit) -> Outcome，调 HifCore 的页面方法。

    rt = Runtime(raw_device=dev, classify=hiro.vision.classify.classify, handlers=make_handlers(core), ...)

这里只登记已经不依赖 KAA 上下文的页面；还要 KAA ctx 的（选行动、选卡、选饮料、轮间、PDRINK_MAX）换成自有执行后
再加进来；活動支給、培育结束由 hiro.runtime.finish 提供（协调在做）。没登记的页面 Runtime 交给 advance。

考试入口：KAA 的 _dispatch 只在「上一页不是考试」时调 on_exam_entered；新主循环每拍都会调处理器，考试打完（run_exam 返回）后
残留的考试帧会让它再进一次（场次重复计数、重复记录）。所以考试打完以后关门，直到处理过一个非考试页才重新开门；
再挑戦（core.exam_restarted）不关门，直接重进。
"""

from __future__ import annotations

from collections.abc import Callable

from hiro.runtime.loop import DONE, STAY, Outcome

EXAM_PAGES = ("HIF_EXAM", "EXAM")


def make_handlers(core) -> dict[str, Callable]:
    gate = {"exam_done": False}  # 考试打完、还没见过别的已处理页面

    def page(fn) -> Callable:
        def handler(rt, frame, hit) -> Outcome:
            gate["exam_done"] = False
            fn(None)
            return DONE

        handler.__name__ = f"handle_{fn.__name__}"
        return handler

    def exam(rt, frame, hit) -> Outcome:
        if gate["exam_done"] and not getattr(core, "exam_restarted", False):
            return STAY  # 刚打完的考试还有残帧：不重进，等画面走到下一页
        core.exam_restarted = False
        core.on_exam_entered(None)
        gate["exam_done"] = not getattr(core, "exam_restarted", False)
        return DONE

    handlers: dict[str, Callable] = {
        "CONSULT": page(core.on_consult),
        "SKILL_CARD_ENHANCE": page(core.on_skill_card_enhance),
        "SKILL_CARD_REMOVAL": page(core.on_skill_card_removal),
        "PDRINK_MAX_CONFIRM": page(core.on_pdrink_max_confirm),
        "SELECT_PITEM": page(core.on_select_pitem),
        "STUDY": page(core.on_study),
        "OUTING": page(core.on_outing),
        "SKILL_CARD_CHANGE_1": page(lambda ctx: core.on_skill_card_change(ctx, stage=1)),
        "SKILL_CARD_CHANGE_2": page(lambda ctx: core.on_skill_card_change(ctx, stage=2)),
        "PRACTICE": page(core.on_practice_entered),  # H.I.F 不该出现练习课：停机
    }
    for name in EXAM_PAGES:
        handlers[name] = exam
    return handlers
