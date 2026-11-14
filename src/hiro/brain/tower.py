"""偶像之路的编成决策（用户 11-14：编成「接入我们的 bench 算法去游玩」，不用おまかせ；设计稿
`.temp/plans-20261112/偶像之路-编成决策-设计.md`）。

一层的编成 = 考哪种考试（mechanic，一层通常有几种）+ 主回忆（牌组、P 道具、饮料、体力、属性）+ 副回忆（只加属性：
每份副回忆三属性 × 0.2 向下取整，hiro.bench_bridge.tower.stage_params）。

- 副回忆：倍率公式（tower.score_bonus_permils）是确定的，按「倍率和最大」贪心挑，不用模拟；
- 考试 × 主回忆：每个组合换成 bench 题目的编成（gkms.exam_loadout.v1），用 bench 引擎 + UINet 按同一批种子打 K 局
  （tower.evaluate），按「分数 ≥ 过关线（第 1 名对手 scoreMax + 1）的比例，再看平均分」排。

UINet 只在 H.I.F 上训练过，偶像之路上只到上限的 33.7%（8a3a1e7）：排序只当依据之一，前两名接近时交 LLM。
"""

from __future__ import annotations

import math
import statistics

SUB_POOL = 12  # 副回忆候选最多看这么多份（按属性和）
MAIN_POOL = 6  # 主回忆最多评估这么多份（按本层倍率和）


def _vec(m) -> list[int]:
    p = m.get("params") if isinstance(m, dict) else m
    return [int(x or 0) for x in (p or (0, 0, 0))]


def bonus(lex: dict, main: dict, subs: list[dict]) -> list[int] | None:
    """这一层这一编成的考试倍率；battle_config 不知道时 None。"""
    from hiro.bench_bridge import tower as tw

    cfg = (lex.get("exam") or {}).get("produce_exam_battle_config_id")
    if not cfg:
        return None
    try:
        return tw.score_bonus_permils(cfg, tw.stage_params(_vec(main), [_vec(s) for s in subs]))
    except KeyError:
        return None


def choose_subs(lex: dict, main: dict, pool: list[dict], k: int) -> list[dict]:
    """副回忆：贪心挑 k 份，让本层倍率和（不知道倍率时用属性和）最大。主回忆不能同时当副回忆。"""
    from hiro.bench_bridge import tower as tw

    left = sorted((m for m in pool if m is not main), key=lambda m: -sum(_vec(m)))[:SUB_POOL]
    out: list[dict] = []
    for _ in range(max(0, k)):
        if not left:
            break

        def gain(m):
            b = bonus(lex, main, out + [m])
            return sum(b) if b is not None else sum(tw.stage_params(_vec(main), [_vec(s) for s in out + [m]]))

        best = max(left, key=gain)
        out.append(best)
        left.remove(best)
    return out


def loadout(lex: dict, main: dict, subs: list[dict], idol_card_id: str | None = None) -> dict:
    """（本层考试设置, 主回忆, 副回忆）→ gkms.exam_loadout.v1（同 idolroad 题目的写法）。"""
    exam = dict(lex.get("exam") or {})
    layer_items = list(exam.get("produce_item_ids") or [])
    hp = int(main.get("max_stamina") or 0) or None
    out = {
        "schema": "gkms.exam_loadout.v1", "produce_id": "tower", "round": "final",
        "tower_id": lex["tower_id"], "layer": int(lex["layer"]), "mechanic": lex["mechanic"],
        "idol_card_id": idol_card_id or main.get("idol_card_id"),
        "max_stamina": hp, "starting_stamina": hp,
        "score_bonus_permils": bonus(lex, main, subs),
        "produce_cards": list(main.get("deck") or []),
        "produce_item_ids": list(main.get("items") or []) + [i for i in layer_items if i not in (main.get("items") or [])],
        "exam": exam, "drink_ids": list(main.get("drinks") or []),
    }  # fmt: skip
    if lex.get("open_rounds") is not None:
        out["open_rounds"] = lex["open_rounds"]
    return out


def evaluable(lo: dict) -> str | None:
    """编成能不能拿去模拟：不能返回原因。"""
    ex = lo.get("exam") or {}
    if not lo.get("produce_cards"):
        return "主回忆的牌组没读到"
    if lo.get("score_bonus_permils") is None or not ex.get("produce_exam_battle_config_id"):
        return "本层考试设置（审查基准 / 回合数）不知道"
    if not ex.get("produce_exam_gimmick_effect_group_id"):
        return "本层机关不知道"
    if not lo.get("max_stamina"):
        return "主回忆的体力没读到"
    return None


def summarize(scores: list[int | None], border: int | None) -> dict:
    """K 局分数 → {n, mean, se, clear, clear_se}（出错的局不算）。"""
    xs = [s for s in scores if s is not None]
    n = len(xs)
    if not n:
        return {"n": 0, "mean": None, "se": None, "clear": None, "clear_se": None}
    mean = statistics.fmean(xs)
    se = statistics.stdev(xs) / math.sqrt(n) if n > 1 else 0.0
    clear = clear_se = None
    if border is not None:
        clear = sum(x >= border for x in xs) / n
        clear_se = math.sqrt(max(clear * (1 - clear), 1 / n) / n)
    return {"n": n, "mean": round(mean), "se": round(se), "clear": clear, "clear_se": clear_se}


def rank_key(s: dict) -> tuple:
    """排序键（大的好）：过关率 → 平均分。过关线不知道时只比平均分。"""
    return (s["clear"] if s["clear"] is not None else -1.0, s["mean"] if s["mean"] is not None else -1)


def clearly_better(a: dict, b: dict) -> bool:
    """第一名是否明显好过第二名（> 2 个标准误）：过关率能比就比过关率，否则比平均分。"""
    if a["clear"] is not None and b["clear"] is not None and (a["clear"] != b["clear"]):
        se = math.hypot(a["clear_se"] or 0, b["clear_se"] or 0)
        return a["clear"] - b["clear"] > 2 * max(se, 1e-9)
    if a["mean"] is None or b["mean"] is None:
        return False
    return a["mean"] - b["mean"] > 2 * max(math.hypot(a["se"] or 0, b["se"] or 0), 1.0)
