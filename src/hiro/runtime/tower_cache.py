"""偶像之路的本机缓存（只给偶像之路同编成重试用；H.I.F 不读种子 / 不读存档的规矩不变）。

两类文件，目录 HIRO_TOWER_CACHE（缺省 ~/.cache/hiro/tower）：

- `<tower_id>-<layer>.json`：编成页读到的 loadout（gkms.exam_loadout.v1 + formation_signature）。「同じ編成で再挑戦」不经过编成页，
  同一进程重试、或从结果页 / 名次页 / 再挑戦确认页 / 考试中起跑时读这一份设 HIRO_TOWER_LOADOUT；经过编成页就覆盖（协调 11-14）。
- `<tower_id>-<layer>-<签名>.json`：这一场实际抽到的牌（按抽到的顺序，含开局手牌）和对手分数（8a3a1e7 11-14 定的格式）：
  `{"tower_id", "layer", "formation_signature", "draws": [{"id": "p_card-…", "u": 1}, …], "rivals": [105438, …]}`。
  抽牌从考试每一步的手牌变化推出来；有一步说不清（认不出的卡、生成卡、同一步一张消失一张同名出现）就只写到那之前，不猜。

编成签名：主 / サブ1 / サブ2 回忆的 id 读不到，用偶像卡 id + 编成页三张回忆的评价值（「12075」「10773」「9978」，按主、サブ1、サブ2）；
评价值读不全退回偶像卡 id + 三属性值。都读不到不写签名。
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)


def cache_dir() -> Path:
    return Path(os.environ.get("HIRO_TOWER_CACHE") or Path.home() / ".cache" / "hiro" / "tower")


def signature(idol_card_id: str | None, ratings: list | None, params: list | None) -> str | None:
    """编成签名：偶像卡 id + 三张回忆评价值（读不全退回三属性值）；偶像卡 id 读不到返回 None。"""
    if not idol_card_id:
        return None
    nums = ratings if ratings and len(ratings) == 3 else params if params and len(params) == 3 else None
    return f"{idol_card_id}.{'-'.join(str(int(v)) for v in nums)}" if nums else None


def loadout_path(tower_id: str, layer: int) -> Path:
    return cache_dir() / f"{tower_id}-{layer}.json"


def save_loadout(lo: dict) -> Path | None:
    """loadout 存一份到缓存（tower_id / layer 缺一个就不存）。"""
    if not lo.get("tower_id") or not lo.get("layer"):
        return None
    p = loadout_path(lo["tower_id"], lo["layer"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(lo, ensure_ascii=False), encoding="utf-8")
    return p


def load_loadout(tower_id: str | None, layer: int | None) -> dict | None:
    """按 tower_id + layer 读缓存的 loadout；layer 不知道（从考试中 / 名次页起跑）时取这条路线最近写的一份。"""
    if not tower_id:
        return None
    if layer:
        p = loadout_path(tower_id, layer)
    else:
        cands = [p for p in cache_dir().glob(f"{tower_id}-*.json") if p.stem[len(tower_id) + 1 :].isdigit()]
        p = max(cands, key=lambda q: q.stat().st_mtime, default=None)
    if p is None or not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("偶像之路 loadout 缓存 %s 读不了：%s", p, e)
        return None


def draws_path(tower_id: str, layer: int, sig: str) -> Path:
    return cache_dir() / f"{tower_id}-{layer}-{sig}.json"


def save_draws(tower_id: str, layer: int, sig: str, draws: list[dict], rivals: list[int]) -> Path:
    p = draws_path(tower_id, layer, sig)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"tower_id": tower_id, "layer": layer, "formation_signature": sig, "draws": draws, "rivals": rivals}
    p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------- 抽牌推断
def _hand(fields: dict) -> list[tuple[str, int]] | None:
    """一步的手牌 [(卡 id, 强化)]（按槽位从左到右）；有认不出的卡返回 None。"""
    hand = fields.get("hand")
    if hand is None:
        return None
    out = []
    for c in sorted(hand, key=lambda c: c.get("slot", 0)):
        if not c.get("card_id"):
            return None
        out.append((c["card_id"], int(c.get("upgrade") or 0)))
    return out


def infer_draws(steps: list[dict], deck_ids: set[str] | None = None) -> tuple[list[dict], str | None]:
    """考试各步（{"remaining_turns", "hand": [...], "played": 槽位或 None, "unrecognized": 认不出的卡数}，按时间顺序）→
    (抽到的牌 [{"id", "u"}]，停在哪儿的原因；全程说得清时原因是 None)。

    规则（只写有把握的前缀）：
    - 第一步的整手牌是开局手牌，全算抽到（槽位从左到右）。
    - 回合变了（残りターン 变小）：上回合剩下的手牌进弃牌堆，新手牌整手算抽到。
    - 同一回合内：上一步的手牌去掉打出的那张，多出来的算抽到（卡效果抽牌）；少了的（消耗 / 弃牌效果）不管。
    - 说不清就停：认不出的卡、多出来的卡不在牌组里（生成卡 / 麻烦卡，deck_ids 给了才查）、
      同一步一张消失又出现同 id 的卡（强化 / 换牌分不清）、残りターン 读不到。
    """
    draws: list[dict] = []
    prev: list[tuple[str, int]] | None = None
    prev_turn = None
    for i, st in enumerate(steps):
        hand = None if st.get("unrecognized") else _hand(st)
        if hand is None:
            return draws, f"第 {i} 步手牌有认不出的卡"
        turn = st.get("remaining_turns")
        if turn is None:
            return draws, f"第 {i} 步残りターン读不到"
        if prev is None or turn < prev_turn:
            added = hand
        elif turn > prev_turn:
            return draws, f"第 {i} 步残りターン变大（{prev_turn} → {turn}）"
        else:
            expect = Counter(prev)
            slot = steps[i - 1].get("played")
            if slot is not None:
                if not 0 <= slot < len(prev):
                    return draws, f"第 {i - 1} 步打出的槽位 {slot} 不在手牌里"
                expect[prev[slot]] -= 1
            extra = Counter(hand) - expect
            gone = expect - Counter(hand)
            if {cid for cid, _ in extra} & {cid for cid, _ in gone}:
                return draws, f"第 {i} 步同一张卡消失又出现（强化 / 换牌分不清）"
            left = Counter(extra)
            added = []
            for c in hand:  # 多出来的按槽位从左到右
                if left[c] > 0:
                    added.append(c)
                    left[c] -= 1
        if deck_ids and (odd := [cid for cid, _ in added if cid not in deck_ids]):
            return draws, f"第 {i} 步多出来的卡不在牌组里（{odd}，生成卡 / 麻烦卡）"
        draws.extend({"id": cid, "u": u} for cid, u in added)
        prev, prev_turn = hand, turn
    return draws, None


def exam_steps(steps_jsonl: Path, label: str, after_seq: int = 0) -> list[dict]:
    """trace 的 steps.jsonl 里这一场考试（exam_label 对得上、seq 在开考之后）的各步 → infer_draws 的输入。"""
    out = []
    if not steps_jsonl.exists():
        return out
    for line in steps_jsonl.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        f = (r.get("observation") or {}).get("fields") or {}
        if (r.get("seq") or 0) <= after_seq or f.get("exam_label") not in (label, None) or f.get("hand") is None:
            continue
        act = (r.get("decision") or {}).get("action") or {}
        ok = (r.get("execution") or {}).get("ok", True)
        played = (act.get("args") or {}).get("slot") if act.get("kind") == "PlayCard" and ok else None
        out.append({"remaining_turns": f.get("remaining_turns"), "hand": f.get("hand"), "played": played,
                    "unrecognized": len(f.get("unrecognized_cards") or [])})  # fmt: skip
    return out
