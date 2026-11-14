"""偶像之路跑一段（新主循环 hiro.runtime）：列表 → 层选择 → 编成 → 考试 → 结果 →（重试 / 下一层 / 停）。

第一次实机的范围（协调 11-14）：只打「当前最前沿」那一层；编成保持现状（决策要换编成就停下报告）；考试走 run_exam + bench 中转层；
结果页按 hiro.runtime.tower.TowerRun 的规则重试或往下走；打完 --layers 层就停（缺省 1）。

    PYTHONPATH=src python -m hiro.runtime.tower_play --idol-name 月村手毬 [--layers 1] [--no-llm] [--trace <名>]

规矩同 H.I.F：おまかせ 不点；再挑戦确认框有消耗字样（hiro.runtime.tower.DIALOG_WORDS）就停，同一批词也交 GuardedDevice 拦；
认不出 / 卡住按 Runtime 看门狗停机。编成页读到的回合数 / 倍率 / 体力 / 牌组写进 HIRO_TOWER_LOADOUT（gkms.exam_loadout.v1），
bench 中转层（8a3a1e7）按它给出牌算法出偶像之路的观测。

loadout 另存一份到 hiro.runtime.tower_cache（按 tower_id + 层）：「同じ編成で再挑戦」不经过编成页，从结果页 / 名次页 /
再挑戦确认页 / 考试中起跑时读这一份。每场考完从 trace 的手牌变化推出抽牌顺序，连同名次页的对手分数按编成签名存下
（只给偶像之路同编成重试用）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from hiro.loop.errors import ResumeBlocked
from hiro.runtime import tower_cache
from hiro.runtime.loop import DONE, STAY, Outcome
from hiro.runtime.tower import DIALOG_WORDS, TowerRun

logger = logging.getLogger(__name__)

TOWER_NO = "tower_001"  # 目前只有一座塔（主数据 Tower 表）；tower_id = tower_001-<偶像代号>
END = Outcome("end", "偶像之路打完设定的层数")  # 处理器返回它：Runtime.run 正常结束


def idol_code(name: str | None) -> str | None:
    """画面上的偶像名（「月村手毬」）→ 主数据 Character.id（ttmr）。"""
    from hiro import master

    if not name:
        return None
    key = name.replace(" ", "").replace("　", "")
    row = next(iter(master.rows("SELECT id FROM Character WHERE lastName || firstName = ?", key)), None)
    return row[0] if row else None


def idol_card_id(title: str | None, code: str | None) -> str | None:
    """偶像卡名（「一匹狼」）+ 偶像代号（ttmr）→ IdolCard.id（i_card-ttmr-2-000）；查不到 None。"""
    from hiro import master

    if not title or not code:
        return None
    row = next(iter(master.rows("SELECT id FROM IdolCard WHERE name = ? AND characterId = ?", title.strip(), code)), None)
    return row[0] if row else None


def loadout(fields: dict, tower_id: str | None, layer: int | None) -> dict:
    """编成页字段 → HIRO_TOWER_LOADOUT（gkms.exam_loadout.v1；读不到的不写，8a3a1e7 11-14）。"""
    lo = {"produce_id": "tower", "tower_id": tower_id, "layer": layer, "turns": fields.get("turns"),
          "score_bonus_permils": fields.get("score_bonus_permils"), "max_stamina": fields.get("max_stamina"),
          "idol_card_id": fields.get("idol_card_id")}  # fmt: skip
    return {k: v for k, v in lo.items() if v is not None}


def rivals(ranking: dict, idol_name: str | None) -> list[int]:
    """名次页 → 对手分数（名次从高到低，去掉自己那行；按名字认，名字没读到用徽章名次）。有一行分数没读到返回空（不猜）。"""
    rows = ranking.get("rows") or []
    mine = next((r for r in rows if idol_name and r.get("name") == idol_name), None)
    if mine is None and ranking.get("my_rank"):
        mine = next((r for r in rows if r.get("rank") == ranking["my_rank"]), None)
    if mine is None:
        return []
    others = [r.get("score") for r in rows if r is not mine]
    return others if others and all(isinstance(v, int) for v in others) else []


class TowerPlay:
    """偶像之路各页面的处理器（page → handler(rt, frame, hit) -> Outcome）。core：HifCore（考试、决策、Session 都用它的）。"""

    def __init__(self, core, run: TowerRun, *, idol_name: str, layers: int, loadout_path: Path):
        self.core, self.run, self.idol_name, self.layers, self.loadout_path = core, run, idol_name, layers, loadout_path
        self.layer: int | None = None
        self.page1: dict | None = None  # 编成页第 1 页的字段（回合 / 倍率 / 体力 / 三属性）
        self.deck: dict | None = None  # 编成页第 2 页的牌组（hiro.vision.tower.read_formation_deck）
        self.done_layers = 0
        self.finished = False
        self.loadout: dict | None = None  # 现在 HIRO_TOWER_LOADOUT 指的那份（编成页写的，或从缓存读的）
        self.exam_draws: dict | None = None  # 刚考完那场的抽牌（tower_cache.infer_draws），名次页补上对手分数后存盘
        self.result_handled = False  # 这一次的结果页已经处理过（点了再挑戦 / 一覧に戻る）：等页面换了再处理下一次（实机 r2：同一张结果页处理了两次）
        if run.tower_id is None and (code := idol_code(idol_name)):
            run.tower_id = f"{TOWER_NO}-{code}"  # 没经过编成页（从名次页 / 结果页续跑）也有路线

    # ---------------------------------------------------------------- 页面
    def on_list(self, rt, f, hit):
        idol = next((i for i in hit.fields.get("idols") or [] if i.get("name") == self.idol_name), None)
        if idol is None:
            raise ResumeBlocked(f"偶像之路列表里没找到「{self.idol_name}」（读到 {[i.get('name') for i in hit.fields.get('idols') or []]}）")
        rt.device.tap(*idol["center"])
        return DONE

    def on_layers(self, rt, f, hit):
        if self.finished:
            return END
        fields = hit.fields
        if fields.get("idol") and fields["idol"] != self.idol_name:
            raise ResumeBlocked(f"层选择页是「{fields['idol']}」，不是要打的「{self.idol_name}」")
        if fields.get("stage") is None or fields.get("challenge") is None:
            return STAY  # 还没读全：等下一帧
        if fields.get("locked"):
            # 最前沿那层锁着（要先攒星，如手毬 16 层要 45 星）：按 TowerRun 要回头为三星重打已通关的层，层选择页滑动还没接，先停
            raise ResumeBlocked(f"层选择页居中的第 {fields['stage']} 层锁着（挑戦する是灰的），不点；回头重打已通关的层还没接，停下报告")
        if (fields.get("stars") or 0) >= 3:
            raise ResumeBlocked(f"层选择页居中的第 {fields['stage']} 层已经三星，没有要打的；换层（滑动）还没接，停下报告")
        self.layer = fields["stage"]  # 第一次实机：只打层选择页居中那一层（「挑戦する」对着的那层）
        logger.info("偶像之路：第 %s 层，点挑戦する", self.layer)
        rt.device.tap(*fields["challenge"])
        return DONE

    def on_layer_info(self, rt, f, hit):
        logger.info("偶像之路层详情：%s", hit.fields.get("conditions"))
        if hit.fields.get("close"):
            rt.device.tap(*hit.fields["close"])
        return DONE

    def on_formation(self, rt, f, hit):
        """编成页：第 1 页读回合 / 倍率 / 体力 / 三属性，翻到第 2 页读牌组（亮着的卡），合起来写 HIRO_TOWER_LOADOUT，
        交 TOWER_FORMATION 决策（只给当前编成），保持就点挑戦する。"""
        from dataclasses import replace

        fields = hit.fields
        if fields.get("page") == 2:
            self.deck = fields.get("deck")
            if self.page1 is None:  # 直接落在第 2 页（续跑）：先翻回第 1 页读倍率 / 体力
                return self._tap(rt, fields.get("prev_page"))
        else:
            self.page1 = fields
            if self.deck is None and fields.get("next_page"):
                return self._tap(rt, fields["next_page"])  # 翻到第 2 页读牌组
        p1 = self.page1
        self.layer = p1.get("layer") or self.layer
        tower_id = f"{TOWER_NO}-{code}" if (code := idol_code(self.idol_name)) else None
        self.run.tower_id = tower_id
        p1 = {**p1, "idol_card_id": idol_card_id(p1.get("idol_card_title"), code)}
        lo = loadout(p1, tower_id, self.layer)
        if self.deck and self.deck.get("cards"):
            lo["produce_cards"] = list(self.deck["cards"])  # 基本 2 张由中转层按偶像补（8a3a1e7 069d34c）
            if self.deck.get("unread"):
                logger.warning("偶像之路编成：牌组里有 %d 张亮着但认不出，没写进 produce_cards", self.deck["unread"])
        sig = tower_cache.signature(lo.get("idol_card_id"), fields.get("memory_ratings") or p1.get("memory_ratings"), p1.get("params"))
        if sig:
            lo["formation_signature"] = sig
        self._use_loadout(lo)
        if (cached := tower_cache.save_loadout(lo)) is not None:
            logger.info("偶像之路编成存到 %s（签名 %s）", cached, sig)
        current = {"index": 0, "current": True, "memory_id": None, "params": p1.get("params"), "max_stamina": p1.get("max_stamina"),
                   "deck": lo.get("produce_cards"), "items": [], "drinks": []}  # fmt: skip
        pf = {"tower_id": tower_id, "layer": self.layer, "sub_slots": 0, "candidates": [current],
              "shown_bonus": p1.get("score_bonus_permils"), "shown_stamina": p1.get("max_stamina")}  # fmt: skip
        d = self.core.deciders.decide("TOWER_FORMATION", replace(self.core.s.state, page_fields=pf))
        args = d.action.args or {}
        logger.info("偶像之路编成决策 ← %s：%s", d.source, d.reason)
        if args.get("main") not in (0, None) or args.get("subs"):
            raise ResumeBlocked(f"编成决策要换编成（{args}）：第一次实机不换编成，停下报告。理由：{d.reason}")
        return self._tap(rt, fields.get("challenge"))  # 保持当前编成，直接挑戦する（おまかせ 不点）

    def _use_loadout(self, lo: dict) -> None:
        self.loadout = lo
        self.loadout_path.write_text(json.dumps(lo, ensure_ascii=False), encoding="utf-8")
        os.environ["HIRO_TOWER_LOADOUT"] = str(self.loadout_path)

    def ensure_loadout(self, layer: int | None = None) -> dict | None:
        """这一进程没经过编成页（同编成重试 / 从结果页、名次页、确认页、考试中起跑）：按 tower_id + 层读缓存的 loadout，
        设 HIRO_TOWER_LOADOUT。已经有同一层的就不动；层不知道时取这条路线最近写的一份（层号也从它补上）。"""
        layer = layer or self.layer
        if self.loadout is not None and (layer is None or self.loadout.get("layer") == layer):
            return self.loadout
        lo = tower_cache.load_loadout(self.run.tower_id, layer)
        if lo is None:
            logger.warning("偶像之路：%s 第 %s 层没有缓存的编成，HIRO_TOWER_LOADOUT 不设（出牌只按画面读数）", self.run.tower_id, layer)
            return None
        self._use_loadout(lo)
        self.layer = self.layer or lo.get("layer")
        logger.info("偶像之路：用缓存的编成（第 %s 层，签名 %s）", lo.get("layer"), lo.get("formation_signature"))
        return lo

    def _deck_ids(self) -> dict[str, set[int]] | None:
        """这一场牌组里的卡 id → 强化值（编成页读到的 + 偶像的 2 张基本卡）。牌组没读到、或基本卡查不到（会被当成生成卡跳过，
        顺序就错了）返回 None：分不出生成卡，这场抽牌不记。"""
        cards = (self.loadout or {}).get("produce_cards")
        if not cards:
            return None
        deck: dict[str, set[int]] = {}
        for c in cards:
            cid, _, up = str(c).split("/", 1)[0].partition("+")
            deck.setdefault(cid, set()).add(int(up or 0))
        try:
            from hiro.bench_bridge.tower import master

            basics = master().idol_initial_cards(self.loadout.get("idol_card_id") or "")
        except Exception as e:  # noqa: BLE001  没有主数据
            logger.warning("偶像之路：基本卡查不到（%s），这场抽牌不记", e)
            return None
        if not basics:
            logger.warning("偶像之路：%s 的基本卡查不到，这场抽牌不记", self.loadout.get("idol_card_id"))
            return None
        for cid in basics:
            deck.setdefault(cid, set()).add(0)
        return deck

    def record_draws(self, steps_jsonl: Path, label: str, after_seq: int) -> None:
        """刚考完的那场：从 trace 的手牌变化推抽牌顺序（只留有把握的前缀），等名次页补对手分数再存。"""
        lo = self.loadout or {}
        sig, layer = lo.get("formation_signature"), lo.get("layer") or self.layer
        if not sig or not layer or not self.run.tower_id:
            logger.warning("偶像之路：编成签名 / 层号不全（%s / %s），这场的抽牌不记", sig, layer)
            self.exam_draws = None
            return
        draws, skipped, why = tower_cache.infer_draws(tower_cache.exam_steps(steps_jsonl, label, after_seq), self._deck_ids())
        logger.info("偶像之路第 %s 层抽牌：记下 %d 张、跳过生成卡 %d 张%s", layer, len(draws), skipped, f"，停在：{why}" if why else "（全程）")
        self.exam_draws = {"tower_id": self.run.tower_id, "layer": layer, "sig": sig, "draws": draws, "skipped": skipped}
        self._save_draws([])  # 先存一份；名次页读到对手分数再覆盖

    def _save_draws(self, rivals: list[int]) -> None:
        d = self.exam_draws
        if not d:
            return
        path = tower_cache.save_draws(d["tower_id"], d["layer"], d["sig"], d["draws"], rivals, d["skipped"])
        logger.info("偶像之路抽牌记录 → %s", path)

    def _tap(self, rt, pos):
        if pos is None:
            return STAY  # 按钮还没读到：等下一帧
        rt.device.tap(*pos)
        return DONE

    def on_memory_select(self, rt, f, hit):
        raise ResumeBlocked("进了回忆选择页：第一次实机不换编成，停下（回忆选择页的操作等采样后再接）")

    def on_exam(self, rt, f, hit):
        """考试：同 HifCore.on_exam_entered，只是标签按层、不走 H.I.F 的再挑戦（重试由结果页按 TowerRun 规则定）。"""
        from hiro.exec.exam import run_exam
        from hiro.devices.active import device
        from hiro.vision.ocr import find_text
        from hiro.vision.ui_templates import box, tpl

        core = self.core
        self.ensure_loadout()
        label = f"tower-{self.layer or 'x'}"
        core.rec.log("exam_enter", image=device.screenshot(), exam=label)
        core.s.state.exam_session.label = label
        after_seq = core.s.trace.seq

        def ended(img) -> bool:
            return tpl("Common.ButtonNext").exists(img) and find_text(device.screenshot(), "残りターン", rect=box("InProduce.BoxExamTop")) is None

        run_exam(core.brain, label, core.rec, ended, session=core.s, advisor=core.advisor)
        core.rec.log("exam_end", image=device.screenshot(), exam=label)
        try:
            self.record_draws(Path(core.s.trace.dir) / "steps.jsonl", label, after_seq)
        except Exception:  # noqa: BLE001  记录失败不影响往下打
            logger.exception("偶像之路：抽牌记录失败")
        return DONE

    def on_result(self, rt, f, hit):
        if self.result_handled:
            return STAY  # 刚点过再挑戦 / 一覧に戻る，确认框 / 下一页还没出来：不再算一次
        fields = hit.fields
        layer = fields.get("layer") or self.layer
        self.layer = layer
        self.ensure_loadout(layer)  # 同编成再挑戦不经过编成页：下一场用这一层缓存的编成
        verdict = self.run.after_result(layer, bool(fields.get("cleared")), int(fields.get("stars") or 0))
        logger.info("偶像之路第 %s 层结果：过关=%s 星=%s → %s（%s）", layer, fields.get("cleared"), fields.get("stars"), verdict, self.run.summary())
        if verdict == "stop":
            raise ResumeBlocked(f"偶像之路第 {layer} 层 {self.run.tries.get(layer)} 次都没过关，停下报告（{self.run.summary()}）")
        if verdict == "retry":
            if fields.get("retry") is None:
                raise ResumeBlocked("结果页没读到「再挑戦」，停下")
            rt.device.tap(*fields["retry"])
            self.result_handled = True
            return DONE
        self.done_layers += 1
        if self.done_layers >= self.layers:
            logger.info("偶像之路：打完 %d 层，停（%s）", self.done_layers, self.run.summary())
            self.finished = True
            return END  # 停在结果页，不点（一覧に戻る 交给下一段）
        if fields.get("back") is not None:
            rt.device.tap(*fields["back"])
            self.result_handled = True
        return DONE

    def on_ranking(self, rt, f, hit):
        """考完的名次页：记下名次和各人分数（TowerRun.rankings），点「次へ」到 CLEAR 结果页（重试规则在结果页按星数走）。"""
        fields = hit.fields
        layer = self.layer
        self.run.rankings.setdefault(layer, []).append({"my_rank": fields.get("my_rank"), "rows": fields.get("rows")})
        logger.info("偶像之路第 %s 层名次：第 %s 名（%s）", layer, fields.get("my_rank"), fields.get("rows"))
        if self.exam_draws is not None:
            self._save_draws(rivals(fields, self.idol_name))
            self.exam_draws = None
        return self._tap(rt, fields.get("next"))

    def on_retry_confirm(self, rt, f, hit):
        fields = hit.fields
        self.ensure_loadout()
        if fields.get("cost"):
            raise ResumeBlocked(f"再挑戦确认框上有消耗字样「{fields['cost']}」：不点，停下")
        if fields.get("same") is None or fields.get("ok") is None:
            raise ResumeBlocked("再挑戦确认框没读全（同じ編成で再挑戦 / OK），不点，停下")
        rt.device.tap(*fields["same"])  # 同编成再打（换编成等回忆选择页接上后再做）
        rt.sleep(0.5)
        rt.device.tap(*fields["ok"])
        return DONE

    def handlers(self) -> dict:
        def reopen(fn):
            def h(rt, f, hit):
                self.result_handled = False  # 换到别的页面了：下一次结果页照常处理
                return fn(rt, f, hit)

            return h

        hs = {"TOWER_LIST": self.on_list, "TOWER_LAYERS": self.on_layers, "TOWER_LAYER_INFO": self.on_layer_info,
                "TOWER_FORMATION": self.on_formation, "TOWER_MEMORY_SELECT": self.on_memory_select, "TOWER_EXAM": self.on_exam,
                "TOWER_RANKING": self.on_ranking, "TOWER_RESULT": self.on_result, "TOWER_RETRY_CONFIRM": self.on_retry_confirm}  # fmt: skip
        return {k: (v if k == "TOWER_RESULT" else reopen(v)) for k, v in hs.items()}


def run(args) -> int:
    """跑一段偶像之路。返回退出码：0 打完设定的层数，3 停机交给人。"""
    from hiro.contracts import TraceWriter
    from hiro.devices import active, open_device
    from hiro.loop.session import Session
    from hiro.produce.hif import HifCore
    from hiro.runtime import play
    from hiro.runtime.loop import Runtime
    from hiro.vision.classify import classify

    session = Session(TraceWriter(name=args.trace))
    HifCore.session, HifCore.use_llm, HifCore.llm_spec = session, not args.no_llm, args.llm
    core = HifCore(scenario="qualify", idol=None)
    tp = TowerPlay(core, TowerRun(tower_id=None, max_layer=None), idol_name=args.idol_name, layers=args.layers,
                   loadout_path=Path(session.trace.dir) / "tower-loadout.json")  # fmt: skip
    device = open_device()
    device.connect()
    rt = Runtime(raw_device=device, classify=classify, handlers=tp.handlers(), advance=play.advance, session=session,
                 dialog_words=DIALOG_WORDS)  # fmt: skip
    active.use(rt)
    try:
        rt.run(until=lambda: tp.finished)
        return 0
    except ResumeBlocked as e:
        logger.error("%s", e)
        print(str(e))
        return 3
    finally:
        active.use(None)
        device.close()
        logger.info("偶像之路这一段：%s", tp.run.summary())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="偶像之路（新主循环）")
    ap.add_argument("--idol-name", required=True, help="要打的路线的偶像名（画面上的写法，如 月村手毬）")
    ap.add_argument("--layers", type=int, default=1, help="打完几层就停（缺省 1：第一次实机只打当前最前沿一层）")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--llm", default=os.environ.get("HIRO_LLM"))
    ap.add_argument("--trace", default=None)
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
