"""初 / N.I.A 试镜出牌：和偶像之路同一套 Rust GNRPA 搜索（hiro.search.tower_algo.TowerGnrpa），开局换成通用的 exam_env。

ctx.loadout 是 bench 题（gkms.hif_loadout.v1）时先用 exam_env.from_hif_loadout 换写法；是偶像之路编成（produce_id tower）时
走 TowerGnrpa 原来的路。对手分：ctx.meta.rival_scores 有就用各对手的 score_max（保守），没有按主数据对手组。
终局目标 exam_env.objective（超过对手 + 3940a9 按场次的 stage_objective）。初的课程题（round lesson）按课程开局，目标是合格线 + 满分线封顶。
"""

from __future__ import annotations

import collections
import json
import random

from hiro.search.tower_algo import TowerGnrpa


class ExamGnrpa(TowerGnrpa):
    name = "hiro-exam-gnrpa"
    title = "hiro 试镜 GNRPA（Rust）"

    def begin(self, ctx):
        lo = dict(ctx.loadout or {})
        if lo.get("produce_id") == "tower":
            return super().begin(ctx)
        from hiro.search.exam_env import exam_env, from_hif_loadout, loadout_npc_permil, objective, scale_npc_range

        self.lo = from_hif_loadout(lo) if lo.get("deck_cards") is not None else lo
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
