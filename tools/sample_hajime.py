"""初（はじめ）采样驱动：用 KAA 的标准策略（StandardStrategy）在 Mac 上自动打一局初，一路存帧，给新主循环接初 / N.I.A 做判页样本。

协调 11-17（页面清单第 3 节 P0）。只用于采样：不走我们的决策层，KAA 认不出的页（含事件选项页：kaa_patches 不让 KAA 盲选第一项）
画面 3 分钟没变化就停下，帧留着，交给人手动接。

    PYTHONPATH=src python tools/sample_hajime.py [--difficulty regular|pro|master] [--idol i_card-skin-shro-3-007]
                                                 [--out ~/github/digital-hiro/.temp/hajime-nia-mac/frames]

- 编成：按开局编成方案 conf/formation-plan.json（HIRO_FORMATION_PLAN 可改；支援卡 / 回忆编成号从方案来，也可用 HIRO_SUPPORT_SET /
  HIRO_MEMORY_SET 覆盖）。第 2 步租借格走 hiro.produce.rental（kaa_patches 的 RENTAL_PICK），挑不到才 RentalPending 停。
- 规矩同 run_hif：kaa_patches 全装（「プロデュースデータの破棄」只点キャンセル、不用ジュエル、编成核对），开局前 guard_new。
  AP 不够就停（run_hif 的自动补 AP 只认 H.I.F 的按钮），手动喝 APドリンク 后重跑。
- 存帧：每次截图和上一张存下的帧相比有明显变化（灰度缩略图平均差 ≥ --diff），或 KAA 判的页面类型变了，就存一帧原尺寸截图：
  <序号>-<时分秒>-<KAA 页面>.png；frames.jsonl 每行 {seq, t, file, scene, ctx（最近一条 KAA / kotonebot 日志）, native, logical_diff}。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import hiro  # noqa: F401  兼容层（要在 kotonebot 之前）

logger = logging.getLogger("sample_hajime")

STALL_S = 180.0  # 画面没变、KAA 页面也没变这么久：停下（帧留着，人接手）


class SampleStall(RuntimeError):
    """画面 STALL_S 秒没有变化：停下交给人。"""


class Sampler:
    """挂在 kotonebot 设备上：screenshot_raw 记住最近一张原生截图，screenshot_hook_after 拿逻辑分辨率帧判断要不要存。"""

    def __init__(self, out: Path, diff: float, clock=time.monotonic) -> None:
        self.out, self.diff, self.clock = out, diff, clock
        self.out.mkdir(parents=True, exist_ok=True)
        self.jsonl = (self.out / "frames.jsonl").open("a", encoding="utf-8")
        self.seq = sum(1 for _ in (self.out / "frames.jsonl").open(encoding="utf-8")) if (self.out / "frames.jsonl").exists() else 0
        self.last_thumb = None
        self.last_scene = None
        self.scene = "start"  # KAA ProducePage.check_scene 最近一次的结果
        self.ctx = ""  # 最近一条 KAA / kotonebot 日志
        self.raw = None
        self.progress_t = clock()

    # ---- 钩子
    def wrap_raw(self, device) -> None:
        orig = device.screenshot_raw

        def raw():
            img = orig()
            self.raw = img
            return img

        device.screenshot_raw = raw
        device.screenshot_hook_after = self.after

    def after(self, img):
        import cv2
        import numpy as np

        thumb = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (90, 160)).astype(np.float32)
        d = 255.0 if self.last_thumb is None else float(np.abs(thumb - self.last_thumb).mean())
        now = self.clock()
        if d >= self.diff or self.scene != self.last_scene:
            self.save(img, d)
            self.last_thumb, self.last_scene, self.progress_t = thumb, self.scene, now
        elif now - self.progress_t >= STALL_S:
            raise SampleStall(f"画面和 KAA 页面（{self.scene}）{now - self.progress_t:.0f}s 没变化，停下（最近日志：{self.ctx}）")
        return img

    def save(self, img, d: float) -> None:
        import cv2

        self.seq += 1
        raw = self.raw if self.raw is not None else img
        name = f"{self.seq:05d}-{time.strftime('%H%M%S')}-{self.scene}.png"
        cv2.imwrite(str(self.out / name), raw)
        rec = {"seq": self.seq, "t": time.strftime("%Y-%m-%d %H:%M:%S"), "file": name, "scene": self.scene, "ctx": self.ctx,
               "native": [int(raw.shape[1]), int(raw.shape[0])], "logical_diff": round(d, 1)}  # fmt: skip
        self.jsonl.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.jsonl.flush()

    def log_handler(self) -> logging.Handler:
        sampler = self

        class H(logging.Handler):
            def emit(self, record):
                if record.name.startswith(("kaa", "kotonebot")):
                    sampler.ctx = f"{record.name}: {record.getMessage()}"[:200]

        return H(level=logging.INFO)

    def watch_scene(self) -> None:
        """包 KAA ProducePage.check_scene：记下它判的页面类型（帧名 / jsonl 里用）。"""
        from kaa.tasks.produce.new.page import ProducePage

        orig = ProducePage.check_scene
        sampler = self

        def check_scene(page):
            scene = orig(page)
            sampler.scene = getattr(getattr(scene, "type", None), "name", None) or "UNKNOWN"
            return scene

        ProducePage.check_scene = check_scene


DIFFICULTY = {"regular": "REGULAR", "pro": "PRO", "master": "MASTER"}


def main() -> int:
    ap = argparse.ArgumentParser(description="初 采样驱动（KAA 标准策略打一局，一路存帧）")
    ap.add_argument("--difficulty", choices=list(DIFFICULTY), default="regular")
    ap.add_argument("--idol", default="i_card-skin-shro-3-007")
    ap.add_argument("--out", default=str(Path.home() / "github/digital-hiro/.temp/hajime-nia-mac/frames"))
    ap.add_argument("--diff", type=float, default=4.0, help="灰度缩略图（90x160）平均差达到这个就存一帧")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")

    from kaa.config.const import HajimeScenario
    from kotonebot.backend.context import init_context, manual_context

    from hiro import kaa_env
    from hiro.device import connect
    from hiro.kaa_env import SetupMissing, init_kaa

    scenario = getattr(HajimeScenario, DIFFICULTY[args.difficulty])
    try:
        init_kaa(scenario, idol=args.idol, require_sets=True)
    except SetupMissing as e:
        print(str(e), file=sys.stderr)
        return 2
    sampler = Sampler(Path(os.path.expanduser(args.out)), args.diff)
    logging.getLogger().addHandler(sampler.log_handler())

    device = connect()
    sampler.wrap_raw(device)
    init_context(target_device=device)
    manual_context().begin()
    sampler.watch_scene()

    from hiro.loop import kaa_patches

    kaa_patches.RENTAL_ATTR = kaa_env.PLAN_MAIN_ATTR  # 租借格按方案主属性挑（hiro.produce.rental）
    kaa_patches.apply()  # 破弃框只点キャンセル、编成核对、租借、不盲选第一项……（同 run_hif）
    import importlib

    from kaa.tasks.actions.scenes import at_home

    from hiro.loop.resume import ResumeBlocked, finish_produce_end, guard_new
    from kotonebot import device as kdev

    produce_module = importlib.import_module("kaa.tasks.produce.produce")  # KAA 原版 ProduceController + StandardStrategy
    logger.info("初 %s 采样：偶像 %s，支援卡编成 %s，回忆编成 %s，存帧 → %s", args.difficulty, args.idol, kaa_env.SUPPORT_SET,
                kaa_env.MEMORY_SET, sampler.out)  # fmt: skip
    try:
        kdev.screenshot()
        if not at_home():
            finish_produce_end(go_home=True)
        guard_new()  # 别的设备有进行中的培育：KAA 会自动确认破弃，先拦住
        if produce_module.do_produce(args.idol, scenario) is False:
            # AP 不足（KAA 已点キャンセル退出）。run_hif 的自动补 AP 是按 H.I.F 按钮弹窗的，初的页面不一样：这里不自动喝，停下交人
            print("AP 不足：KAA 已点キャンセル退出。请手动喝 APドリンク（不用ジュエル）后重跑", file=sys.stderr)
            return 3
    except (ResumeBlocked, kaa_patches.RentalPending, kaa_patches.FormationMismatch) as e:
        logger.error("%s", e)
        print(str(e), file=sys.stderr)
        return 3
    except SampleStall as e:
        logger.error("%s", e)
        print(f"{e}\n帧在 {sampler.out}（共 {sampler.seq} 张），请人工接手", file=sys.stderr)
        return 4
    except Exception as e:  # noqa: BLE001  KAA 认不出 / 崩了：帧留着，交给人
        logger.exception("采样中断：%s", e)
        print(f"采样中断：{e}\n帧在 {sampler.out}（共 {sampler.seq} 张），请人工接手", file=sys.stderr)
        return 4
    print(f"初 {args.difficulty} 一局打完，帧 {sampler.seq} 张 → {sampler.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
