"""通用考试开局：编成（gkms.exam_loadout.v1 写法的 dict）→ 我们的引擎（gakumas_exam，Rust 后端）开一局，给搜索用。

偶像之路（tower_env）、初 / N.I.A 的试镜共用这一份（3940a9 11-17 同意：构造器由 8a3a1e7 写，实机出牌也用这一份）。
lo 的字段（缺的按缺省）：
  produce_cards       牌组，"p_card-…+1/p_card_custom-…" 或 dict（hiro.search.loadout.parse_deck_entry）
  produce_item_ids    P 道具（引擎按道具挂附魔）
  start_enchant_ids   另外的开考附魔（bench 题的 main_item_enchant_ids + lesson_start_enchant_ids）
  supports            支援卡 ["s_card-3-0010:64", …]（id:等级，考试里抽牌时按概率强化）
  idol_card_id / starting_stamina / max_stamina / drink_ids
  score_bonus_permils 三属性倍率，列表 [Vo, Da, Vi] 或字典 {"1": …}
  exam                {produce_exam_battle_config_id, produce_exam_gimmick_effect_group_id}；回合数和审查基准取 battle config，
                      每回合属性按审查基准随机（同 GKMS：试镜的回合属性按审查基准抽，不按偶像自己的属性）
bench 题（gkms.hif_loadout.v1，初 / N.I.A 的试镜）先用 from_hif_loadout 换成上面这种写法。课程（初的レッスン）还不支持：
引擎没有「打到满分线就结束」，见 .temp/plans-20261112/初与NIA-bench-对照.md。
"""

from __future__ import annotations

from functools import cache

STEP_TYPES = {
    "mid1": "ProduceStepType_AuditionMid1",
    "mid2": "ProduceStepType_AuditionMid2",
    "final": "ProduceStepType_AuditionFinal",
}
PLAN_TYPES = {"ProducePlanType_Plan1": 1, "ProducePlanType_Plan2": 2, "ProducePlanType_Plan3": 3}


class ExamUnsupported(ValueError):
    """这种场次 / 写法我们的引擎开不了局（课程、查不到的试镜）。"""


def bonus_permils(b) -> dict:
    """考试倍率 → {1: Vo, 2: Da, 3: Vi}。题目文件写成列表 [Vo, Da, Vi]，bench 模板（problems.load_set(template=True)，实打时
    ctx.loadout 就是它）写成 {"1": Vo, "2": Da, "3": Vi}：两种都认（字典直接 zip 会拿到键，倍率变成 1 / 2 / 3）。"""
    if isinstance(b, dict):
        return {t: int(b[k]) for t in (1, 2, 3) for k in (t, str(t)) if k in b}
    return {t: int(v) for t, v in zip((1, 2, 3), b)}


def _master():
    from gakumas_exam.master import shared

    import hiro.sim  # noqa: F401  引擎路径
    from hiro.sim.engine import master_commit

    return shared(master_commit())


def exam_env(lo: dict, seed: int, *, guid_prefix: str = "card-exam"):
    """编成 → 我们的引擎对局（FidelityBattle，Rust 后端时是 NativeBattle，.rx 是 gakumas_exam_rs.Exam）。"""
    from gakumas_exam.battle import FidelityBattle, _native
    from gakumas_exam.cards import ExamCard
    from gakumas_exam.setup import new_exam

    import hiro.sim  # noqa: F401
    from hiro.bench_bridge.advisor import _customize_ids
    from hiro.search.loadout import parse_deck_entry

    m = _master()
    cz = _customize_ids()
    deck = []
    for i, s in enumerate(lo["produce_cards"]):
        cid, up, custom = parse_deck_entry(s)
        ids = cz(cid, up)
        counts = [int(custom.get(k) or 0) for k in ids] if custom else None
        deck.append(ExamCard(m, cid, up, counts, guid=f"{guid_prefix}-{i:03d}"))
    ex_ = lo["exam"]
    cfg = next((r for r in m.table("ProduceExamBattleConfig") if r["id"] == ex_["produce_exam_battle_config_id"]), None)
    if cfg is None:
        raise ExamUnsupported(f"主数据里没有 battle config {ex_['produce_exam_battle_config_id']}")
    plan = _idol_card(lo["idol_card_id"])["planType"]
    weights = {1: cfg["vocal"], 2: cfg["dance"], 3: cfg["visual"], "turns": int(cfg["turn"])}
    supports = [_support(m, s) for s in lo.get("supports") or ()]
    hp = int(lo.get("starting_stamina") or lo["max_stamina"])
    gimmick = ex_.get("produce_exam_gimmick_effect_group_id")
    ex = new_exam(None, m, seed, deck=deck, items=list(lo.get("produce_item_ids") or []), stamina=hp, max_stamina=int(lo["max_stamina"]),
                  randomize_turns=True, config_weights=weights, bonus_permil=bonus_permils(lo["score_bonus_permils"]),
                  drinks=list(lo.get("drink_ids") or []), plan_type=PLAN_TYPES.get(plan, 0), gimmicks=[gimmick] if gimmick else None,
                  start_enchants=list(lo.get("start_enchant_ids") or []), supports=supports)  # fmt: skip
    attrs = [{1: "Vo", 2: "Da", 3: "Vi"}[t] for t in ex.turn_types]
    env = FidelityBattle(ex, FidelityBattle._turn_table(ex, attrs, 3), attrs, turn_offset=0, draw=3)
    env.seed = seed
    env._sync_turns()
    return _native(env)


def _support(m, s) -> dict:
    """支援卡 → 引擎的 supportCardList 一项。bench 题写成 "s_card-3-0010:64" 或展开后的 {support_card_id, permil}：数字是考试内抽牌时的
    强化概率（千分比），不是等级（gkbench 展开模板时就叫 permil）；{id, level} 才按等级查。"""
    from gakumas_exam.loadout import _support as row_of
    from gakumas_exam.loadout import support_entry

    if isinstance(s, dict):
        sid, permil, level = s.get("support_card_id") or s.get("id"), s.get("permil"), s.get("level")
    else:
        sid, _, n = str(s).partition(":")
        permil, level = (int(n) if n else None), None
    if permil is None and level is not None:
        return support_entry(m, sid, int(level))
    row = row_of(m, sid)
    return {"_supportCardId": sid, "_filterParameterType": row["produceCardUpgradeLessonParameterType"],
            "_cardSearchId": row["upgradeProduceCardSearchId"], "_produceCardUpgradePermil": int(permil or 0)}  # fmt: skip


# ---------------------------------------------------------------- bench 题（gkms.hif_loadout.v1）


# 查表用引擎的主数据（gakumasu-diff 快照，hiro.bench_bridge.tower.master），不用 hiro.state 的 KAA game.db：后者旧，
# 新偶像卡（如 i_card-atbm-3-018）的试镜行没有（11-17 初 / N.I.A 29 题因此查不到）。


@cache
def _difficulty_rows() -> dict:
    from hiro.bench_bridge import tower as tw

    out: dict = {}
    for r in tw.master().rows("ProduceStepAuditionDifficulty"):
        out.setdefault((r["id"], r["produceId"], r["stepType"]), []).append(r)
    return out


@cache
def _idol_card(idol_card_id: str) -> dict:
    from hiro.bench_bridge import tower as tw

    row = next((r for r in tw.master().rows("IdolCard") if r.get("id") == idol_card_id), None)
    if row is None:
        raise ExamUnsupported(f"主数据里没有偶像卡 {idol_card_id}")
    return row


def audition_row(idol_card_id: str, produce_id: str, round_key: str, number: int | None = None) -> dict:
    """这场试镜的主数据行（ProduceStepAuditionDifficulty：偶像 × 培育 × 场次 × 编号）：battle config、对手组、gimmick、
    rankThreshold（过关名次）、baseScore（合格线）、forceEndScore（初中期封顶）、voteCount（N.I.A 票数）。
    number（N.I.A 选的是第几个试镜）不给时：只有一个就用它，有几个就报错。"""
    idol = _idol_card(idol_card_id)
    step = STEP_TYPES.get(str(round_key).lower())
    if step is None:
        raise ExamUnsupported(f"场次 {round_key} 不是试镜（课程还不支持）")
    rows = _difficulty_rows().get((idol["produceStepAuditionDifficultyId"], produce_id, step), [])
    if number:
        rows = [r for r in rows if int(r.get("number") or 0) == int(number)]
    if len(rows) != 1:
        raise ExamUnsupported(f"{idol_card_id} {produce_id} {step} 编号 {number}：主数据里找到 {len(rows)} 行")
    return rows[0]


def turn_weights(lo: dict) -> dict | None:
    """这场考试三属性回合的权重 {1: Vo, 2: Da, 3: Vi}（主数据 ProduceExamBattleConfig.vocal / dance / visual）；查不到 None。"""
    try:
        import hiro.sim  # noqa: F401  引擎路径
        from gakumas_exam.master import shared

        from hiro.sim.engine import master_commit

        cid = (lo.get("exam") or {}).get("produce_exam_battle_config_id")
        cfg = next((r for r in shared(master_commit()).table("ProduceExamBattleConfig") if r["id"] == cid), None) if cid else None
    except Exception:  # noqa: BLE001
        return None
    return {1: float(cfg["vocal"]), 2: float(cfg["dance"]), 3: float(cfg["visual"])} if cfg else None


def from_hif_loadout(doc: dict) -> dict:
    """bench 题（初 / N.I.A 的试镜，gkms.hif_loadout.v1）→ exam_env 要的写法，附 audition（主数据行，objective 要用）。
    倍率：题里有 score_bonus_permils（N.I.A 抓到的服务器倍率，已含各种加成）就用，没有按 parameters 和 battle config 算
    （同 hiro.bench_bridge.tower.score_bonus_permils 的曲线插值 + 审查基准不足扣分）。"""
    from hiro.bench_bridge import tower as tw

    if str(doc.get("round") or "") == "lesson":
        raise ExamUnsupported("课程（レッスン）还不支持：引擎没有打到满分线就结束")
    number = doc.get("audition_number") or doc.get("step_select_number")
    row = audition_row(doc["idol_card_id"], doc["produce_id"], doc.get("round") or "final", number)
    permils = doc.get("score_bonus_permils")
    if not permils:
        params = doc["parameters"]
        params = [int(params[k]) for k in ("1", "2", "3")] if isinstance(params, dict) else [int(v) for v in params]
        permils = tw.score_bonus_permils(row["produceExamBattleConfigId"], params)
    return {
        "produce_id": doc["produce_id"],
        "round": doc.get("round"),
        "idol_card_id": doc["idol_card_id"],
        "produce_cards": list(doc["deck_cards"]),
        "produce_item_ids": list(doc.get("produce_item_ids") or []),
        "start_enchant_ids": list(doc.get("main_item_enchant_ids") or []) + list(doc.get("lesson_start_enchant_ids") or []),
        "supports": list(doc.get("support_cards") or []),
        "drink_ids": list(doc.get("drink_ids") or []),
        "starting_stamina": int(doc.get("starting_stamina") or doc["max_stamina"]),
        "max_stamina": int(doc["max_stamina"]),
        "score_bonus_permils": permils,
        "exam": {"produce_exam_battle_config_id": row["produceExamBattleConfigId"],
                 "produce_exam_gimmick_effect_group_id": row.get("produceExamGimmickEffectGroupId") or None,
                 "produce_exam_battle_npc_group_id": row["produceExamBattleNpcGroupId"]},
        "audition": {k: row.get(k) for k in ("rankThreshold", "baseScore", "forceEndScore", "voteCount", "isStaticNpcScore", "number")},
    }  # fmt: skip


def objective(lo: dict, rivals: list | None = None) -> dict:
    """search / plan_many 的终局目标（rivals：对手终局分，从高到低）：画面 / ctx.meta 给的优先，没有用主数据对手组的 scoreMax（保守）；
    再加按场次的目标（stage_objective：过关名次、分数封顶、课程合格线）。"""
    from hiro.bench_bridge import tower as tw

    if rivals:
        top = sorted((int(x) for x in rivals), reverse=True)
    else:
        npc = (lo.get("exam") or {}).get("produce_exam_battle_npc_group_id")
        rows = [r for r in tw.master().rows("ProduceExamBattleNpcGroup") if r.get("id") == npc] if npc else []
        top = sorted((int(r["scoreMax"]) for r in rows), reverse=True)
    out = {"rivals": top, "lost_ssr_max": None, "debuffs_min": None}
    out.update(stage_objective(lo))
    return out


def stage_objective(lo: dict) -> dict:
    """按场次的目标（3940a9，设计稿第五节）：只给有值的键（旧 Rust 包不认这几个参数）。
    - 过关名次 pass_rank：主数据 rankThreshold（初 = 3，N.I.A = 1），名次在线外一律 0 档；
    - 分数封顶 score_cap：forceEndScore > 0 时（初 REGULAR 中間 900，到分考试就结束，多的分没用）；
    - 课程（以后）：clear_score = 合格线、score_cap = 满分线。"""
    aud = lo.get("audition") or {}
    out: dict = {}
    if aud.get("rankThreshold"):
        out["pass_rank"] = int(aud["rankThreshold"])
    if int(aud.get("forceEndScore") or 0) > 0:
        out["score_cap"] = int(aud["forceEndScore"])
    lesson = lo.get("lesson") or {}
    if lesson.get("clear_score") is not None:
        out["clear_score"] = int(lesson["clear_score"])
        if lesson.get("perfect_score"):
            out["score_cap"] = int(lesson["perfect_score"])
    return out
