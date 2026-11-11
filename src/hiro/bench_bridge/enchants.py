"""主数据里的附魔：打出一张卡 / 带着一个 P 道具，会挂上哪些持续效果（UIObs ench 的 [附魔 id, 次数, 回合]）。

画面上持续效果只有来源卡名，没有 ID：只看画面时，出牌插件按「自己打出了哪张卡」从这里查它挂的附魔（ScreenTracker 记账），
开考时加上偶像自带 P 道具的附魔。次数画面上看不到触发，按初始值记。
"""

from __future__ import annotations

from functools import lru_cache

INF = -1
CARD_ENCHANT_TYPES = ("ProduceExamEffectType_ExamStatusEnchant", "ProduceExamEffectType_ExamStatusEnchantEncore")


def _n(v) -> int:
    v = int(v or 0)
    return INF if v <= 0 else v


class Enchants:
    """按主数据（引擎 catalog）查附魔；查不到时返回空列表。"""

    def __init__(self, catalog=None):
        if catalog is None:
            from gakumas_exam.catalog import Catalog

            catalog = Catalog()
        self.cat = catalog

    def _get(self, table, key, variant=None):
        try:
            return self.cat.one(table, key, variant)
        except Exception:  # noqa: BLE001
            return None

    @lru_cache(maxsize=None)  # noqa: B019  一局里同一张卡反复查
    def card(self, card_id: str, upgrade: int) -> tuple:
        """打出这张卡挂上的附魔：((附魔 id, 次数, 回合, 只第一次打出时), …)。强化超过最高等级时按最高等级。"""
        row = None
        for u in range(int(upgrade or 0), -1, -1):
            row = self._get("ProduceCard", card_id, u)
            if row is not None:
                break
        out = []
        for pe in (row or {}).get("playEffects") or ():
            e = self._get("ProduceExamEffect", pe.get("produceExamEffectId"))
            if e and e.get("effectType") in CARD_ENCHANT_TYPES and e.get("produceExamStatusEnchantId"):
                out.append((e["produceExamStatusEnchantId"], _n(e.get("effectCount")), _n(e.get("effectTurn")), bool(pe.get("isOncePlayEffect"))))
        return tuple(out)

    @lru_cache(maxsize=None)  # noqa: B019
    def item(self, item_id: str) -> tuple:
        """P 道具带的附魔：((附魔 id, 次数, 回合), …)。"""
        row = self._get("ProduceItem", item_id) or {}
        out = []
        for eid in row.get("produceItemEffectIds") or ():
            e = self._get("ProduceItemEffect", eid)
            if e and e.get("effectType") == "ProduceItemEffectType_ExamStatusEnchant" and e.get("produceExamStatusEnchantId"):
                out.append((e["produceExamStatusEnchantId"], _n(e.get("effectCount")), _n(e.get("effectTurn"))))
        return tuple(out)

    def idol_items(self, idol: str | None) -> list[str]:
        row = self._get("IdolCard", idol) if idol else None
        it = (row or {}).get("beforeProduceItemId")
        return [it] if it else []
