"""偶像之路（tower）：编成 → 我们的引擎（gakumas_exam，Rust 后端）开局，和搜索的终局目标（用户 11-14：偶像之塔用 GNRPA 搜、追求三星）。

编成写法同 bench 题目 / HIRO_TOWER_LOADOUT（gkms.exam_loadout.v1）：produce_cards（「卡ID+强化/定制ID*次数」）、produce_item_ids、
starting_stamina / max_stamina、score_bonus_permils、exam（gimmick / battle_config / npc_group，缺了用 hiro.bench_bridge.tower.layer_exam 补）。
离线对拍（设计稿「偶像之路第 1 步」）：机关、回合属性（按 battle_config 的三属性权重随机，和 GKMS 逐种子一致）、倍率都是现有能力；
随机出牌 200 局的分布，集中 / やる気 和 GKMS 一致，好印象还差约 2 万（待查）。
"""

from __future__ import annotations


def complete_loadout(lo: dict) -> dict:
    """编成缺的考试设置（机关 / battle_config / 对手组 / 层道具）用 layer_exam 补；已有的不动。"""
    from hiro.bench_bridge import tower as tw

    lo = dict(lo)
    ex = dict(lo.get("exam") or {})
    if not (ex.get("produce_exam_battle_config_id") and ex.get("produce_exam_gimmick_effect_group_id")):
        lex = tw.layer_exam(lo["tower_id"], int(lo["layer"]), lo.get("mechanic"))
        for k, v in ((lex or {}).get("exam") or {}).items():
            if v is not None and not ex.get(k):
                ex[k] = v
        items = list(lo.get("produce_item_ids") or [])
        for i in (lex or {}).get("exam", {}).get("produce_item_ids") or []:
            if i not in items:
                items.append(i)
        lo["produce_item_ids"] = items
    lo["exam"] = ex
    return lo


def tower_env(lo: dict, seed: int):
    """编成 → 我们的引擎对局（FidelityBattle，Rust 后端时是 NativeBattle，.rx 是 gakumas_exam_rs.Exam）。"""
    import hiro.sim  # noqa: F401  引擎路径
    from gakumas_exam.battle import FidelityBattle, _native
    from gakumas_exam.cards import ExamCard
    from gakumas_exam.master import shared
    from gakumas_exam.setup import new_exam

    from hiro.bench_bridge.advisor import _customize_ids
    from hiro.search.loadout import parse_deck_entry
    from hiro.sim.engine import master_commit
    from hiro.state.context import catalog

    m = shared(master_commit())
    cz = _customize_ids()
    deck = []
    for i, s in enumerate(lo["produce_cards"]):
        cid, up, custom = parse_deck_entry(s)
        ids = cz(cid, up)
        counts = [int(custom.get(k) or 0) for k in ids] if custom else None
        deck.append(ExamCard(m, cid, up, counts, guid=f"card-tower-{i:03d}"))
    ex_ = lo["exam"]
    cfg = next(r for r in m.table("ProduceExamBattleConfig") if r["id"] == ex_["produce_exam_battle_config_id"])
    plan = catalog().one("IdolCard", lo["idol_card_id"])["planType"]
    plan_type = {"ProducePlanType_Plan1": 1, "ProducePlanType_Plan2": 2, "ProducePlanType_Plan3": 3}.get(plan, 0)
    weights = {1: cfg["vocal"], 2: cfg["dance"], 3: cfg["visual"], "turns": int(cfg["turn"])}
    bonus = dict(zip((1, 2, 3), lo["score_bonus_permils"]))
    hp = int(lo.get("starting_stamina") or lo["max_stamina"])
    ex = new_exam(None, m, seed, deck=deck, items=list(lo.get("produce_item_ids") or []), stamina=hp, max_stamina=int(lo["max_stamina"]),
                  randomize_turns=True, config_weights=weights, bonus_permil=bonus, drinks=list(lo.get("drink_ids") or []),
                  plan_type=plan_type, gimmicks=[ex_["produce_exam_gimmick_effect_group_id"]])  # fmt: skip
    attrs = [{1: "Vo", 2: "Da", 3: "Vi"}[t] for t in ex.turn_types]
    env = FidelityBattle(ex, FidelityBattle._turn_table(ex, attrs, 3), attrs, turn_offset=0, draw=3)
    env.seed = seed
    env._sync_turns()
    return _native(env)


def objective(lo: dict, rivals: list | None = None) -> dict:
    """search / plan_many 的目标参数：rivals（对手终局分，优先用画面读到的；没有用主数据区间的上限，保守）、通关条件。"""
    from hiro.bench_bridge import tower as tw

    out: dict = {"rivals": [], "lost_ssr_max": None, "debuffs_min": None}
    if rivals:
        out["rivals"] = sorted((int(x) for x in rivals), reverse=True)
    else:
        lex = tw.layer_exam(lo["tower_id"], int(lo["layer"]), lo.get("mechanic")) or {}
        out["rivals"] = sorted((int(hi) for _, hi in lex.get("rivals") or []), reverse=True)
    for c in tw.star_conditions(int(lo["layer"])):
        if c.get("field") == "lost_ssr" and c.get("op") == "<=":
            out["lost_ssr_max"] = int(c["value"])
        elif c.get("field") == "debuffs" and c.get("op") == ">=":
            out["debuffs_min"] = int(c["value"])
    return out
