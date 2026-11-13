"""开局和续跑（去 KAA 设计稿 §3.5，替代 KAA do_produce / prepare / goto_home 和 hiro.loop.resume.enter_produce）。

全部跑在 hiro.runtime.Runtime 上：每一步 rt.drive（每拍过暂停检查点和中断层、带超时），点击都过危险点击拦截。
模板走 hiro.vision.ui_templates（KAA 的同一批模板，tools/assets/ui_from_kaa.py 搬来）。不 import KAA / kotonebot。

规矩（同旧流程）：
- 破弃框（其他端末有进行中的培育）只点キャンセル，停机，是否破弃由用户决定；别端末「開始する」绝不点。
- 新开时看到「再開する」（本机有进行中的培育）停下，让使用者改用 resume。
- AP 不足只喝 APドリンク（hiro.loop.ap_refill；确认框有ジュエル就取消）。
- 「プロデュース開始」只在 new 流程里点（使用者放行开局后才会跑 new）。

这一版是导航部分：回首页 → 培育入口 → 翻到 H.I.F → 选拔 / 本战 → AP → 开始 → 跳过交流。
第 1–3 步（选偶像 / 支援卡和租借 / 回忆）现在由 kaa_patches 包着 KAA 的 prepare，迁过来之前 new 流程不走这里。
"""

from __future__ import annotations

import logging

from hiro.loop.errors import ResumeBlocked
from hiro.runtime import nav
from hiro.vision.ocr import screen_texts
from hiro.vision.ui_templates import box, point

logger = logging.getLogger(__name__)

ENTER_TIMEOUT = 40.0
LOGO_TIMEOUT = 30.0
MODE_TIMEOUT = 40.0
START_SKIP_S = 5.0  # 点开始后这么久内一直找「跳过交流」单选框 / 确认按钮（同 KAA）

LOGOS = ("Produce.LogoHajime", "Produce.LogoNia", "Produce.LogoHif")
MODE_BUTTON = {"qualify": "Produce.ButtonHifQualify", "main": "Produce.ButtonHifMain"}
DISCARD = "游戏提示「プロデュースデータの破棄」：其他端末有进行中的培育。已点「キャンセル」，不自动新开；是否破弃由用户决定"


def _ocr(img):
    return [(t.text, t.conf, tuple(t.rect)) for t in screen_texts(img)]


def enter_produce(rt, *, new: bool, timeout: float = ENTER_TIMEOUT) -> str:
    """从首页点「プロデュース中」进培育入口。返回 "new"（到了剧本选择页）或 "resume"（本机有进行中的培育，「再開する」框）。
    new=True 时看到「再開する」就停（ResumeBlocked：应改用 resume）；破弃框只点キャンセル并停。"""
    nav.goto_home(rt)

    def step(f):
        if nav.find(f, "Produce.BreakProduceDialog.Title") is not None:
            if (c := next((t for t in f.texts if "キャンセル" in t.text), None)) is not None:
                rt.device.tap(*c.rect.center)
            raise ResumeBlocked(DISCARD)
        if any(nav.find(f, n) is not None for n in LOGOS):
            return "new"
        if nav.find(f, "Produce.ButtonResume") is not None:
            if new:
                raise ResumeBlocked("本机有进行中的培育（看到「再開する」），请用 resume 继续，而不是新开")
            return "resume"
        if nav.at_home(f):
            rt.device.tap(*box("Produce.BoxProduceOngoing").center)
        return None

    return rt.drive(step, timeout, "进培育入口")


def select_hif(rt, timeout: float = LOGO_TIMEOUT) -> None:
    """剧本选择页翻到 H.I.F：先往前翻到 H.I.F 或最前面的はじめ，再往后翻到 H.I.F（同 KAA）。"""
    turned = {"back": False}

    def step(f):
        if nav.find(f, "Produce.LogoHif") is not None:
            return True
        if not turned["back"] and nav.find(f, "Produce.LogoHajime") is None:
            rt.device.tap(*point("Produce.PointPrev"))
        else:
            turned["back"] = True
            rt.device.tap(*point("Produce.PointNext"))
        return None

    rt.drive(step, timeout, "翻到 H.I.F")


def choose_mode(rt, mode: str, *, extra_ap: int | None = None, timeout: float = MODE_TIMEOUT) -> None:
    """点 H.I.F 的选拔 / 本战，直到进了第 1 步（编成页）。AP 不足时喝 APドリンク 再点（只打选拔时本战还要 20 AP，一起补）。"""
    from hiro.loop import ap_refill

    name = MODE_BUTTON[mode]
    extra = (0 if mode == "main" else 20) if extra_ap is None else extra_ap
    refilled = {"done": False}

    def step(f):
        if nav.find(f, "Produce.Step1.ButtonNext") is not None or nav.find(f, "Produce.TextStepIndicator1") is not None:
            return True
        if nav.find(f, "Produce.TextAPInsufficient") is not None:
            if refilled["done"]:
                raise ResumeBlocked("喝过 APドリンク 后仍然 AP 不足，停下")
            r = ap_refill.refill(lambda: rt.screen.shot().img, rt.device.tap, _ocr, extra_ap=extra, sleep=rt.sleep, clock=rt.clock,
                                 log=logger.warning)  # fmt: skip
            if not r["ok"]:
                raise ResumeBlocked(f"AP 不足，APドリンク 没补上：{r['error']}")
            refilled["done"] = True
            return None
        if (m := nav.find(f, name)) is not None:
            nav.tap_match(rt, m)
        return None

    rt.drive(step, timeout, f"进 H.I.F {mode}")


def start(rt, timeout: float = 20.0) -> None:
    """第 4 步点「プロデュース開始」，之后 START_SKIP_S 秒内点「コミュをスキップ」单选框和确认按钮（同 KAA）。"""

    def press(f):
        if (m := nav.find(f, "Produce.Step4.ButtonProduceStart")) is not None:
            nav.tap_match(rt, m)
            return True
        return None

    rt.drive(press, timeout, "点プロデュース開始")
    t0 = rt.clock()
    while rt.clock() - t0 < START_SKIP_S:
        f, done = rt.tick()
        if done is None:
            for name in ("Produce.RadioTextSkipCommu", "Common.ButtonConfirmNoIcon"):
                if (m := nav.find(f, name)) is not None:
                    nav.tap_match(rt, m)
        rt.sleep(0.3)
