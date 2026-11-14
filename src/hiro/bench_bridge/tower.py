"""偶像之路（tower）的考试：层设置、考试倍率、编成评估（bench 引擎上按题目编成打若干局）。

公开主数据里 TowerLayer / TowerLayerExam 是空表，「某层考什么」查不到，这里拼：
- 已抓到的绑定（tower_id, layer, mechanic → battle_config / gimmick / npc_group / 层道具）：从 bench 题目或抓包整理成 JSON，
  放在 HIRO_TOWER_BINDINGS（缺省 ~/.cache/hiro/bench/tower_bindings.json），用 `python -m hiro.bench_bridge.tower bindings` 生成。
  这些是采集来的，不进仓库。同一层有几种考试（机制不同，battle_config 也各不相同），按机制分开记。
- 能按命名规则推的：对手组 p_npc_group-<塔>-<偶像>-<机制>-stage_<层>、层道具 pitem_<塔>-<机制>-<槽>-stage_<层>。
- 对手分数区间（ProduceExamBattleNpcGroup）、倍率曲线（ProduceExamBattleScoreConfig）、审查基准（ProduceExamBattleConfig）在主数据里。

考试倍率（score_bonus_permils）：参数 = 主回忆三属性 + Σ floor(副回忆三属性 × 0.2)；按 battle_config 的曲线插值，
低于审查基准的每项扣 0.25 − 参数 / 基准 × 0.15（扣分加总后乘到三项上），再 +1000 按 10 向上取整。
2026-11-14 用 6 场实机开局（1 副 4 场、3 副 2 场）核过，6 场都对，且换别的系数 / 取整都对不上。

过关：拿第 1 名，线 = 第 1 名对手 scoreMax + 1。三星条件另算（这里不管）。

evaluate 要 gkbench（bench 的裁判）和 GKMS 引擎（本机克隆，见 gkbench.engine），开源包里没有 GKMS 时报错说明。
"""

from __future__ import annotations

import itertools
import json
import logging
import math
import os
import re
import time
from functools import cache, lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

SUB_RATE = 0.2
COLUMNS = ("vocal", "dance", "visual")
BATTLE_CONFIG = re.compile(
    r"^p_exam_battle_config-(?P<tower>tower_\d+)-(?:\d+_){2}\d+-(?:\d+_){2}\d+-turn_(?P<turn>\d+)$"
)
GIMMICK = re.compile(r"^p_exam_gimmick-(?P<tower>tower_\d+)-(?P<mechanic>.+?)-(?P<variant>\d+)-stage_(?P<stage>\d+)$")
NPC = re.compile(r"^p_npc_group-(?P<tower>tower_\d+)-(?P<idol>[^-]+)-(?P<mechanic>.+?)-stage_(?P<stage>\d+)$")
ITEM = re.compile(r"^pitem_(?P<tower>tower_\d+)-(?P<mechanic>.+?)-(?P<slot>\d+)-stage_(?P<stage>\d+)(?:-\d+)?$")


def bindings_path() -> Path:
    env = os.environ.get("HIRO_TOWER_BINDINGS")
    if env:
        return Path(env).expanduser()
    from hiro.bench_bridge.advisor import cache_dir

    return cache_dir() / "tower_bindings.json"


def _split(tower_id: str) -> tuple[str, str]:
    """tower_001-shro → (tower_001, shro)。"""
    family, _, idol = tower_id.partition("-")
    return family, idol


# ---------------------------------------------------------------- 主数据


class Master:
    """偶像之路用到的主数据（引擎 catalog）。测试可以直接传 rows={表名: [行]}。"""

    def __init__(self, catalog=None, rows: dict | None = None):
        self._rows = rows
        if rows is None and catalog is None:
            from gakumas_exam.catalog import Catalog

            import hiro.sim  # noqa: F401  把 vendor 里的考试引擎放进 sys.path

            catalog = Catalog()
        self.cat = catalog

    def rows(self, table: str) -> list[dict]:
        if self._rows is not None:
            return list(self._rows.get(table, ()))
        return list(self.cat.rows(table))

    @cache  # noqa: B019
    def battle_config(self, config_id: str) -> dict | None:
        return next((r for r in self.rows("ProduceExamBattleConfig") if r.get("id") == config_id), None)

    @lru_cache(maxsize=1)  # noqa: B019
    def _score_points(self) -> dict:
        out: dict = {}
        for r in self.rows("ProduceExamBattleScoreConfig"):
            if "-tower_" in r.get("id", ""):
                out.setdefault(r["id"], []).append(r)
        for pts in out.values():
            pts.sort(key=lambda r: int(r.get("parameter") or 0))
        return out

    def score_points(self, score_config_id: str) -> list[dict]:
        return self._score_points().get(score_config_id, [])

    @lru_cache(maxsize=1)  # noqa: B019
    def _npc(self) -> dict:
        out: dict = {}
        for r in self.rows("ProduceExamBattleNpcGroup"):
            if NPC.match(r.get("id", "")):
                out.setdefault(r["id"], []).append(r)
        for g in out.values():
            g.sort(key=lambda r: int(r.get("number") or 0))
        return out

    def npc_group(self, group_id: str) -> list[dict]:
        return self._npc().get(group_id, [])

    @lru_cache(maxsize=1)  # noqa: B019
    def _stage_items(self) -> dict:
        out: dict = {}
        for r in self.rows("ProduceItem"):
            if m := ITEM.match(r.get("id", "")):
                out.setdefault((m["tower"], m["mechanic"], int(m["stage"])), []).append(r["id"])
        return {k: sorted(v) for k, v in out.items()}

    def stage_items(self, family: str, mechanic: str, layer: int) -> list[str]:
        return list(self._stage_items().get((family, mechanic, int(layer)), ()))

    @lru_cache(maxsize=1)  # noqa: B019
    def _gimmicks(self) -> dict:
        out: dict = {}
        for r in self.rows("ProduceExamGimmickEffectGroup"):
            if (m := GIMMICK.match(r.get("id", ""))) and r["id"] not in out.setdefault(
                (m["tower"], m["mechanic"], int(m["stage"])), []
            ):
                out[(m["tower"], m["mechanic"], int(m["stage"]))].append(r["id"])
        return {k: sorted(v) for k, v in out.items()}

    def gimmick_variants(self, family: str, mechanic: str, layer: int) -> list[str]:
        theme = "exam_full_power" if mechanic == "exam_preservation" else mechanic  # 温存和全力共用一套时间表
        return list(self._gimmicks().get((family, theme, int(layer)), ()))


@lru_cache(maxsize=1)
def master() -> Master:
    return Master()


# ---------------------------------------------------------------- 倍率


def stage_params(main: dict | list, subs=()) -> list[int]:
    """主回忆 + 副回忆 → 进考试的三属性：主 + Σ floor(副 × 0.2)。回忆写成 {vocal, dance, visual} 或 [Vo, Da, Vi]。"""

    def vec(m):
        return [int(m[k]) for k in COLUMNS] if isinstance(m, dict) else [int(v) for v in m]

    out = vec(main)
    for s in subs:
        out = [a + math.floor(b * SUB_RATE) for a, b in zip(out, vec(s))]
    return out


def _interpolate(points: list[dict], column: str, value: int) -> float:
    key = f"{column}Permil"
    if value <= int(points[0]["parameter"]):
        return float(points[0][key])
    if value >= int(points[-1]["parameter"]):
        return float(points[-1][key])
    for a, b in itertools.pairwise(points):
        x0, x1 = int(a["parameter"]), int(b["parameter"])
        if x0 <= value <= x1:
            return float(a[key]) + (value - x0) * (float(b[key]) - float(a[key])) / (x1 - x0)
    raise ValueError("曲线不单调")


def shortfall(config: dict, params: list[int]) -> float:
    """低于审查基准的扣分（三项加总）：每项 0.25 − 参数 / 基准 × 0.15。"""
    total = 0.0
    for column, v in zip(COLUMNS, params):
        crit = int(config.get(column) or 0)
        if crit and v < crit:
            total += 0.25 - (v / crit) * 0.15
    return total


def score_bonus_permils(battle_config_id: str, params: list[int], m: Master | None = None) -> list[int]:
    """本层的考试倍率 [Vo, Da, Vi]（千分比，同题目的 score_bonus_permils）。params 用 stage_params 算。"""
    m = m or master()
    config = m.battle_config(battle_config_id)
    if config is None:
        raise KeyError(battle_config_id)
    points = m.score_points(config["produceExamBattleScoreConfigId"])
    if not points:
        raise KeyError(config["produceExamBattleScoreConfigId"])
    factor = 1.0 - shortfall(config, params)
    return [math.ceil((_interpolate(points, c, v) * factor + 1000) / 10.0) * 10 for c, v in zip(COLUMNS, params)]


# ---------------------------------------------------------------- 层设置


@lru_cache(maxsize=1)
def _bindings() -> dict:
    p = bindings_path()
    if not p.is_file():
        logger.info("没有偶像之路层绑定 %s（python -m hiro.bench_bridge.tower bindings 生成）", p)
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {(r["tower_id"], int(r["layer"]), r["mechanic"]): r for r in doc.get("exams", ())}


def layer_mechanics(tower_id: str, layer: int) -> list[str]:
    """绑定里这一层已知的考试机制（一层通常有几种可选）。"""
    return sorted(k[2] for k in _bindings() if k[0] == tower_id and k[1] == int(layer))


def layer_exam(tower_id: str, layer: int, mechanic: str | None = None, m: Master | None = None) -> dict | None:
    """本层考试设置：{mechanic, turns, exam: {produce_exam_battle_config_id, produce_exam_gimmick_effect_group_id,
    produce_exam_battle_npc_group_id, produce_item_ids}, criteria, border, rivals, gimmick_variants, source}。
    mechanic 不给时：这一层只知道一种就用它，否则 None。battle_config / gimmick 只有绑定里有（没有就是 None，要从画面读）；
    对手组、层道具按命名规则推；border = 第 1 名对手 scoreMax + 1，对手组查不到时 None。"""
    m = m or master()
    layer = int(layer)
    if mechanic is None:
        known = layer_mechanics(tower_id, layer)
        if len(known) != 1:
            return None
        mechanic = known[0]
    family, idol = _split(tower_id)
    bound = _bindings().get((tower_id, layer, mechanic)) or {}
    variants = m.gimmick_variants(family, mechanic, layer)
    gimmick = bound.get("gimmick") or (variants[0] if len(variants) == 1 else None)
    exam = {
        "produce_exam_battle_config_id": bound.get("battle_config"),
        "produce_exam_gimmick_effect_group_id": gimmick,
        "produce_exam_battle_npc_group_id": bound.get("npc_group")
        or f"p_npc_group-{family}-{idol}-{mechanic}-stage_{layer:03d}",
        "produce_item_ids": stage_items_for(gimmick, family, mechanic, layer, m) if gimmick else None,
    }
    if bound.get("exam_effect_type") is not None:
        exam["exam_effect_type"] = bound["exam_effect_type"]
    config_id = exam["produce_exam_battle_config_id"]
    config = m.battle_config(config_id) if config_id else None
    rivals = [[int(r["scoreMin"]), int(r["scoreMax"])] for r in m.npc_group(exam["produce_exam_battle_npc_group_id"])]
    turns = int(BATTLE_CONFIG.match(config_id)["turn"]) if config_id and BATTLE_CONFIG.match(config_id) else None
    return {
        "tower_id": tower_id,
        "layer": layer,
        "mechanic": mechanic,
        "turns": turns,
        "exam": exam,
        "criteria": [int(config[c]) for c in COLUMNS] if config else None,
        "border": rivals[0][1] + 1 if rivals else None,
        "rivals": rivals,
        "gimmick_variants": variants,
        "source": bound.get("source") or "rule",
    }


def stage_items_for(gimmick_id: str, family: str, mechanic: str, layer: int, m: Master | None = None) -> list[str]:
    """层自带的 P 道具：槽号 = gimmick 变体号（idolroad 163 题全符：变体 1 只带槽 1、变体 2 只带槽 2，主数据没有的层不带）。"""
    m = m or master()
    g = GIMMICK.match(gimmick_id or "")
    if g is None:
        return []
    return [i for i in m.stage_items(family, mechanic, layer) if int(ITEM.match(i)["slot"]) == int(g["variant"])]


def build_bindings(problem_dirs=(), captures=()) -> list[dict]:
    """bench 题目（gkms.exam_loadout.v1，produce_id=tower）和抓包绑定（{"exams": [{towerId, number, examEffectType, …}]}）
    → 绑定行。同一 (tower_id, layer, mechanic) 设置不一致时报错（不该发生）。"""
    rows: dict = {}

    def put(key, row):
        old = rows.get(key)
        if old is not None and any(old[k] != row[k] for k in ("battle_config", "gimmick", "npc_group")):
            raise ValueError(f"{key} 两处设置不一致：{old['source']} / {row['source']}")
        rows.setdefault(key, row)

    for d in problem_dirs:
        for f in sorted(Path(d).glob("*.gksave.json")):
            if f.name.startswith("._"):
                continue
            lo = json.loads(f.read_text(encoding="utf-8")).get("loadout") or {}
            if lo.get("produce_id") != "tower" or not lo.get("exam"):
                continue
            e = lo["exam"]
            key = (lo["tower_id"], int(lo["layer"]), lo["mechanic"])
            put(key, {"tower_id": key[0], "layer": key[1], "mechanic": key[2], "exam_effect_type": e.get("exam_effect_type"),
                      "battle_config": e["produce_exam_battle_config_id"], "gimmick": e["produce_exam_gimmick_effect_group_id"],
                      "npc_group": e["produce_exam_battle_npc_group_id"], "produce_item_ids": list(e.get("produce_item_ids") or ()),
                      "source": f"bench:{f.stem.split('.')[0]}"})  # fmt: skip
    for c in captures:
        for r in json.loads(Path(c).read_text(encoding="utf-8")).get("exams", ()):
            effect = r["examEffectType"]
            name = (
                (effect.get("name") if isinstance(effect, dict) else effect)
                .removeprefix("PRODUCE_EXAM_EFFECT_TYPE_")
                .lower()
            )
            key = (r["towerId"], int(r["number"]), name)
            put(key, {"tower_id": key[0], "layer": key[1], "mechanic": key[2], "exam_effect_type": None,
                      "battle_config": r["produceExamBattleConfigId"], "gimmick": r["produceExamGimmickEffectGroupId"],
                      "npc_group": r["produceExamBattleNpcGroupId"], "produce_item_ids": [],
                      "source": f"capture:{Path(c).name}"})  # fmt: skip
    return [rows[k] for k in sorted(rows)]


# ---------------------------------------------------------------- 编成评估


def _gkbench():
    try:
        from gkbench import runner
    except ImportError as e:
        raise RuntimeError("evaluate 要 gkbench 和 GKMS 引擎：装 gkbench（或把 gakumas-bench 仓库放进 PYTHONPATH），"
                           "GKMS_ROOT 指向 GKMSProject 克隆") from e  # fmt: skip
    return runner


def evaluate(loadouts: list[dict], seeds: list[int], *, algo: str = "uinet", budget_s: float | None = None,
             step_seconds: float = 5.0) -> list[list[int | None]]:  # fmt: skip
    """每个编成（gkms.exam_loadout.v1）在同一批种子上各打一局，返回终局分（出错 None）。
    budget_s：总时限，到了就停，没跑到的给 None。algo 写法同 HIRO_BENCH_ALGO（uinet 用我们的模型和主数据）。
    同一编成、同一种子、同一算法，分数和 bench 上的一样（2026-11-14 核过 idolroad 题）。"""
    runner = _gkbench()
    from hiro.bench_bridge.advisor import load_algo

    bot = load_algo(algo)
    t0 = time.monotonic()
    out: list[list[int | None]] = []
    for li, lo in enumerate(loadouts):
        row: list[int | None] = []
        problem = {"id": f"eval-{li}", "family": f"eval-{li}", "set": "hiro-eval", "loadout": lo}
        for si, seed in enumerate(seeds):
            if budget_s is not None and time.monotonic() - t0 > budget_s:
                row.append(None)
                continue
            ep = runner.play_episode(problem, {"index": si, "seed": int(seed)}, bot, step_seconds, keep_obs=False)
            if ep.get("err"):
                logger.info("编成 %d 种子 %d 出错：%s", li, seed, ep["err"])
                row.append(None)
            else:
                row.append(int(ep["final"]["score"]))
        out.append(row)
    return out


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bindings", help="从 bench 题目 / 抓包整理层绑定")
    b.add_argument("--problems", nargs="*", default=[], help="题目目录（gakumas-bench-data/problems/idolroad）")
    b.add_argument("--captures", nargs="*", default=[], help="抓包绑定 JSON（如 GKMS 的 tower_capture_bindings.json）")
    b.add_argument("--out", default=None)
    q = sub.add_parser("layer", help="查一层的考试设置")
    q.add_argument("tower_id")
    q.add_argument("layer", type=int)
    q.add_argument("--mechanic", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "bindings":
        rows = build_bindings(a.problems, a.captures)
        out = Path(a.out) if a.out else bindings_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"schema": "hiro.tower_bindings.v1", "exams": rows}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        print(f"{len(rows)} 组 → {out}")
    else:
        print(json.dumps(layer_exam(a.tower_id, a.layer, a.mechanic), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
