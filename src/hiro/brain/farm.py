"""刷回忆（メモリー転写）：「初」BAD 育成，目标评价 B（用户 2026-11-21；社区方法见 docs/memory-transcription.md 第二节 ①）。

开关 HIRO_FARM=bad（缺省关）。原理：回忆编成里带一张想转写的技能卡（转写目标），这一局除了它和初始卡 / 偶像固有卡之外
什么卡都不拿，以 B 评价通关；中間試験后的抽选池里只剩目标卡，B 评价能抽到 虹- / 虹+。

这里只放决策规则，接入点：
- 选行动：deciders._action_select_hajime_nia 开头 → pick_action（按周固定日程）；
- 练习课：runtime.hajime 的练习课把出牌顾问包一层 BadLessonAdvisor（离通关线只差 margin 时不再出牌，课程以「刚好没过」结束，
  不掉技能卡）；
- 相談：deciders._hajime_nia_consult → delete_pool（删掉这局拿到的所有卡，除了初始卡 / 固有卡 / 目标卡）。
考试（中間 / 最終）照常打：B 的难点是分数够不够，不是会不会超（社区：参数合计 ≥1500、最终得分 ≥3000 才稳）。

- 收尾：runtime.finish 在回忆结果页调 regen_step：读出生成的回忆带的技能卡，不是目标、还有次数就「再生成」一次
  （确认框里有ジュエル或认不出确认按钮一律キャンセル）。

还没做：租借回忆（程序不会选，玩家自己开局后 resume 接手）、按卡片预演精确卡在通关线下。
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# 13 周日程（社区 ①；第 6 / 13 周是考试，选行动页不出现）。值是这一周要做的事：
# lesson = 审查基准第 1 属性的 SP 课（没有 SP 就普通课）；oikomi = 追い込み（社区：没有 SP，可以拿第 2 属性）；
# rest = 休息；shop_or_outing = 有要删的卡、能进相談就相談，否则外出（第 7 / 8 周不能连着休息两次，第 7 周外出确定不掉卡）
SCHEDULE = {1: "lesson", 2: "rest", 3: "lesson", 4: "rest", 5: "oikomi", 7: "shop_or_outing", 8: "rest",
            9: "lesson", 10: "lesson", 11: "rest", 12: "oikomi"}  # fmt: skip
DEFAULT_MARGIN = 0.4  # 练习课离通关线还差「通关线 × 这个比例」以内就不再出牌（先保守，实机看读数再调）


def mode(env: dict | None = None) -> str | None:
    v = ((env if env is not None else os.environ).get("HIRO_FARM") or "").strip().lower()
    if v in ("", "0", "off"):
        return None
    if v != "bad":
        logger.warning("HIRO_FARM=%r 不认识（现在只有 bad），不刷回忆", v)
        return None
    return v


def margin_ratio(env: dict | None = None) -> float:
    try:
        return min(
            0.9,
            max(0.05, float((env if env is not None else os.environ).get("HIRO_FARM_BAD_MARGIN") or DEFAULT_MARGIN)),
        )
    except ValueError:
        return DEFAULT_MARGIN


def _ranked_attrs(criteria: dict | None) -> list[str]:
    """审查基准三属性按权重从高到低（Vo / Da / Vi）。"""
    if not criteria:
        return []
    norm = {str(k).capitalize(): v for k, v in criteria.items() if v is not None}
    return [a for a in sorted(norm, key=lambda a: -norm[a]) if a in ("Vo", "Da", "Vi")]


def _attr(o: dict) -> str | None:
    a = o.get("attr")
    return str(a).capitalize() if a else None


def pick_action(step: int | None, opts: list[dict], criteria: dict | None, *, has_junk: bool = False,
                shop_ok: bool = True) -> tuple[int, str] | None:  # fmt: skip
    """这一周按日程选哪个选项 → (opts 下标, 理由)；周数不知道 / 日程里没有这一周 / 要的选项不在画面上时 None（交回原来的规则）。"""
    want = SCHEDULE.get(int(step or 0))
    if want is None:
        return None
    ranked = _ranked_attrs(criteria)
    idx = dict(enumerate(opts))

    def first(pred) -> int | None:
        return next((i for i, o in idx.items() if pred(o)), None)

    if want == "lesson":
        lessons = {i: o for i, o in idx.items() if o.get("option") == "training" and not o.get("oikomi")}
        for attr in ranked[:1]:
            for sp in (True, None, False):
                i = next(
                    (i for i, o in lessons.items() if _attr(o) == attr and (sp is None or bool(o.get("sp")) == sp)),
                    None,
                )
                if i is not None:
                    return (
                        i,
                        f"刷回忆 BAD 第 {step} 周：审查基准第 1 的 {attr} {'SP ' if lessons[i].get('sp') else ''}课（故意不通关）",
                    )
        i = next((i for i, o in lessons.items() if o.get("sp")), None)
        if i is None:
            i = next(iter(lessons), None)
        return (
            (i, f"刷回忆 BAD 第 {step} 周：上课（故意不通关；审查基准没读到，按 SP 优先）") if i is not None else None
        )
    if want == "oikomi":
        oik = {i: o for i, o in idx.items() if o.get("option") == "training" and o.get("oikomi")} or {
            i: o for i, o in idx.items() if o.get("option") == "training"
        }
        for attr in ranked[1:2] + ranked[:1]:
            i = next((i for i, o in oik.items() if _attr(o) == attr), None)
            if i is not None:
                return i, f"刷回忆 BAD 第 {step} 周：追い込み {attr}（社区：可以拿第 2 属性，故意不通关）"
        i = next(iter(oik), None)
        return (i, f"刷回忆 BAD 第 {step} 周：追い込み（故意不通关）") if i is not None else None
    if want == "rest":
        i = first(lambda o: o.get("option") == "rest")
        return (i, f"刷回忆 BAD 第 {step} 周：休息（不拿卡）") if i is not None else None
    if want == "shop_or_outing":
        if has_junk and shop_ok and (i := first(lambda o: o.get("option") == "shop")) is not None:
            return i, f"刷回忆 BAD 第 {step} 周：相談，删掉这局拿到的卡（不让它们进抽选池）"
        if (i := first(lambda o: o.get("option") == "outing")) is not None:
            return i, f"刷回忆 BAD 第 {step} 周：外出（第 7 / 8 周不能连着休息，外出确定不掉卡）"
        i = first(lambda o: o.get("option") == "rest")
        return (i, f"刷回忆 BAD 第 {step} 周：休息（没有外出可选）") if i is not None else None
    return None


def junk_cards(cards: list[dict], targets: set[str]) -> list[dict]:
    """这一局拿到的、该删掉的卡（不让它们进回忆抽选池）：不是初始的「○○の基本」、不是偶像固有卡（-ido-）、不是转写目标。
    定制过的、没认出的格不碰。"""
    from hiro.brain.deciders import _is_basic, _is_trouble_card

    out = []
    for c in cards:
        cid = c.get("card_id")
        if not cid or c.get("customized") or "-ido-" in cid or cid in targets or _is_basic(cid):
            continue
        out.append(dict(c, farm_trouble=_is_trouble_card(cid)))
    out.sort(key=lambda c: (not c["farm_trouble"], c.get("index", 0)))  # 眠気等トラブル先删（不删会塞牌组）
    return out


def target_cards(env: dict | None = None) -> set[str]:
    """转写目标：HIRO_FARM_TARGET（逗号分隔，技能卡 id 或卡名，中日文都行）；没设时用回忆编成带进来的卡（HIRO_MEMORY_CARDS / 开局编成方案）。
    11-27 实机：界面里填的是卡名「輝くキミへ」，原来只认 id；没设时的来源还指向已删的 kaa_env，结果目标是空的。"""
    src = env if env is not None else os.environ
    raw = src.get("HIRO_FARM_TARGET") or ""
    if not raw:
        try:
            from hiro.formation_env import MEMORY_CARDS

            return {c for c in MEMORY_CARDS if c}
        except Exception:  # noqa: BLE001
            return set()
    return {cid for c in raw.replace("，", ",").split(",") if (cid := card_id(c.strip()))}


def card_id(name_or_id: str) -> str | None:
    """技能卡 id 原样返回；卡名在资料库里按名字找（完全一致优先，中日文都查；带「+」的强化版去掉 +）。找不到 None（记一条警告）。"""
    s = name_or_id.strip()
    if not s or s.startswith("p_card-"):
        return s or None
    base = s.rstrip("+＋")
    try:
        from hiro.cli.catalog import search

        for lang in ("ja", "zh"):
            hits = [h for h in search(base, kind="cards", lang=lang) if h.get("id")]
            exact = [h for h in hits if (h.get("name") or "").rstrip("+＋") == base]
            if exact or len(hits) == 1:
                return (exact or hits)[0]["id"]
    except Exception as e:  # noqa: BLE001  资料库没下载等
        logger.warning("刷回忆：按卡名找技能卡失败（%s）：%s", s, e)
        return None
    logger.warning("刷回忆：转写目标「%s」在资料库里没找到（填技能卡 id 也行）", s)
    return None


PASSIVE_SAFETY = 1.2  # 好印象自动加分的估计再放大一点（P 道具等会让好印象加成更高）


def impression_gain(impression: int | None, turns: int | None) -> int:
    """好印象 G 层、还剩 T 回合：每回合结束按当前层数加一次参数再减 1 层 → G + (G−1) + … 共 T 项（减到 0 为止）。读不到为 0。"""
    if not impression or not turns or impression <= 0 or turns <= 0:
        return 0
    n = min(int(turns), int(impression))
    return int(n * impression - n * (n - 1) // 2)


class BadLessonAdvisor:
    """练习课的出牌顾问外面包一层：离通关线只差 margin 以内（画面「CLEARまで N」的 N）就跳过回合，不再出牌，
    让这节课以「刚好没过」结束（不掉技能卡）。读不到 N 时照常交给原来的顾问。live 由练习课的结束判断每帧更新。"""

    def __init__(self, inner, live: dict, clear_target, ratio: float):
        self.inner, self.live, self.clear_target, self.ratio = inner, live, clear_target, ratio

    def margin(self) -> float | None:
        t = self.clear_target() if callable(self.clear_target) else self.clear_target
        return None if not isinstance(t, (int, float)) or not t else max(1.0, float(t) * self.ratio)

    def decide(self, state, memory, previews, legal):
        from hiro.contracts import Action, ActionKind, Decision

        left, m = self.live.get("left"), self.margin()
        can_skip = any(getattr(a, "kind", None) is ActionKind.SKIP for a in legal)
        if left is not None and m is not None and can_skip:
            # 11-27 实机（藤田ことね 好印象流）：停手后好印象每回合结束还自动加参数，差 5 停手照样过线、拿了卡。
            # 余量 = 通关线 × 比例 + 之后几回合好印象自动加的分 × PASSIVE_SAFETY
            passive = impression_gain(getattr(state, "impression", None), getattr(state, "remaining_turns", None))
            limit = m + passive * PASSIVE_SAFETY
            if left <= limit:
                extra = f"，之后好印象还会自动加约 {passive}" if passive else ""
                if passive >= left:
                    logger.warning("刷回忆 BAD：离通关差 %s，好印象之后还会自动加约 %s，停手也会过线", left, passive)
                return Decision(Action.skip(), f"刷回忆 BAD：离通关只差 {left}（≤ {limit:.0f}{extra}），不再出牌，这节课以刚好没过结束",
                                "rule", 1.0, decider="battle")  # fmt: skip
        return self.inner.decide(state, memory, previews, legal)

    def __getattr__(self, name):
        return getattr(self.inner, name)


# ---- 回忆结果页：生成的回忆带的技能卡不是转写目标 → 用「再生成」再抽一次（11-27 用户：不对就刷新一次）----

REGEN_MAX = 1  # 一局最多再生成几次（用户：刷新一次）
_regen = {"done": 0, "pending": False, "reported": set()}
REGEN_CONFIRM_WORDS = ("再生成する", "再生成", "決定", "OK", "はい")
REGEN_FREE_WORDS = ("チケット", "無料")  # 确认框里要读到这些之一才确认（用再生成券 / 免费）；否则一律キャンセル


def _txt(b) -> str:
    return (b.text or "").replace(" ", "").strip()


def memory_result(boxes) -> dict | None:
    """回忆结果页（「獲得可能スキルカード」+「再生成」+「次へ」）→ {name, left, regen_xy}；不是这页 None。
    卡名在「獲得可能スキルカード」下面一行（11-27 DMM：标题 y≈685，卡名「リズミカル」y≈730，右边）。"""
    head = next((b for b in boxes if "獲得可能スキルカード" in _txt(b)), None)
    regen = next((b for b in boxes if _txt(b) == "再生成"), None)
    if head is None or regen is None or not any(_txt(b) == "次へ" for b in boxes):
        return None
    hy = head.rect.center.y
    name = next(
        (_txt(b) for b in sorted(boxes, key=lambda b: b.rect.center.y)
         if 20 < b.rect.center.y - hy < 110 and b.rect.center.x > 180 and "獲得" not in _txt(b) and "試験" not in _txt(b)),
        None,
    )  # fmt: skip
    left = None
    for b in boxes:
        if (m := re.search(r"あと(\d+)回", _txt(b))) and abs(b.rect.center.y - regen.rect.center.y) < 80:
            left = int(m.group(1))
    return {"name": name, "left": left, "regen_xy": (int(regen.rect.center.x), int(regen.rect.center.y))}


def _target_names() -> set[str]:
    """转写目标的卡名（日文、中文都收），和结果页读到的卡名比。"""
    names: set[str] = set()
    try:
        from hiro.cli.catalog import search

        for cid in target_cards():
            for lang in ("ja", "zh"):
                for h in search(cid, kind="cards", lang=lang):
                    if h.get("id") == cid and h.get("name"):
                        names.add(str(h["name"]).replace(" ", "").rstrip("+＋"))
    except Exception as e:  # noqa: BLE001
        logger.warning("刷回忆：查转写目标的卡名失败：%s", e)
    return names


def regen_step(boxes) -> tuple[int, int] | None:
    """刷回忆收尾：回忆结果页 / 再生成确认框要点哪里；不归这里管返回 None（照常点「次へ」）。
    只在：刷回忆开着、读到了卡名、不是目标、还有再生成次数、这局还没再生成过 REGEN_MAX 次。
    确认框里有「ジュエル」或认不出确认按钮一律点キャンセル（绝不花钻石）。"""
    if mode() != "bad":
        return None
    texts = [_txt(b) for b in boxes]
    cancel = next((b for b in boxes if "キャンセル" in _txt(b)), None)
    if _regen["pending"] and cancel is not None:
        # 等再生成确认框时，带キャンセル的框一律这里管、不交回收尾的通用分支（那边会点「決定」「OK」，不看费用）。
        # 框是半透明的，底下结果页的字可能还读得到，所以不靠「獲得可能スキルカード」在不在来分。
        if not any("再生成" in t for t in texts):
            # 不是再生成的确认框（点了再生成没弹框、直接重抽了）：不替它点确认，点キャンセル（キャンセル不会花东西）
            logger.info("刷回忆：等再生成确认框时来了别的框，点キャンセル：%s", " ".join(texts)[:120])
            _regen["pending"] = False
            return int(cancel.rect.center.x), int(cancel.rect.center.y)
        _regen["pending"] = False
        free = any(w in t for t in texts for w in REGEN_FREE_WORDS)
        if any("ジュエル" in t or "ジユエル" in t for t in texts) or not free:
            # 白名单：要读到「チケット」「無料」才确认（钻石可能只显示成图标 + 数字，或「ジュエル」读错）
            logger.warning(
                "刷回忆：再生成确认框里没读到免费 / 再生成券（或有钻石），点キャンセル：%s", " ".join(texts)[:160]
            )
            return int(cancel.rect.center.x), int(cancel.rect.center.y)
        ok = next((b for b in boxes if _txt(b) in REGEN_CONFIRM_WORDS and b.rect.center.y > 700), None)
        if ok is None:
            logger.warning("刷回忆：再生成确认框认不出确认按钮，点キャンセル：%s", " ".join(texts)[:160])
            return int(cancel.rect.center.x), int(cancel.rect.center.y)
        logger.info("刷回忆：确认再生成（%s）", " ".join(texts)[:120])
        return int(ok.rect.center.x), int(ok.rect.center.y)
    r = memory_result(boxes)
    if r is None or not r["name"]:
        return None
    _regen["pending"] = False  # 又回到结果页：确认框没弹（或已经过了），不再等它
    targets = _target_names()
    hit = any(t and (t in r["name"] or r["name"] in t) for t in targets)
    key = (r["name"], _regen["done"])
    if key not in _regen["reported"]:
        _regen["reported"].add(key)
        logger.info(
            "刷回忆：生成的回忆带「%s」（目标 %s）%s",
            r["name"],
            "、".join(sorted(targets)) or "?",
            "，刷到了" if hit else "",
        )
    if hit or not targets or _regen["done"] >= REGEN_MAX or not r["left"]:
        return None
    _regen["done"] += 1
    _regen["pending"] = True
    logger.info("刷回忆：不是目标，点「再生成」（还剩 %s 次，这局第 %d 次）", r["left"], _regen["done"])
    return r["regen_xy"]
