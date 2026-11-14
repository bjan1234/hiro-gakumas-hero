"""偶像之路出牌：Rust GNRPA 搜索（用户 11-14：「偶像之塔这里我们用 gnrpa 去搜索吧，不要强制性使用 uinet」）。

bench Algorithm 接口（hiro.bench_bridge 的 tower 场次按 HIRO_TOWER_ALGO 加载，也能直接在 gakumas-bench 上跑）：
  begin(ctx)：ctx.loadout（整份偶像之路编成）→ 我们的引擎开局（hiro.search.tower.tower_env）；目标 = 三星（名次按对手分数：
              ctx.loadout["rivals"] / 画面读到的优先，没有用主数据区间上限），26 / 27 层带通关条件。
  decide(ctx)：引擎局面按 ctx.obs（UIObs，画面读数）对齐——手牌（按画面顺序）、山札 / 弃牌 / 除外（按卡 id 对实例，同区优先）、
              分数 / 体力 / 元気 / やる気 / 好印象 / 饮料 / 回合；ctx.known_draws（用户 11-14：同一编成重试可以用上一次画面上看到的
              抽牌顺序；只用第一轮，洗牌后会分叉）有就把还没抽到的那段排在山札最前、设成已知前缀；然后 gakumas_exam_rs.search（三星目标）→ 动作；
              这个动作也在我们的引擎里执行，状态 / 附魔由引擎演化。
不读种子、不读存档；ctx.worlds（GKMS 世界）不用。出错就抛异常，由调用方退回 uinet（写明原因）；Rust 后端没有 search / plan_many 时构造就抛（加载失败 → 退回 uinet）。
"""

from __future__ import annotations

import collections
import json
import logging
import random
import time
from dataclasses import dataclass, field

logger = logging.getLogger("hiro.search.tower")


# 跨步热启动强度（协调 11-15 批）：bench 同题同种子每步 5 秒，26 层三星 2/8 → 5/8、均分 38.2 万 → 51.4 万（8 局逐局都高），
# 27 层三星 2/8 → 2/8、均分 101.8 万 → 104.0 万（不降）。0 = 关
WARM = 2.0
STEP_SECONDS = 5.0  # 每步搜索秒数（用户 11-14 定 5 秒）；ctx.budget 有就用它


@dataclass
class Decision:
    action: tuple
    meta: dict = field(default_factory=dict)


def known_prefix(known: list[str], deck_ids: list[str], start: int = 0) -> tuple[int, list[str]]:
    """已知抽牌顺序 known（编成牌组的卡 id，按抽到先后）和现在的山札 deck_ids（画面读到的，可能有生成卡）对位：
    找最小的 k ≥ start，使 known[k:] 开头那一段（最多山札里编成牌的张数）都在山札里、并且 known 没到头时正好就是山札里的编成牌
    → (k, 那一段)。用山札内容对位，不靠数手牌：生成卡进手牌、抽到和刚打出的同名卡都不会数错（known 由调用方截到第一轮，洗牌后不当已知）。对不上 / 已知的抽完了返回 (start, [])。"""
    ids = set(known)
    left = collections.Counter(c for c in deck_ids if c in ids)  # 山札里的编成牌（生成卡不算）
    n = sum(left.values())
    for k in range(max(0, start), len(known)):
        seg = known[k:k + n]
        got = collections.Counter(seg)
        if got - left:
            continue
        if len(seg) == n and got != left:
            continue
        return k, seg
    return start, []


class TowerGnrpa:
    name = "hiro-tower-gnrpa"
    title = "hiro 偶像之路 GNRPA（Rust）"
    privileged = False
    needs_gkms = False
    sees_seed = False

    def __init__(self, seconds: float | None = None, worlds: int = 8, threads: int = 0, warm: float = WARM, greedy: float = 0.0, **params):
        try:
            import gakumas_exam_rs as rs
        except ImportError as e:
            raise RuntimeError(f"没装 Rust 后端 gakumas_exam_rs（{e}）") from None
        missing = [f for f in ("search", "plan_many") if not hasattr(rs, f)]
        if missing:
            raise RuntimeError(f"Rust 后端 gakumas_exam_rs 是旧版本，没有 {' / '.join(missing)}（要带搜索的新包）")
        self.seconds = None if seconds is None else float(seconds)
        self.worlds, self.threads = int(worlds), int(threads)
        # warm：跨步热启动强度（上一步各世界最好路线的权重 × warm 作这一步的初始策略；0 = 关）；greedy：眼前得分先验（0 = 关）
        self.warm, self.greedy = float(warm), float(greedy)
        self.params = dict(params, seconds=seconds, worlds=worlds, threads=threads, warm=warm, greedy=greedy)
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
        self.prev = None  # 上一步对齐后、执行动作前的局面（引擎跑到画面前面时退回用）
        self.policy: dict = {}  # 上一步搜索返回的权重（热启动用）
        # 只用第一轮（牌组张数以内）：洗牌后的顺序和当时弃牌堆的内容有关，打法不同就分叉（平台模块 11-14 回放 r1 / r3：前 12 张一样、
        # 第 13 张起不同），洗牌后交给搜索当随机
        known = [(d["id"], int(d.get("u") or 0)) for d in (getattr(ctx, "known_draws", None) or [])]
        self.known = known[:len(self.lo.get("produce_cards") or [])]
        self.drawn = 0  # known_draws 里已经抽过的张数（每步按山札内容重新对位）
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

        def take(cid, zone, u=0):
            for z in [zone] + [x for x in pools if x != zone]:
                if pools[z].get(cid):
                    return pools[z][cid].pop(0)
            # 引擎牌组里没有：眠気这类机关 / 效果生成的卡（或编成没读到的牌），按画面新建一张接住
            if hasattr(rx, "new_card"):
                try:
                    g = rx.new_card(cid, int(u or 0))
                except KeyError:
                    return None
                self.stats["new_card"] += 1
                return g
            return None

        hand = [take(c["id"], "hand", c.get("u")) for c in obs["hand"]]
        grave = [take(c["id"], "grave", c.get("u")) for c in obs.get("grave") or []]
        lost = [take(c["id"], "lost", c.get("u")) for c in obs.get("lost") or []]
        ups = {c["id"]: c.get("u") for c in obs.get("deck") or []}
        deck_ids = [c["id"] for c in obs.get("deck") or []]
        # 已知抽牌顺序（ctx.known_draws：编成牌组里的牌按抽到先后、含开局起手；生成卡（眠気等）不在里面，8a3a1e7 11-14）
        if self.known:
            self.drawn, prefix = known_prefix([c for c, _ in self.known], deck_ids, self.drawn)
        else:
            prefix = []
        deck = [take(c, "deck", ups.get(c)) for c in prefix] + [take(c, "deck", ups.get(c)) for c in (collections.Counter(deck_ids) - collections.Counter(prefix)).elements()]
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

    # ---------------------------------------------------------------- 一步
    def decide(self, ctx) -> Decision:
        import gakumas_exam_rs as rs

        obs = ctx.obs
        t0 = time.monotonic()
        # 引擎比画面快（上一步我们选的动作实际没执行：退回了规则 / 画面上没生效）：回到上一步对齐后的局面再对齐
        if self.prev is not None and (self.rx.ended or int(self.rx.current_turn) > int(obs["exam"]["turn"])):
            self.rx = self.prev
            self.stats["rewind"] += 1
        self._align(obs)
        self.prev = self.rx.clone()
        secs = self.seconds if self.seconds is not None else float(getattr(ctx, "budget", None) or STEP_SECONDS)
        legal = {tuple(a) for a in obs.get("legal") or []}
        free = [] if obs["exam"].get("types") else list(range(int(self.rx.current_turn), int(self.rx.limit_turn)))
        extra = {}
        if self.greedy:
            extra["greedy"] = self.greedy
        if self.warm and self.policy:
            extra["prior"] = {k: v * self.warm for k, v in self.policy.items()}
        kw = dict(worlds=self.worlds, seconds=max(0.2, secs - 0.3), threads=self.threads, seed=int(time.time()) & 0xFFFFFFFF, **self.obj)
        try:
            r = rs.search(self.rx.clone(), self.prefix, free, **kw, **extra)
        except TypeError as e:  # 旧 Rust 包不认 prior / greedy：这一局关掉，照常搜
            if not extra:
                raise
            logger.warning("Rust 后端不认 %s（%s），这一局关掉热启动 / 先验", sorted(extra), e)
            self.warm = self.greedy = 0.0
            self.stats["no_prior"] += 1
            r = rs.search(self.rx.clone(), self.prefix, free, **kw)
        self.policy = r.get("policy") or {}
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
