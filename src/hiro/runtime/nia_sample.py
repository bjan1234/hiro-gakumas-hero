"""N.I.A 采样模式（新主循环）：从プロデュース选 N.I.A PRO 开局，共用页走现有处理器 + 3940a9 的 hajime_nia 规则，
认不出 / 没有处理器的页存帧、停下交人，人手动处理后 resume 接着跑。边跑边存帧，N.I.A 的识别从这批帧长起来。

    PYTHONPATH=src python -m hiro.runtime.nia_sample new    --idol i_card-skin-shro-3-007 [--difficulty pro] [--main-attr Da]
    PYTHONPATH=src python -m hiro.runtime.nia_sample resume --idol i_card-skin-shro-3-007

- KAA 不支持 N.I.A（produce.py 四处直接抛 UnsupportedProduceScenarioError），所以只能走新主循环。
- 开局：培育入口 → 剧本页翻到 N.I.A（Produce.LogoNia）→ OCR 点「プロ / PRO」（或 --difficulty master）→ 第 1–4 步同 H.I.F 选拔
  （选偶像 / 支援卡 + 租借 / 回忆核对 / 加成，编成号按开局编成方案）→ プロデュース開始。
- 状态里写 produce.mode = produce-004（PRO）/ produce-005（MASTER），决策器按它走 hiro.brain.hajime_nia。
- 认不出的画面：不点（Runtime 原来会连点空白，N.I.A 的新页面上不安全），连续 UNKNOWN_STOP_S 秒还认不出就存帧停下；
  没有处理器、也不在「点一下就过」名单里的页同样处理。横屏 LIVE 不算。
- 考试：判成 HIF_EXAM / EXAM / TOWER_EXAM 都按考试打，标签 nia-mid1 / nia-mid2 / nia-final（按进了几场，8a3a1e7 的中转层认）。
- 存帧：画面变了（灰度缩略图平均差 ≥ FRAME_DIFF）或页面名变了就存一张 JPEG q95，frames.jsonl 记 {seq, t, file, page, source}。
退出码：0 打完，3 停下交人（ResumeBlocked / 设备错误），2 参数 / 编成号缺。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import cv2
import numpy as np

from hiro.loop.errors import ResumeBlocked
from hiro.runtime import nav, opening

logger = logging.getLogger(__name__)

MODES = {"pro": "produce-004", "master": "produce-005"}
DIFFICULTY_WORDS = {"pro": ("プロ", "PRO"), "master": ("マスター", "MASTER")}
DIFFICULTY_BAND = (700, 1000)  # 剧本页难度按钮的 y 范围（N.I.A 剧本页「プロ / マスター」约 y 876）
AP_COST = 20
UNKNOWN_STOP_S = 15.0
FRAME_DIFF = 4.0
DEFAULT_OUT = Path.home() / "github" / "digital-hiro" / ".temp" / "nia-mac" / "frames"
STAGES = ("nia-mid1", "nia-mid2", "nia-final")


# ---------------------------------------------------------------- 开局
def select_scenario(rt, logo: str, timeout: float = opening.LOGO_TIMEOUT) -> None:
    """剧本选择页翻到 logo：先往前翻到目标或最前面的「初」，再往后翻（同 opening.select_hif）。"""
    from hiro.vision.ui_templates import point

    turned = {"back": False}

    def step(f):
        if nav.find(f, logo) is not None:
            return True
        if not turned["back"] and nav.find(f, "Produce.LogoHajime") is None:
            rt.device.tap(*point("Produce.PointPrev"))
        else:
            turned["back"] = True
            rt.device.tap(*point("Produce.PointNext"))
        return None

    rt.drive(step, timeout, f"翻到 {logo}")


def choose_difficulty(rt, difficulty: str, timeout: float = opening.MODE_TIMEOUT) -> None:
    """剧本页点难度按钮（OCR 找「プロ / PRO」），直到进了第 1 步。AP 不足只喝 APドリンク（同 opening.choose_mode）。"""
    from hiro.loop import ap_refill

    words = DIFFICULTY_WORDS[difficulty]
    state = {"refilled": False}

    def step(f):
        if nav.find(f, "Produce.TextStepIndicator1") is not None:
            return True
        if nav.find(f, "Produce.TextAPInsufficient") is not None:
            if state["refilled"]:
                raise ResumeBlocked("喝过 APドリンク 后仍然 AP 不足，停下")
            r = ap_refill.refill(lambda: rt.screen.shot().img, rt.device.tap, opening._ocr, extra_ap=0, sleep=rt.sleep, clock=rt.clock,
                                 log=logger.warning)  # fmt: skip
            if not r["ok"]:
                raise ResumeBlocked(f"AP 不足，APドリンク 没补上：{r['error']}")
            state["refilled"] = True
            return None
        lo, hi = DIFFICULTY_BAND
        btn = next((t for t in f.texts if lo <= t.rect.center.y <= hi and any(w == t.text.replace(" ", "") for w in words)), None)
        if btn is not None:
            logger.info("N.I.A：点「%s」%s", btn.text, tuple(btn.rect.center))
            rt.device.tap(*btn.rect.center)
            rt.sleep(1.5)
        return None

    rt.drive(step, timeout, f"进 N.I.A {difficulty}")


def new_produce(rt, difficulty: str, **prep) -> None:
    """培育入口 → N.I.A → 难度 → 第 1–4 步（同 H.I.F 选拔）→ プロデュース開始（使用者放行开局后才跑）。"""
    if opening.enter_produce(rt, new=True) != "new":
        raise ResumeBlocked("没进到剧本选择页")
    select_scenario(rt, "Produce.LogoNia")
    choose_difficulty(rt, difficulty)
    opening.prepare(rt, "qualify", **prep)
    opening.start(rt)


# ---------------------------------------------------------------- 采样：存帧 + 判页改名 + 认不出就停
class Sampler:
    """包住 classify：存帧（画面或页面名变了）；TOWER_EXAM 当考试（N.I.A 试镜可能被偶像之路的考试判据认中），其余 TOWER_* 当认不出。"""

    def __init__(self, classify, out: Path, clock=time.monotonic):
        self.classify, self.out, self.clock = classify, Path(out), clock
        self.out.mkdir(parents=True, exist_ok=True)
        self.index = self.out / "frames.jsonl"
        self.seq = sum(1 for _ in self.index.open(encoding="utf-8")) if self.index.exists() else 0
        self.last_thumb, self.last_page = None, None

    def __call__(self, img):
        hit = self.classify(img)
        if hit.name == "TOWER_EXAM":
            import dataclasses

            hit = dataclasses.replace(hit, name="EXAM")
        elif hit.name.startswith("TOWER_"):
            from hiro.vision.classify import UNKNOWN

            hit = UNKNOWN
        self.save(img, hit)
        return hit

    def save(self, img, hit) -> None:
        if img is None:
            return
        thumb = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (90, 160)).astype(np.float32)
        d = 255.0 if self.last_thumb is None else float(np.abs(thumb - self.last_thumb).mean())
        if d < FRAME_DIFF and hit.name == self.last_page:
            return
        self.seq += 1
        name = f"{self.seq:05d}-{time.strftime('%H%M%S')}-{hit.name}.jpg"
        cv2.imwrite(str(self.out / name), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        with self.index.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"seq": self.seq, "t": round(time.time(), 2), "file": name, "page": hit.name, "source": getattr(hit, "source", None),
                                "diff": round(d, 2)}, ensure_ascii=False) + "\n")  # fmt: skip
        self.last_thumb, self.last_page = thumb, hit.name


def make_advance(sampler: Sampler, stop_s: float = UNKNOWN_STOP_S):
    """采样用的 advance：认不出的画面不点，连续 stop_s 秒还认不出就存帧停下；没处理器、也点不过去的已知页同样计时。
    结算流程（回忆照片 / 突破证书）和其余已知页照旧交给 play.advance。"""
    from hiro.runtime import play

    state = {"since": None, "page": None}

    def advance(rt, frame, hit) -> bool:
        landscape = frame.img is not None and frame.img.shape[1] > frame.img.shape[0]
        if hit.name == "unknown" and not play._produce_finished(frame) and not landscape:
            did = False
        else:
            did = play.advance(rt, frame, hit)
        if did or landscape:
            state["since"] = None
            return did
        now = rt.clock()
        if state["since"] is None or state["page"] != hit.name:
            state["since"], state["page"] = now, hit.name
            return False
        if now - state["since"] >= stop_s:
            shot = _save_stop_frame(rt, sampler, frame, hit)
            raise ResumeBlocked(f"N.I.A 采样：{hit.name} 页 {now - state['since']:.0f}s 认不出 / 没有处理器，存帧 {shot}，停下交人")
        return False

    return advance


def _save_stop_frame(rt, sampler: Sampler, frame, hit) -> str:
    path = sampler.out / f"stop-{time.strftime('%H%M%S')}-{hit.name}.jpg"
    try:
        cv2.imwrite(str(path), frame.img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if rt.session is not None:
            rt.session.note(f"N.I.A 采样停下：{hit.name}（帧 {path}）")
    except Exception:  # noqa: BLE001  存帧失败不影响停下
        pass
    return str(path)


def nia_core(scenario_mode: str):
    """HifCore 的 N.I.A 版：考试标签按进了几场给 nia-mid1 / nia-mid2 / nia-final；produce.mode 写成 N.I.A。"""
    from hiro.produce.hif import HifCore

    class NiaSampleCore(HifCore):
        def _battle_label(self, ctx) -> str:
            n = self.exam_count
            self.exam_count += 1
            type(self).exams_done = self.exam_count
            return STAGES[min(n, len(STAGES) - 1)]

    NiaSampleCore.__name__ = NiaSampleCore.__qualname__ = "NiaSampleCore"
    return NiaSampleCore


def set_mode(session, mode: str) -> None:
    prod = dict(session.state.produce or {})
    prod["mode"] = mode
    session.state.produce = prod


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
    from hiro.vision.classify import classify

    kaa_env.apply_formation_plan(args.idol)
    support_set = args.support_set or kaa_env.SUPPORT_SET
    memory_set = args.memory_set or kaa_env.MEMORY_SET
    if args.command == "new" and (support_set is None or memory_set is None):
        logger.error("new 开局要编成号：--support-set / --memory-set，或开局编成方案")
        return 2
    mode = MODES[args.difficulty]
    session = Session(TraceWriter(name=args.trace))
    Core = nia_core(mode)
    for k, v in {"session": session, "use_llm": not args.no_llm, "llm_spec": args.llm, "main_attr": args.main_attr, "exams_done": 0}.items():
        setattr(Core, k, v)
    core = Core(scenario="qualify", idol=args.idol)
    set_mode(session, mode)
    sampler = Sampler(classify, Path(args.out))
    device = open_device()
    device.connect()
    rt = Runtime(raw_device=device, classify=sampler, handlers=make_handlers(core), advance=make_advance(sampler), session=session,
                 landscape=LandscapeGuard(active=getattr(device, "name", "") == "maatools"), idle_stop_s=play.IDLE_STOP_S)  # fmt: skip
    active.use(rt)
    logger.info("N.I.A 采样：%s（%s），帧存到 %s", args.difficulty, mode, sampler.out)
    try:
        if args.command == "new":
            finish.finish_produce_end(rt, go_home=True)
            new_produce(rt, args.difficulty, idol=args.idol, support_set=support_set, memory_set=memory_set, plan=kaa_env.ACTIVE_PLAN,
                        rental_attr=args.main_attr, main_attr=args.main_attr)  # fmt: skip
        else:
            finish.resume_produce(rt)
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
    ap = argparse.ArgumentParser(description="N.I.A 采样（新主循环）")
    ap.add_argument("command", choices=["new", "resume"])
    ap.add_argument("--idol", required=True, help="偶像卡 skin id（同 run_hif）")
    ap.add_argument("--difficulty", choices=sorted(MODES), default="pro")
    ap.add_argument("--main-attr", default=None)
    ap.add_argument("--support-set", type=int, default=None)
    ap.add_argument("--memory-set", type=int, default=None)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--llm", default=os.environ.get("HIRO_LLM"))
    ap.add_argument("--trace", default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="采样帧目录")
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
