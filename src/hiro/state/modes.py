"""培育模式表：produce id → 家族（hif / hajime / nia）、难度、步数、考试过关名次、各场考试的档位。

设计稿 `.temp/plans-20261112/初与NIA-决策-设计.md` 第二节。步数和考试档位来自主数据（`Produce.steps`、`ProduceStepAuditionDifficulty`），
家族 / 难度按 produce id 固定（主数据的 `Produce.name` 只有「プロ」「マスター」，初和 N.I.A 同名，分不出家族）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

HIF = "hif"
HAJIME = "hajime"
NIA = "nia"


@dataclass(frozen=True)
class Mode:
    produce_id: str
    family: str  # hif / hajime / nia
    difficulty: str  # regular / pro / master / legend（初、N.I.A）；selection / finals（H.I.F）
    pass_rank: int  # 考试 / 试镜要到的名次：初前 3、N.I.A 第 1（主数据 rankThreshold）；H.I.F 按各自规则，这里记 1


MODES: dict[str, Mode] = {
    m.produce_id: m
    for m in (
        Mode("produce-001", HAJIME, "regular", 3),
        Mode("produce-002", HAJIME, "pro", 3),
        Mode("produce-003", HAJIME, "master", 3),
        Mode("produce-006", HAJIME, "legend", 3),
        Mode("produce-004", NIA, "pro", 1),
        Mode("produce-005", NIA, "master", 1),
        Mode("produce-007", HIF, "selection", 1),
        Mode("produce-008", HIF, "finals", 1),
    )
}


def mode(produce_id: str) -> Mode:
    return MODES[produce_id]


def family(produce_id: str | None) -> str | None:
    m = MODES.get(produce_id or "")
    return m.family if m else None


@lru_cache(maxsize=1)
def master():
    """引擎的主数据（gakumasu-diff 快照，vendor/gakumas-player）。不用 hiro.state 的 KAA game.db：那份太旧，新偶像卡查不到（8a3a1e7 11-17）。"""
    import hiro.sim  # noqa: F401  引擎路径
    from gakumas_exam.catalog import Catalog

    return Catalog()


def steps(produce_id: str) -> int:
    """日程步数（主数据 Produce.steps：初 13 / 16 / 18，N.I.A 27 / 26）。"""
    return int(master().one("Produce", produce_id)["steps"])


# ---------------------------------------------------------------- 考试 / 试镜档位

STAGE_KIND = {"ProduceStepType_AuditionMid1": "mid1", "ProduceStepType_AuditionMid2": "mid2", "ProduceStepType_AuditionFinal": "final"}
STAGE_ORDER = ("mid1", "mid2", "final")


@dataclass(frozen=True)
class Tier:
    """一场考试的一个档位（主数据 ProduceStepAuditionDifficulty 一行）。初每场只有 1 档；N.I.A 每场 3–4 档。"""

    number: int
    audition_type: str  # 例如 Mid1Easy；初是 Unknown
    base_score: int
    vote_unlock: int  # voteCount：选这一档要先攒到的投票数（N.I.A；0 = 不要票）
    vote_baseline: int  # voteCountBaseLine
    rank_threshold: int  # 要到的名次
    parameter_baseline: int
    force_end_score: int  # 到这个分数考试就结束（初 REGULAR 中間 900）；0 = 不封顶
    battle_config_id: str
    npc_group_id: str
    gimmick_group_id: str


@dataclass(frozen=True)
class Stage:
    kind: str  # mid1 / mid2 / final
    tiers: tuple[Tier, ...] = field(default_factory=tuple)


def auditions(produce_id: str, idol_card_id: str) -> list[Stage]:
    """这个偶像卡在这个培育里的各场考试，按 mid1 → mid2 → final 排，每场的档位按编号排。偶像卡没有配置时返回空列表。"""
    c = master()
    ref = c.one("IdolCard", idol_card_id).get("produceStepAuditionDifficultyId")
    rows = [r for r in c.rows("ProduceStepAuditionDifficulty") if r.get("id") == ref and r.get("produceId") == produce_id]
    out: list[Stage] = []
    for kind in STAGE_ORDER:
        tiers = sorted(
            (Tier(number=int(r["number"]), audition_type=str(r.get("auditionType", "")).replace("ProduceStepAuditionType_", ""),
                  base_score=int(r.get("baseScore") or 0), vote_unlock=int(r.get("voteCount") or 0),
                  vote_baseline=int(r.get("voteCountBaseLine") or 0), rank_threshold=int(r.get("rankThreshold") or 0),
                  parameter_baseline=int(r.get("parameterBaseLine") or 0), force_end_score=int(r.get("forceEndScore") or 0),
                  battle_config_id=r.get("produceExamBattleConfigId", ""), npc_group_id=r.get("produceExamBattleNpcGroupId", ""),
                  gimmick_group_id=r.get("produceExamGimmickEffectGroupId", ""))
             for r in rows if STAGE_KIND.get(r.get("stepType")) == kind),
            key=lambda t: t.number,
        )  # fmt: skip
        if tiers:
            out.append(Stage(kind, tuple(tiers)))
    return out
