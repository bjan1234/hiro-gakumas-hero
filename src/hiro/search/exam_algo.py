"""初 / N.I.A 试镜出牌：和偶像之路同一套 Rust GNRPA 搜索（hiro.search.tower_algo.TowerGnrpa），开局换成通用的 exam_env。

ctx.loadout 是 bench 题（gkms.hif_loadout.v1）时先用 exam_env.from_hif_loadout 换写法；是偶像之路编成（produce_id tower）时
走 TowerGnrpa 原来的路。对手分：ctx.meta.rival_scores 有就用各对手的 score_max（保守），没有按主数据对手组。
终局目标 exam_env.objective（超过对手 + 3940a9 按场次的 stage_objective）。初的课程题（round lesson）按课程开局，目标是合格线 + 满分线封顶。
"""

from __future__ import annotations

import collections
import json
import logging
import random

from hiro.search.tower_algo import TowerGnrpa

logger = logging.getLogger(__name__)

# 对账护栏的门槛（11-18 按 bench 标定：初 48 题 + N.I.A 39 题、护栏关掉打一遍，试镜正常局累计比值最低 0.36、最高 1.55；
# 倍率为 0 时引擎每步 +0，比值接近 0）。课程不查：课程不乘倍率，没有这种故障；已知的引擎缺口（追い込み过合格线后的加成、
# 随机卡池生成）会让比值低到 0–0.1，但 GNRPA 照样比 uinet 好，退回反而亏。
CALIB_MIN_STEPS = 3
CALIB_MIN_SCORE = 30
CALIB_LOW = 0.25
CALIB_HIGH = 4.0


class SearchDistrust(RuntimeError):
    """搜索自己判定不可信（护栏）。whole_round：这一场剩下的步都退回 uinet（中转层看这个属性）。"""

    def __init__(self, msg: str, *, whole_round: bool = True):
        super().__init__(msg)
        self.whole_round = whole_round


class _ObsView:
    """ctx 换一个 obs，其余属性照原 ctx（bench 的 Ctx 有方法，不能拷成 SimpleNamespace）。"""

    def __init__(self, ctx, obs):
        self._ctx, self.obs = ctx, obs

    def __getattr__(self, k):
        return getattr(self._ctx, k)


class ExamGnrpa(TowerGnrpa):
    name = "hiro-exam-gnrpa"
    title = "hiro 试镜 GNRPA（Rust）"

    def begin(self, ctx):
        lo = dict(ctx.loadout or {})
        if lo.get("produce_id") == "tower":
            return super().begin(ctx)
        from hiro.search.exam_env import (
            ExamUnsupported,
            exam_env,
            from_hif_loadout,
            loadout_npc_permil,
            objective,
            scale_npc_range,
        )

        self.lo = from_hif_loadout(lo) if lo.get("deck_cards") is not None else lo
        if not self.lo.get("produce_cards"):
            raise ExamUnsupported("没有这一场的编成（实机拼不出，原因见中转层日志）")
        if not self.lo.get("lesson"):
            pm = self.lo.get("score_bonus_permils") or ()
            vals = [pm.get(k, pm.get(str(k))) for k in (1, 2, 3)] if isinstance(pm, dict) else list(pm)
            if len(vals) != 3 or not all(int(v or 0) > 0 for v in vals):
                raise ExamUnsupported(f"三属性倍率读不全（{pm}）：引擎会以为出牌不加分，不搜")  # 初第二局中間（协调 11-18）
        # bench 裁判（GKMS）给的对手区间没算对手分增减（AuditionNpcEnhancePermil），按 P 道具推的千分比缩放（客户端算法）
        permil = loadout_npc_permil(self.lo)
        rivals = [
            scale_npc_range(int(r.get("score_min") or r["score_max"]), int(r["score_max"]), permil)[1]
            for r in (getattr(ctx, "meta", None) or {}).get("rival_scores") or ()
            if r.get("score_max") is not None
        ]
        self.obj = objective(self.lo, rivals or None)
        seed = random.Random(json.dumps(self.lo.get("produce_cards"), sort_keys=True, default=str)).randrange(1, 2**31)
        self.rx = exam_env(self.lo, seed).rx
        self.rx.advance()
        self.prev = None
        self.seen_types, self.free, self._turn_weights = {}, None, None
        self.policy = {}
        self.known = []  # 抽牌记录只有偶像之路同一编成重试才有（用户 11-14 定的例外），初 / N.I.A 不用
        self.drawn = 0
        self.stats = collections.Counter()
        self.hold_strong = bool(self.lo.get("lesson"))  # 课程：强饮料留到考试（协调 11-18）
        self.calib = {"pred": 0, "act": 0, "n": 0}  # 引擎算的每步加分 vs 画面实际加分（护栏）
        self._expect = None
        self._known_types = None
        self._replay(getattr(ctx, "history", None) or ())

    def _replay(self, history) -> None:
        """编成晚于开考才拼好（倍率要等画面读到，初的考试 T1 常见）：这一场已经执行过的动作（中转层记的 (UIObs, 动作)）按当时的画面
        在引擎里补放一遍，打出过的牌留下的附魔 / 状态才在（初 PRO 第一局中間：T1 uinet 打的 エウレカ！+ 引擎里没有，它的
        「体力 50% 以下时回合开始按元気 40% 得分」整场缺席，T7 画面 +798、引擎 +39，对账护栏判不可信，协调 11-18）。"""
        done = 0
        for o, a in history:
            try:
                self._align(o)
                self.rx.step(tuple(a))
                self.rx.advance()
                done += 1
            except Exception as e:  # noqa: BLE001  补放不了的那一步：之后照常按画面对齐
                self.stats["replay_failed"] += 1
                logger.info("补放开局前的动作 %s 失败：%s: %s", a, type(e).__name__, e)
        if history:
            self.stats["replayed"] += done
            self.prev = None

    def _align(self, obs: dict) -> None:
        """同 TowerGnrpa._align；审查日程已知（中转层放进 ctx.loadout["turn_types"]，平台读面板）时回合属性整表按日程，不再随机。"""
        super()._align(obs)
        known = getattr(self, "_known_types", None)
        if known:
            tt = [int(t) for t in self.rx.turn_types]
            for i, t in enumerate(known[: len(tt)]):
                if t:
                    tt[i] = int(t)
            self.rx.turn_types = tt
            self.free = [i for i in (self.free or ()) if i >= len(known) or not known[i]]

    def decide(self, ctx):
        """护栏（协调 11-18，初第二局中間倍率为 0 打了 227 分）：
        1. 引擎和画面对账：每一步我们选的动作执行后，引擎算的加分和下一帧画面实际的加分都累计（每步都记），比累计值；至少 CALIB_MIN_STEPS 步有实际加分、
           累计实际加分 ≥ CALIB_MIN_SCORE 后，比值在 [CALIB_LOW, CALIB_HIGH] 之外 → 这一场的模型不可信，整场退回 uinet（whole_round）。只查试镜；
        2. 终局分预测中位 ≤ 0 → 这一步不信它，退回 uinet。
        没做「比 uinet 的终局分预测」：uinet 在初 / N.I.A 上的预测量级不可信（初中間预测 1.5–3 万、实际 900；课程预测 7.9 万、满分 80）。"""
        obs = ctx.obs
        self._update_lesson(getattr(ctx, "loadout", None))
        self._known_types = (getattr(ctx, "loadout", None) or {}).get("turn_types") if isinstance(getattr(ctx, "loadout", None), dict) else None
        score = int((obs.get("num") or {}).get("score") or 0)
        if getattr(self, "_expect", None) is not None and not (getattr(self, "lo", None) or {}).get("lesson"):
            before, pred = self._expect
            act = score - before
            c = self.calib
            # 累计比（每一步都记）：画面分数读数常比实际晚一步（初 PRO 第一局：引擎在出牌那步 +406 / +279，画面下一步才读到 +406 / +278），
            # 以前只记「画面这一步涨了分」的步，引擎在画面没涨那一步算的加分全丢了，3 步累计引擎 13、画面 428 误判不可信（协调 11-18）
            c["pred"] += max(0, pred - before)
            c["act"] += max(0, act)
            c["n"] += int(act > 0)
            if c["n"] >= CALIB_MIN_STEPS and c["act"] >= CALIB_MIN_SCORE:
                r = c["pred"] / c["act"]
                if not CALIB_LOW <= r <= CALIB_HIGH:
                    self._expect = None
                    raise SearchDistrust(f"引擎算的加分和画面差太多：{c['n']} 步累计引擎 {c['pred']}、画面 {c['act']}（比值 {r:.2f}）")
        self._expect = None
        d = self._decide_held(ctx)
        q = (d.meta or {}).get("score_quantiles") or {}
        if q.get("50%") is not None and int(q["50%"]) <= 0:
            raise SearchDistrust(f"终局分预测 {q['50%']}，不信它", whole_round=False)
        if getattr(self, "calib", None) is not None:
            self._expect = (score, int(self.rx.score))  # 我们的动作执行后引擎的分（下一帧画面对账）
        return d

    def _update_lesson(self, loadout) -> None:
        """课程中途画面读到了满分线（中转层更新 ctx.loadout.lesson）：目标的封顶跟着改。"""
        les = (loadout or {}).get("lesson") if isinstance(loadout, dict) else None
        mine = (getattr(self, "lo", None) or {}).get("lesson")
        if not les or not mine or les.get("perfect_score") == mine.get("perfect_score"):
            return
        from hiro.search.exam_env import stage_objective

        self.lo = {**self.lo, "lesson": {**mine, "perfect_score": les.get("perfect_score")}}
        self.obj = {k: v for k, v in self.obj.items() if k not in ("score_cap", "clear_score")}
        self.obj.update(stage_objective(self.lo))
        self.stats["lesson_cap_updated"] += 1

    def _decide_held(self, ctx):
        """课程时把强饮料（exam_env.strong_drink）从这一步的局面里拿掉：引擎里没有、合法动作里也没有，搜索就不会喝；
        饮料下标按剩下的重排，选出的动作再换回画面的下标。"""
        if not getattr(self, "hold_strong", False):
            return super().decide(ctx)
        from hiro.search.exam_env import strong_drink

        obs = dict(ctx.obs)
        drinks = list(obs.get("drinks") or [])
        keep = [i for i, d in enumerate(drinks) if not strong_drink(d if isinstance(d, str) else d[0])]
        if len(keep) == len(drinks):
            return super().decide(ctx)
        obs["drinks"] = [drinks[i] for i in keep]
        legal = []
        for a in obs.get("legal") or []:
            if a[0] != "drink":
                legal.append(a)
            elif int(a[1]) in keep:
                legal.append(["drink", keep.index(int(a[1]))])
        obs["legal"] = legal
        self.stats["held_strong_drinks"] += len(drinks) - len(keep)
        d = super().decide(_ObsView(ctx, obs))
        act = tuple(d.action)
        if act and act[0] == "drink":
            d.action = ("drink", keep[int(act[1])])
        return d
