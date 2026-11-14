"""偶像之路出牌：Rust GNRPA 搜索（用户 11-14：「偶像之塔这里我们用 gnrpa 去搜索吧，不要强制性使用 uinet」）。

bench Algorithm 接口（hiro.bench_bridge 的 tower 场次按 HIRO_TOWER_ALGO 加载，也能直接在 gakumas-bench 上跑）：
  begin(ctx)：ctx.loadout（整份偶像之路编成）→ 我们的引擎开局（hiro.search.tower.tower_env）；目标 = 三星（名次按对手分数：
              ctx.loadout["rivals"] / 画面读到的优先，没有用主数据区间上限），26 / 27 层带通关条件。
  decide(ctx)：引擎局面按 ctx.obs（UIObs，画面读数）对齐——手牌（按画面顺序）、山札 / 弃牌 / 除外（按卡 id 对实例，同区优先）、
              分数 / 体力 / 元気 / やる気 / 好印象 / 饮料 / 回合；ctx.known_draws（用户 11-14：同一编成重试可以用上一次画面上看到的
              抽牌顺序）有就把还没抽到的那段排在山札最前、设成已知前缀；然后 gakumas_exam_rs.search（三星目标）→ 动作；
              这个动作也在我们的引擎里执行，状态 / 附魔由引擎演化。
不读种子、不读存档；ctx.worlds（GKMS 世界）不用。出错就抛异常，由调用方退回 uinet（写明原因）。
"""

from __future__ import annotations

import collections
import json
import os
import random
import time
from dataclasses import dataclass, field


@dataclass
class Decision:
    action: tuple
    meta: dict = field(default_factory=dict)


class TowerGnrpa:
    name = "hiro-tower-gnrpa"
    title = "hiro 偶像之路 GNRPA（Rust）"
    privileged = False
    needs_gkms = False
    sees_seed = False

    def __init__(self, seconds: float | None = None, worlds: int = 8, threads: int = 0, **params):
        self.seconds = None if seconds is None else float(seconds)
        self.worlds, self.threads = int(worlds), int(threads)
        self.params = dict(params, seconds=seconds, worlds=worlds, threads=threads)
        self.rx = None

    def describe(self) -> dict:
        return {"name": self.name, "params": self.params, "privileged": False, "sees_seed": False}

    # ---------------------------------------------------------------- 一局
    def begin(self, ctx):
        from hiro.search.tower import complete_loadout, objective, tower_env

        self.lo = complete_loadout(dict(ctx.loadout))
        self.obj = objective(self.lo, self.lo.get("rivals"))
        seed = random.Random(json.dumps(self.lo.get("produce_cards"), sort_keys=True)).randrange(1, 2 ** 31)
        self.rx = tower_env(self.lo, seed).rx
        self.rx.advance()
        self.known = [(d["id"], int(d.get("u") or 0)) for d in (getattr(ctx, "known_draws", None) or [])]
        self.drawn = 0  # 这局已经从山札抽到手里的张数（对 known_draws 用）
        self.last_hand: list = []
        self.first = True
        self.stats = collections.Counter()

    # ---------------------------------------------------------------- 对齐
    def _align(self, obs: dict) -> None:
        rx = self.rx
        guard = 0
        while not rx.ended and rx.current_turn < int(obs["exam"]["turn"]) and guard < 4:
            rx.step(("end",))
            rx.advance()
            guard += 1
        pools = {z: collections.defaultdict(list) for z in ("hand", "deck", "grave", "lost")}
        for z in pools:
            for g in rx.zone(z):
                pools[z][rx.card_info(g)[0]].append(g)

        def take(cid, zone):
            for z in [zone] + [x for x in pools if x != zone]:
                if pools[z].get(cid):
                    return pools[z][cid].pop(0)
            return None

        hand = [take(c["id"], "hand") for c in obs["hand"]]
        grave = [take(c["id"], "grave") for c in obs.get("grave") or []]
        lost = [take(c["id"], "lost") for c in obs.get("lost") or []]
        deck_ids = [c["id"] for c in obs.get("deck") or []]
        # 已知抽牌顺序（ctx.known_draws：按抽到先后、含开局起手）：已经抽了几张按手牌里新出现的张数累计，还没抽到的那段排在山札最前
        prefix: list = []
        if self.known:
            cur = collections.Counter(c["id"] for c in obs["hand"])
            self.drawn = len(obs["hand"]) if self.first else self.drawn + sum((cur - collections.Counter(self.last_hand)).values())
            left = collections.Counter(deck_ids)
            for cid, _ in self.known[self.drawn:]:
                if left.get(cid):
                    prefix.append(cid)
                    left[cid] -= 1
                else:
                    break  # 记录和山札对不上：后面的不当已知
        deck = [take(c, "deck") for c in prefix] + [take(c, "deck") for c in (collections.Counter(deck_ids) - collections.Counter(prefix)).elements()]
        if None in hand:
            raise RuntimeError(f"手牌对不上引擎牌组：{[c['id'] for c, g in zip(obs['hand'], hand) if g is None]}")
        rx.set_zone("hand", hand)
        rx.set_zone("grave", [g for g in grave if g])
        rx.set_zone("lost", [g for g in lost if g])
        rx.set_zone("deck", [g for g in deck if g])
        num = obs["num"]
        rx.score, rx.stamina, rx.block = int(num["score"]), int(num["stamina"]), int(num["block"])
        st = {s[0]: s[1] for s in obs.get("status") or []}
        if "aggressive" in st:
            rx.aggressive = int(st["aggressive"])
        if "review" in st:
            rx.review = int(st["review"])
        drinks = [d if isinstance(d, str) else d[0] for d in obs.get("drinks") or []]
        if drinks or rx.drinks:
            rx.drinks = drinks
        types = obs["exam"].get("types")
        if types and len(types) >= int(rx.limit_turn):
            rx.turn_types = [int(t) for t in types]
        self.prefix = len(prefix)
        self.last_hand = [c["id"] for c in obs["hand"]]
        self.first = False

    # ---------------------------------------------------------------- 一步
    def decide(self, ctx) -> Decision:
        import gakumas_exam_rs as rs

        obs = ctx.obs
        t0 = time.monotonic()
        self._align(obs)
        secs = self.seconds if self.seconds is not None else float(getattr(ctx, "budget", None) or os.environ.get("HIRO_TOWER_SEARCH_S", 5))
        legal = {tuple(a) for a in obs.get("legal") or []}
        free = [] if obs["exam"].get("types") else list(range(int(self.rx.current_turn), int(self.rx.limit_turn)))
        r = rs.search(self.rx.clone(), self.prefix, free, worlds=self.worlds, seconds=max(0.2, secs - 0.3), threads=self.threads,
                      seed=int(time.time()) & 0xFFFFFFFF, **self.obj)  # fmt: skip
        best = tuple(r["best"]) if r.get("best") else ("end",)
        if legal and best not in legal:
            ok = [tuple(v[0]) for v in r.get("votes") or [] if tuple(v[0]) in legal]
            best = ok[0] if ok else (("end",) if ("end",) in legal else sorted(legal)[0])
            self.stats["illegal"] += 1
        self.rx.step(best)
        self.rx.advance()
        ws = r.get("worlds") or []
        raw = [w[4] for w in ws if len(w) > 4]
        stars = [w[5] for w in ws if len(w) > 5]
        meta = {"algo": self.name, "seconds": round(time.monotonic() - t0, 2), "worlds": len(ws),
                "votes": [[list(a), n, m] for a, n, m in (r.get("votes") or [])[:4]],
                "known_prefix": self.prefix,
                "score_quantiles": {"50%": int(sorted(raw)[len(raw) // 2])} if raw else {},
                "stars": collections.Counter(stars).most_common(3)}  # fmt: skip
        return Decision(best, meta)
