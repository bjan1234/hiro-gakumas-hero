"""「初」（はじめ）新主循环：从プロデュース选初 + 难度开局，打完一局（协调 11-17 ①，目标初 REGULAR）。

    PYTHONPATH=src python -m hiro.runtime.hajime new    --idol i_card-skin-shro-3-007 [--difficulty regular] [--main-attr Da]
    PYTHONPATH=src python -m hiro.runtime.hajime resume --idol i_card-skin-shro-3-007

- 开局：培育入口 → 剧本页翻到初（Produce.LogoHajime）→ OCR 点「レギュラー / REGULAR」（--difficulty pro / master 同理）→ 第 1–4 步同
  H.I.F 选拔（选偶像 / 支援卡 + 租借 / 回忆 / 加成，编成号按开局编成方案）→ プロデュース開始。
- 状态里写 produce.mode = produce-001 / 002 / 003，决策器按它走 3940a9 的 hiro.brain.hajime_nia（选行动、授業、外出）。
- 选行动页（hiro.vision.action）：初的「授業」不分属性、「活動支給」= allowance、追い込み三选一 = training + oikomi + 页头 exam_next。
- 练习课（PRACTICE）：按考试打（run_exam），标签 hajime-lesson-<vo|da|vi>[-sp|-hard]：属性看练习课右上图标（图标优先），认不出用选的
  课程；SP 看选的按钮，追い込み = hard（8a3a1e7 的中转层按它查 step_type）。「CLEARまで / PERFECTまで」消失 LESSON_END_S 秒算结束。
- 考试：判成 TOWER_EXAM（偶像之路的考试判据会认中初的考试页）的当 EXAM 打，标签 hajime-mid1 / hajime-final（按选行动页头「中間まで /
  最終まで」，没读到按第几场）。结算名次页按名次判过线（初前 3，modes.pass_rank），没过用再挑戦：免费 / 已有チケット、每场最多 3 次，
  确认框出现ジュエル / マニー就取消（协调 11-17）。
- 认不出的画面照 H.I.F 主循环点空白推进（play.advance：有禁点词 / 弹窗标题条不点）；Sampler 照样存帧，方便之后补识别。
退出码：0 打完，3 停下交人（ResumeBlocked / 设备错误），2 参数 / 编成号缺。
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from hiro.loop.errors import ResumeBlocked
from hiro.runtime import opening

logger = logging.getLogger(__name__)

MODES = {"regular": "produce-001", "pro": "produce-002", "master": "produce-003"}
DIFFICULTY_WORDS = {"regular": ("レギュラー", "REGULAR"), "pro": ("プロ", "PRO"), "master": ("マスター", "MASTER")}
DEFAULT_OUT = Path.home() / "github" / "digital-hiro" / ".temp" / "hajime-mac" / "frames"
LESSON_END_S = 2.0  # 练习课 HUD（CLEARまで / PERFECTまで）连续消失这么久算练习课结束（出牌动画不会盖住它）
RESULT_WAIT_S = 12.0  # 考试打完后等结算名次页出来


def new_produce(rt, difficulty: str, **prep) -> None:
    """培育入口 → 初 → 难度 → 第 1–4 步（同 H.I.F 选拔）→ プロデュース開始（使用者放行开局后才跑）。"""
    from hiro.runtime import nia_sample

    if opening.enter_produce(rt, new=True) != "new":
        raise ResumeBlocked("没进到剧本选择页")
    opening.select_scenario(rt, "Produce.LogoHajime")
    nia_sample.choose_difficulty(rt, difficulty, words=DIFFICULTY_WORDS[difficulty])
    opening.prepare(rt, "qualify", **prep)
    opening.start(rt)


def lesson_label(attr: str | None, choice, options: list[dict]) -> str:
    """练习课标签：hajime-lesson-<vo|da|vi>[-sp|-hard]。attr 是画面右上图标认出的属性，认不出用选的按钮的；
    追い込み（选行动页的选项带 oikomi）= hard，否则按选的按钮有没有 SP。属性都不知道时给 hajime-lesson（中转层按缺省处理）。"""
    a = attr or (getattr(choice, "attr", None) if choice is not None else None)
    if not a:
        return "hajime-lesson"
    if any(o.get("oikomi") for o in options or []):
        kind = "-hard"
    elif choice is not None and getattr(choice, "sp", None):
        kind = "-sp"
    else:
        kind = ""
    return f"hajime-lesson-{a.lower()}{kind}"


def hajime_core(scenario_mode: str):
    """HifCore 的初版：练习课按考试打、考试标签 hajime-mid1 / hajime-final、按名次判过线和再挑戦。"""
    from hiro.devices import active  # 用时再取 active.device / active.sleep（测试可替换）
    from hiro.exec.exam import run_exam
    from hiro.produce.hif import HifCore
    from hiro.state import modes
    from hiro.vision import hajime as hv

    class HajimeCore(HifCore):
        RETRY_JEWEL = ("ジュエル", "マニー")  # 再挑戦确认框要花ジュエル或用マニー买券：取消（协调 11-17：只用免费次数和已有チケット）
        last_action_choice = None
        last_action_options: list = []
        last_exam_next = None
        _lesson_done = False  # 刚打完的练习课还有残帧：不重进，等处理过选行动页再开门

        # ---------------------------------------------------------------- 选行动
        def on_action_select(self, ctx=None):
            self._lesson_done = False
            return super().on_action_select(ctx)

        # ---------------------------------------------------------------- 练习课
        def on_practice_entered(self, ctx):
            if self._lesson_done:
                return
            img = active.device.screenshot()
            label = lesson_label(hv.lesson_attr(img), self.last_action_choice, self.last_action_options)
            self.lesson_count += 1
            type(self).lessons_done = self.lesson_count
            logger.info("初练习课：%s（第 %d 节）", label, self.lesson_count)
            self.rec.log("exam_enter", image=img, exam=label)
            self.s.state.exam_session.label = label
            gone = {"since": None}

            def ended(shot) -> bool:
                if hv.in_lesson(shot):
                    gone["since"] = None
                    return False
                now = time.monotonic()
                if gone["since"] is None:
                    gone["since"] = now
                return now - gone["since"] >= LESSON_END_S

            run_exam(self.brain, label, self.rec, ended, session=self.s, advisor=self.advisor)
            self.rec.log("exam_end", image=active.device.screenshot(), exam=label)
            self._lesson_done = True

        def on_practice_exited(self):
            pass

        # ---------------------------------------------------------------- 考试
        def _battle_label(self, ctx) -> str:
            n = self.exam_count
            self.exam_count += 1
            type(self).exams_done = self.exam_count
            stage = self.last_exam_next or ("mid1" if n == 0 else "final")
            return f"hajime-{stage}"

        def _retry_if_failed(self, label: str, *, timeout: float = RESULT_WAIT_S) -> bool:
            """结算名次页：名次没进前 pass_rank（初前 3）就再挑戦（_click_retry：免费 / 已有チケット、每场最多 3 次、ジュエル / マニー 取消）。
            返回是否已发起再挑戦。"""
            from hiro.vision.ocr import screen_texts
            from hiro.produce.ops import button_text

            deadline = time.monotonic() + timeout
            res = None
            while res is None:
                img = active.device.screenshot()
                res = hv.exam_rank(img)
                if res is None:
                    if time.monotonic() >= deadline:
                        logger.warning("%s 打完 %.0fs 没等到结算名次页，交回主循环", label, timeout)
                        return False
                    active.sleep(0.5)
            need = modes.mode(scenario_mode).pass_rank
            passed = res["rank"] <= need
            self.rec.log("exam_result", image=img, exam=label, result={**res, "passed": passed})
            self.s.observe(scene="HIF_EXAM_RESULT", img=img, fields={"score": res.get("score"), "rank": res["rank"], "passed": passed,
                                                                      "retry": res.get("retry")})  # fmt: skip
            logger.info("%s 结算：第 %s 名（%s Pt），%s", label, res["rank"], res.get("score"), "过线" if passed else f"没进前 {need}")
            if passed:
                return False
            texts = screen_texts(img)
            btn = next((t for t in texts if button_text(t.text, "再挑戦") and t.rect.center.y > 900), None)
            if btn is None:
                self.s.note(f"{label} 第 {res['rank']} 名没进前 {need}，没有再挑戦按钮，继续")
                return False
            kind = self._click_retry(label, btn, texts)
            if kind is None:
                return False
            self.s.note(f"{label} 第 {res['rank']} 名没进前 {need}，使用再挑戦（{kind}）")
            self.exam_restarted = True
            self.exam_count -= 1
            type(self).exams_done = self.exam_count
            self.rec.log("exam_retry", exam=label, retry_kind=kind)
            return True

    HajimeCore.__name__ = HajimeCore.__qualname__ = "HajimeCore"
    return HajimeCore


def run(args) -> int:
    from hiro import kaa_env
    from hiro.contracts import TraceWriter
    from hiro.devices import active, open_device
    from hiro.devices.base import DeviceError
    from hiro.loop.landscape import LandscapeGuard
    from hiro.loop.session import Session
    from hiro.produce.handlers import make_handlers
    from hiro.runtime import finish, play
    from hiro.runtime.loop import Runtime
    from hiro.runtime.nia_sample import Sampler, set_mode
    from hiro.vision.classify import PageHit, classify

    kaa_env.apply_formation_plan(args.idol)
    support_set = args.support_set or kaa_env.SUPPORT_SET
    memory_set = args.memory_set or kaa_env.MEMORY_SET
    if args.command == "new" and (support_set is None or memory_set is None):
        logger.error("new 开局要编成号：--support-set / --memory-set，或开局编成方案")
        return 2
    mode = MODES[args.difficulty]
    from hiro.runtime.segments import trace_name

    session = Session(TraceWriter(name=trace_name("hajime", args.command, args.trace)))  # 续跑接上一段（体力 / P / 属性 / step 打底）
    Core = hajime_core(mode)
    for k, v in {"session": session, "use_llm": not args.no_llm, "llm_spec": args.llm, "main_attr": args.main_attr, "exams_done": 0}.items():
        setattr(Core, k, v)
    core = Core(scenario="qualify", idol=args.idol)
    set_mode(session, mode)
    sampler = Sampler(classify, Path(args.out), nia=False)  # 存帧 + TOWER_EXAM 当 EXAM
    device = open_device()
    device.connect()
    rt = Runtime(raw_device=device, classify=sampler, handlers=make_handlers(core), advance=play.advance, session=session,
                 landscape=LandscapeGuard(active=getattr(device, "name", "") == "maatools"), idle_stop_s=play.IDLE_STOP_S)  # fmt: skip
    active.use(rt)
    logger.info("初：%s（%s），帧存到 %s", args.difficulty, mode, sampler.out)
    rt.device.on_tap = lambda x, y: sampler.save_tap(rt.screen.frame, x, y)
    raw_shot = rt.screen.shot

    def opening_shot():  # 开局阶段（rt.drive 不调 classify）：画面变了就存，页面名 opening
        f = raw_shot()
        sampler.save(f.img, PageHit("opening", "opening"))
        return f

    try:
        rt.screen.shot = opening_shot
        if args.command == "new":
            finish.finish_produce_end(rt, go_home=True)
            new_produce(rt, args.difficulty, idol=args.idol, support_set=support_set, memory_set=memory_set, plan=kaa_env.ACTIVE_PLAN,
                        rental_attr=args.main_attr, main_attr=args.main_attr)  # fmt: skip
        else:
            finish.resume_produce(rt)
        rt.screen.shot = raw_shot
        set_mode(session, mode)
        rt.run(until=lambda: getattr(rt, "finished", False))
        return 0
    except ResumeBlocked as e:
        logger.error("%s", e)
        print(str(e))
        return 3
    except DeviceError as e:
        logger.error("设备出错，停机：%s: %s", type(e).__name__, e)
        print(f"设备出错，停机：{e}")
        return 3
    finally:
        active.use(None)
        device.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="初（新主循环）")
    ap.add_argument("command", choices=["new", "resume"])
    ap.add_argument("--idol", required=True, help="偶像卡 skin id（同 run_hif）")
    ap.add_argument("--difficulty", choices=sorted(MODES), default="regular")
    ap.add_argument("--main-attr", default=None)
    ap.add_argument("--support-set", type=int, default=None)
    ap.add_argument("--memory-set", type=int, default=None)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--llm", default=os.environ.get("HIRO_LLM"))
    ap.add_argument("--trace", default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="存帧目录")
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
