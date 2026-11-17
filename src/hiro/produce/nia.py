"""N.I.A 特有页面的处理器（新主循环）：営業场所、営業话题、试镜选档。识别在 hiro.vision.nia，决策在 3940a9 的
ProduceDeciders.sales_place / sales_event / audition_select（hiro.brain.hajime_nia）。

两步的页（场所、试镜）：第一次进页决策并记住选了哪个（场所按种类、试镜按门槛），点它展开；展开后看展开的是不是记住的那个，
是就点「営業開始 / オーディション開始」，不是就重点那一张。点过之后 ACT_WAIT_S 内同一页不再点（等页面动画）。
试镜的 audition_number 记在 core.nia_audition_number，考试标签带上（nia_sample.NiaSampleCore）。
"""

from __future__ import annotations

import logging
import time

from hiro.runtime.loop import DONE, STAY

logger = logging.getLogger(__name__)

ACT_WAIT_S = 2.5


class NiaPages:
    def __init__(self, core):
        self.core = core
        self._acted: tuple[str, float] | None = None
        self.place_choice: str | None = None  # 场所种类（kind）
        self.audition_choice: int | None = None  # 门槛票数（vote_need）

    def _now(self, rt) -> float:
        clock = getattr(rt, "clock", None)
        return clock() if callable(clock) else time.monotonic()

    def _wait(self, rt, page: str) -> bool:
        return self._acted is not None and self._acted[0] == page and self._now(rt) - self._acted[1] < ACT_WAIT_S

    def _tap(self, rt, page: str, pos) -> None:
        rt.device.tap(int(pos[0]), int(pos[1]))
        self._acted = (page, self._now(rt))

    def _decide(self, page: str, fields: dict):
        s = self.core.s
        obs = s.observe(scene=page, fields=dict(fields))
        d = self.core.deciders.decide(page, s.state)
        s.record(obs, decision=d)
        logger.info("N.I.A %s ← %s：%s", page, d.source, d.reason)
        return d

    # ---------------------------------------------------------------- 営業场所
    def on_sales_place(self, rt, f, hit):
        page, fields = "NIA_SALES_PLACE", hit.fields or {}
        if self._wait(rt, page):
            return STAY
        places = fields.get("places") or []
        if not fields.get("expanded") or self.place_choice is None:
            d = self._decide(page, fields)
            i = (d.action.args or {}).get("select")
            if i is None or not 0 <= int(i) < len(places):
                return STAY  # 决策没给出（读不全）：等下一帧
            self.place_choice = places[int(i)]["kind"]
        target = next((p for p in places if p["kind"] == self.place_choice), None)
        if target is None:
            return STAY
        if fields.get("expanded") and fields.get("selected") == target["index"] and fields.get("start"):
            logger.info("N.I.A 営業：%s，点「営業開始」", target.get("name"))
            self._tap(rt, page, fields["start"])
            self.place_choice = None
            return DONE
        self._tap(rt, page, target["center"])  # 展开这一张（或者展开的不是它：重点）
        return DONE

    # ---------------------------------------------------------------- 営業话题
    def on_sales_event(self, rt, f, hit):
        page, fields = "NIA_SALES_EVENT", hit.fields or {}
        if self._wait(rt, page):
            return STAY
        choices = fields.get("choices") or []
        d = self._decide(page, fields)
        i = (d.action.args or {}).get("select")
        if i is None or not 0 <= int(i) < len(choices):
            return STAY
        logger.info("N.I.A 営業话题：%s", choices[int(i)].get("text"))
        self._tap(rt, page, choices[int(i)]["center"])
        return DONE

    # ---------------------------------------------------------------- 试镜选档
    def on_audition_select(self, rt, f, hit):
        page, fields = "NIA_AUDITION_SELECT", hit.fields or {}
        if self._wait(rt, page):
            return STAY
        tiers = fields.get("tiers") or []
        if not fields.get("expanded") or self.audition_choice is None:
            d = self._decide(page, fields)
            args = d.action.args or {}
            i = args.get("select")
            if i is None or not 0 <= int(i) < len(tiers):
                return STAY
            self.audition_choice = tiers[int(i)]["vote_need"]
            self.core.nia_audition_number = args.get("audition_number") or tiers[int(i)].get("number")
        target = next((t for t in tiers if t["vote_need"] == self.audition_choice), None)
        if fields.get("expanded") and fields.get("chosen_need") == self.audition_choice and fields.get("start"):
            logger.info("N.I.A 试镜：门槛 %s（档 %s），点「オーディション開始」", self.audition_choice, self.core.nia_audition_number)
            self._tap(rt, page, fields["start"])
            self.audition_choice = None
            return DONE
        if target is None:
            return STAY  # 展开后被盖住读不到那一档：等
        self._tap(rt, page, target["center"])
        return DONE

    # ---------------------------------------------------------------- 试镜结束的加分展示
    def on_audition_bonus(self, rt, f, hit):
        """「オーディションボーナス / パラメータボーナス」：只是展示，点底部「TAP」过。"""
        page = "NIA_AUDITION_BONUS"
        if self._wait(rt, page):
            return STAY
        self._tap(rt, page, (hit.fields or {}).get("tap") or (360, 1222))
        return DONE

    def handlers(self) -> dict:
        return {"NIA_SALES_PLACE": self.on_sales_place, "NIA_SALES_EVENT": self.on_sales_event, "NIA_AUDITION_SELECT": self.on_audition_select,
                "NIA_AUDITION_BONUS": self.on_audition_bonus}
