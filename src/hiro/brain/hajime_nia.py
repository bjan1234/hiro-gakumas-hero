"""初 / N.I.A 的培育决策（通关档：社区规则，每条带出处）。设计稿 .temp/plans-20261112/初与NIA-决策-设计.md 第四节。

选行动页的选项沿用 H.I.F 的名字：training（课程 / 自主レッスン / 追い込みレッスン，带 attr、sp、hp_cost）、class（授業）、outing、
gift（差し入れ）、shop（相談）、special_guidance、rest；新增 allowance（初的活動支給）、sales（N.I.A 的営業）。
不跟随老师建议（用户定）：选项上的 recommended 不参与选择。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hiro.brain import hajime_nia_rules as hr
from hiro.state import modes

LOW_STAMINA = 8  # 体力低于它时课程周也先休息（初）；N.I.A 的 SP 课程也耗 8
OUTING_POINTS = 100  # 外出和休息二选一时，P 点到这个数就外出 [g8-外出]
TIRED_LOST = 15  # 体力少了这么多（或少了一半）算累 [g8-外出]
SHOP_POINTS = 100  # 相談删卡 / 强化 100P 起 [g8-PRO]
CUSTOMIZE_ALERT_DEFAULT = 49  # 主数据 ProduceSetting.stepCustomizeStartAlertProducePointThreshold（取不到时用）


@dataclass
class Status:
    """选行动要用的状态（从 GameState.produce 拼出来）。"""

    mode: str
    step: int
    stamina: int
    max_stamina: int
    produce_point: int
    params: dict = field(default_factory=dict)
    rest_left: int | None = None
    main_attr: str | None = None
    criteria: dict | None = None  # 下一场考试的审查基准（三属性权重，和为 1）：追い込みレッスン按它选

    @property
    def family(self) -> str | None:
        return modes.family(self.mode)

    @property
    def difficulty(self) -> str | None:
        return modes.MODES[self.mode].difficulty if self.mode in modes.MODES else None

    def main(self) -> str | None:
        if self.main_attr:
            return self.main_attr
        return max(self.params, key=lambda a: self.params[a]) if self.params else None


def exam_criteria(mode: str, idol_card_id: str | None, stage: str) -> dict | None:
    """下一场考试（mid1 / mid2 / final）的审查基准：主数据战斗配置的 vocal / dance / visual 权重，归一成和为 1。查不到 None。
    画面右上角「審査基準」的三根柱就是它（初 REGULAR 实机帧 00886：Vo 最高）。"""
    if not idol_card_id:
        return None
    try:
        st = next((x for x in modes.auditions(mode, idol_card_id) if x.kind == stage), None)
        if st is None:
            return None
        cid = st.tiers[0].battle_config_id
        cfg = next((r for r in modes.master().rows("ProduceExamBattleConfig") if r.get("id") == cid), None)
    except Exception:  # noqa: BLE001
        return None
    if not cfg:
        return None
    w = {"Vo": float(cfg["vocal"]), "Da": float(cfg["dance"]), "Vi": float(cfg["visual"])}
    tot = sum(w.values()) or 1.0
    return {a: v / tot for a, v in w.items()}


def _customize_alert(mode: str) -> int:
    try:
        c = modes.master()
        sid = c.one("Produce", mode)["produceSettingId"]
        return int(c.one("ProduceSetting", sid)["stepCustomizeStartAlertProducePointThreshold"])
    except Exception:  # noqa: BLE001  没有主数据
        return CUSTOMIZE_ALERT_DEFAULT


class _Pick:
    def __init__(self, st: Status, opts: list[dict]):
        self.st, self.opts, self.rules, self.notes = st, opts, [], []

    def use(self, rule_id: str) -> None:
        if rule_id not in self.rules and hr.applies(rule_id, self.st.family, self.st.difficulty):
            self.rules.append(rule_id)

    def idx(self, option: str) -> list[int]:
        return [i for i, o in enumerate(self.opts) if o.get("option") == option]

    def done(self, i: int, why: str) -> tuple[int, str, list[str]]:
        cites = "；".join(hr.cite(r) for r in self.rules)
        return i, f"{why}（{cites}）" if cites else why, list(self.rules)


def _lesson(p: _Pick, cands: list[int], prefer: str) -> int:
    """课程里挑一门：SP 优先，再按 prefer（main = 主属性 / low = 属性最低的）。"""
    st = p.st

    def key(i):
        o = p.opts[i]
        attr = o.get("attr")
        val = st.params.get(attr, 0) if attr else 0
        return (bool(o.get("sp")), (attr == st.main()) if prefer == "main" else -val)

    return max(cands, key=key)


def _rest_ok(p: _Pick) -> bool:
    st = p.st
    if st.stamina >= st.max_stamina:
        p.use("hajime.rest_full")
        return False
    if st.family == modes.NIA and st.rest_left is not None and st.rest_left <= 0:
        p.use("nia.rest_limit")
        return False
    if st.family == modes.HAJIME and st.difficulty == "master" and st.step < 6:
        p.use("hajime.master_rest_week6")
        return False
    return True


def choose_action(st: Status, opts: list[dict]) -> tuple[int, str, list[str]]:
    """选行动页 → (选第几项, 理由, 用到的规则编号)。只处理初 / N.I.A；别的模式抛 ValueError。"""
    if st.family == modes.HAJIME:
        return _hajime(_Pick(st, opts))
    if st.family == modes.NIA:
        return _nia(_Pick(st, opts))
    raise ValueError(f"不是初 / N.I.A：{st.mode}")


def _fallback_order(p: _Pick, order: tuple[str, ...], why: str) -> tuple[int, str, list[str]]:
    rest_ok = None
    for name in order:
        for i in p.idx(name):
            if name == "rest":
                rest_ok = _rest_ok(p) if rest_ok is None else rest_ok
                if not rest_ok:
                    continue
            return p.done(i, f"{why}：{p.opts[i].get('option')}")
    return p.done(0, f"{why}：没有更合适的，选第 1 项")


def _hajime(p: _Pick) -> tuple[int, str, list[str]]:
    st = p.st
    lessons = p.idx("training")
    oikomi = [i for i in lessons if p.opts[i].get("oikomi")]
    if oikomi and st.criteria:
        p.use("hajime.oikomi_bonus")
        i = max(oikomi, key=lambda k: st.criteria.get(p.opts[k].get("attr"), 0))
        a = p.opts[i].get("attr")
        return p.done(i, f"追い込みレッスン选审查基准最高的 {a}（{st.criteria.get(a, 0):.0%}）")
    lost = st.max_stamina - st.stamina
    tired = lost >= TIRED_LOST or st.stamina * 2 <= st.max_stamina
    if (lessons or p.idx("class")) and tired:
        # 累了：课程、授業让位给外出或休息，没有外出就休息（协调 11-17 初 REGULAR 实机：体力 9/30 选 SP 课，游戏弹「体力が低下しています」）
        p.use("hajime.outing_when")
        p.use("hajime.outing_vs_rest")
        outing = p.idx("outing") if not (st.difficulty == "master") else []
        rest_ok = bool(p.idx("rest")) and _rest_ok(p)
        if outing and (st.produce_point >= OUTING_POINTS or not rest_ok):
            return p.done(outing[0], f"体力少了 {lost}（{st.stamina}/{st.max_stamina}），课程让位，去外出")
        if rest_ok:
            return p.done(p.idx("rest")[0], f"体力少了 {lost}（{st.stamina}/{st.max_stamina}），课程让位，休息")
    if lessons:
        if st.stamina < LOW_STAMINA and p.idx("rest") and _rest_ok(p):
            return p.done(p.idx("rest")[0], f"课程周体力只剩 {st.stamina}（< {LOW_STAMINA}），先休息")
        p.use("hajime.lesson_first")
        i = _lesson(p, lessons, "main")
        o = p.opts[i]
        return p.done(i, f"上课程 {o.get('attr')}{' SP' if o.get('sp') else ''}")
    if p.idx("class"):
        p.use("hajime.lesson_first")
        cls = p.idx("class")
        i = next((k for k in cls if p.opts[k].get("attr") == st.main()), cls[0])
        return p.done(i, f"上授業 {p.opts[i].get('attr') or ''}".strip())
    lost = st.max_stamina - st.stamina
    tired = lost >= TIRED_LOST or st.stamina * 2 <= st.max_stamina
    outing_ok = bool(p.idx("outing"))
    if st.difficulty == "master" and outing_ok:
        p.use("hajime.master_outing_avoid")
        outing_ok = False
    if tired:
        p.use("hajime.outing_when")
        p.use("hajime.outing_vs_rest")
        if outing_ok and st.produce_point >= OUTING_POINTS:
            return p.done(p.idx("outing")[0], f"体力少了 {lost}，P 点 {st.produce_point} ≥ {OUTING_POINTS}，去外出")
        if p.idx("rest") and _rest_ok(p):
            return p.done(p.idx("rest")[0], f"体力少了 {lost}，P 点 {st.produce_point} 不到 {OUTING_POINTS}，休息")
        if outing_ok:
            return p.done(p.idx("outing")[0], f"体力少了 {lost}，休息不了，去外出")
    order = ["allowance", "gift"]
    if st.produce_point >= SHOP_POINTS:
        order.append("shop")
    if outing_ok:
        order.append("outing")
    order += ["shop", "rest", "outing"]  # 最后的 outing：MASTER 不推荐，但实在没别的可选
    return _fallback_order(p, tuple(dict.fromkeys(order)), "没有课程 / 授業")


def _nia(p: _Pick) -> tuple[int, str, list[str]]:
    st = p.st
    lessons = p.idx("training")
    if lessons:
        p.use("nia.lesson_sp")
        ok = [i for i in lessons if p.opts[i].get("hp_cost") is None or st.stamina > int(p.opts[i]["hp_cost"])]
        if len(ok) < len(lessons):
            p.use("nia.lesson_stamina")
        if ok:
            i = _lesson(p, ok, "low")
            o = p.opts[i]
            return p.done(i, f"上自主レッスン {o.get('attr')}{' SP' if o.get('sp') else ''}（缺的属性优先）")
        if p.idx("rest") and _rest_ok(p):
            return p.done(p.idx("rest")[0], f"体力 {st.stamina} 上不了课程，休息")
    if p.idx("sales"):
        p.use("nia.sales_cost")
        return p.done(p.idx("sales")[0], "去营业（场所另选）")
    if p.idx("special_guidance") and st.produce_point > _customize_alert(st.mode):
        return p.done(p.idx("special_guidance")[0], f"P 点 {st.produce_point} 够定制，进特別指導")
    if st.stamina <= LOW_STAMINA and p.idx("rest") and _rest_ok(p):
        return p.done(p.idx("rest")[0], f"体力 {st.stamina} 太低，休息")
    order: list[str] = []
    if st.difficulty == "master":
        p.use("nia.outing_default")
        order.append("outing")
    elif st.stamina * 2 <= st.max_stamina:
        order.append("outing")
    order += ["gift"]
    if st.produce_point >= SHOP_POINTS:
        order.append("shop")
    order += ["outing", "special_guidance", "shop", "rest"]
    return _fallback_order(p, tuple(dict.fromkeys(order)), "没有课程 / 营业")


# ---------------------------------------------------------------- 外出 / 授業
# 选项是结构化的 page_fields.choices：{index, text, cost_p, cost_hp, trouble, attr?}（同 H.I.F 的识别格式）。

ATTR_WORDS = {"Vo": ("ボーカル", "Vo"), "Da": ("ダンス", "Da"), "Vi": ("ビジュアル", "Vi")}


def _affordable(st: Status, c: dict) -> bool:
    return int(c.get("cost_p") or 0) <= st.produce_point


def choose_outing(st: Status, choices: list[dict]) -> tuple[int, str, list[str]]:
    """外出三选一 → (choices 里的 index, 理由, 规则)。"""
    p = _Pick(st, choices)
    chs = sorted(choices, key=lambda c: c["index"])
    ok = [c for c in chs if _affordable(st, c)] or chs[-1:]
    if st.family == modes.NIA and st.difficulty == "master" and len(chs) == 3:
        p.use("nia.outing_order")
        top, mid, low = chs
        is_change = "チェンジ" in (mid.get("text") or "")
        order = [low, mid, top] if not is_change else [low, top, mid]
        c = next((c for c in order if _affordable(st, c)), ok[0])
        return p.done(c["index"], f"外出选{'下中上'[[low, mid, top].index(c)] if c is not mid or not is_change else '中（换卡）'}，P 点 {st.produce_point}")
    if st.family == modes.NIA and len(chs) == 3:
        p.use("nia.outing_middle")
        c = chs[1] if _affordable(st, chs[1]) else ok[0]
        return p.done(c["index"], "外出选中间那项" if c is chs[1] else "中间那项 P 点不够，选买得起的")
    p.use("hajime.outing_spend")
    tired = (st.max_stamina - st.stamina) >= TIRED_LOST or st.stamina * 2 <= st.max_stamina
    c = max(ok, key=lambda c: int(c.get("cost_p") or 0)) if tired else min(ok, key=lambda c: int(c.get("cost_p") or 0))
    return p.done(c["index"], f"{'体力少了，选买得起的最贵一档' if tired else '体力还够，选花得最少的一档'}（{int(c.get('cost_p') or 0)}P）")


def _attr_of(c: dict) -> str | None:
    if c.get("attr"):
        return c["attr"]
    text = c.get("text") or ""
    return next((a for a, words in ATTR_WORDS.items() if any(w in text for w in words)), None)


def choose_study(st: Status, choices: list[dict]) -> tuple[int, str, list[str]]:
    """授業三选一：不选「トラブル追加」（加眠気），答主属性；体力不够其它项的消耗时才选トラブル。"""
    p = _Pick(st, choices)
    chs = sorted(choices, key=lambda c: c["index"])
    trouble = [c for c in chs if c.get("trouble")]
    plain = [c for c in chs if not c.get("trouble")]
    if trouble:
        p.use("hajime.study_avoid_trouble")
    can = [c for c in plain if int(c.get("cost_hp") or 0) <= st.stamina]
    if not can and trouble:
        return p.done(trouble[0]["index"], f"体力 {st.stamina} 不够其它项的消耗，只能选トラブル追加")
    pool = can or plain or chs
    main = st.main()
    c = next((c for c in pool if _attr_of(c) == main), pool[0])
    return p.done(c["index"], f"授業答主属性 {main}" if _attr_of(c) == main else "授業：没认出主属性那项，选第一个不加眠気的")


# ---------------------------------------------------------------- N.I.A 营业 / 试镜选档
# 页面字段（和平台约定，采样后可能调整）：
#   NIA_SALES_PLACE  page_fields.places  = [{index, kind: resort|local|corporate|commercial, hp_cost, name?}]
#   NIA_SALES_EVENT  page_fields.choices = [{index, attr?, text?}]
#   NIA_AUDITION_SELECT page_fields.votes, page_fields.tiers = [{index, number, vote_need, locked}]
SALES_KEEP_STAMINA = 8  # 营业后体力要留到 8 以上（SP 课程耗 8）[g8-NIAM]
KIND_NAME = {"resort": "绿（リゾート）", "local": "黄（自治体）", "corporate": "青（企業）", "commercial": "紫（商業）"}


def choose_sales_place(st: Status, places: list[dict], drinks: list | None = None) -> tuple[int, str, list[str]]:
    """营业场所 → (places 里的 index, 理由, 规则)。"""
    p = _Pick(st, places)
    by = {pl.get("kind"): pl for pl in places}
    p.use("nia.sales_cost")

    def after(pl):
        return st.stamina - int(pl.get("hp_cost") or 0)

    if st.difficulty == "master" and drinks is not None and len(drinks) < 2 and "corporate" in by:
        p.use("nia.sales_corporate_drinks")
        return p.done(by["corporate"]["index"], f"考试饮料只有 {len(drinks)} 瓶，去{KIND_NAME['corporate']}拿饮料")
    good = [by[k] for k in ("commercial", "local") if k in by and after(by[k]) >= SALES_KEEP_STAMINA]
    p.use("nia.sales_yellow_purple")
    if good:
        want = "commercial" if st.produce_point >= SHOP_POINTS else "local"
        pl = next((x for x in good if x.get("kind") == want), good[0])
        p.use("nia.sales_purple" if pl.get("kind") == "commercial" else "nia.sales_yellow")
        why = f"体力 {st.stamina} 去完还剩 {after(pl)}，P 点 {st.produce_point}"
        return p.done(pl["index"], f"营业去{KIND_NAME[pl['kind']]}（{why}）")
    p.use("nia.sales_green_low")
    for k in ("resort", "corporate"):
        if k in by:
            return p.done(by[k]["index"], f"体力 {st.stamina} 去黄 / 紫会掉到 {SALES_KEEP_STAMINA} 以下，去{KIND_NAME[k]}")
    pl = min(places, key=lambda x: int(x.get("hp_cost") or 0))
    return p.done(pl["index"], "没认出场所种类，选耗体力最少的一个")


def choose_sales_event(st: Status, choices: list[dict]) -> tuple[int, str, list[str]]:
    """营业事件的选项：选缺的那项属性 [g8-NIA]；认不出属性时选第一个。"""
    p = _Pick(st, choices)
    p.use("nia.sales_choice_fill")
    with_attr = [(c, _attr_of(c)) for c in choices]
    with_attr = [(c, a) for c, a in with_attr if a]
    if not with_attr:
        return p.done(min(c["index"] for c in choices), "营业选项认不出属性，选第一个")
    c, a = min(with_attr, key=lambda x: st.params.get(x[1], 0))
    return p.done(c["index"], f"营业选项补最缺的属性 {a}（{st.params.get(a, 0)}）")


def choose_audition(st: Status, votes: int | None, tiers: list[dict], *, failed: int = 0) -> tuple[int, int | None, str, list[str]]:
    """试镜选档 → (tiers 里的 index, 档位编号 audition_number, 理由, 规则)。
    通关档（设计稿第六节，模拟估过关率之前）：选投票够得上、没锁的最高档（参考 MaaGakumasu ProduceChooseMirrorAuto）；
    这一场失败过 failed 次就往下降 failed 档（协调 11-17：N.I.A 失败可以降档），降到最低档为止。"""
    ok = [t for t in tiers if not t.get("locked") and (votes is None or int(t.get("vote_need") or 0) <= int(votes))]
    if not ok:
        t = min(tiers, key=lambda t: int(t.get("vote_need") or 0))
        return t["index"], t.get("number"), "没有解锁的档位（读数可能不全），选门槛最低的一档", []
    ok.sort(key=lambda t: -int(t.get("number") or t.get("vote_need") or 0))
    k = min(max(0, int(failed)), len(ok) - 1)
    t = ok[k]
    need = int(t.get("vote_need") or 0)
    why = f"投票 {votes:,}" if votes is not None else "投票数没读到"
    tail = f"，失败过 {failed} 次，降 {k} 档" if failed else ""
    return t["index"], t.get("number"), f"选第 {t.get('number')} 档（门槛 {need:,}，{why}，够得上的最高档{tail}）[参考 MaaGakumasu]", []


# ---------------------------------------------------------------- N.I.A 试镜后的 P 道具三选一（走 SELECT_PITEM，平台 11-17）


def choose_nia_pitem(st: Status, items: list[dict], plan: str | None = None) -> tuple[int | None, str, list[str]]:
    """只覆盖攻略写明白的两种（其余返回 None，交回原有 select_pitem / LLM）：
    PRO：アノマリー以外选 N.I.Aワッペン [ww-NIA]；MASTER：パスケース（补 P 点，配自治体营业）[ww-NIAM]。按名字匹配。"""
    p = _Pick(st, items)
    names = [str(it.get("name") or "") for it in items]
    if st.difficulty == "pro" and plan != "ProducePlanType_Plan3":
        hit = next((i for i, n in enumerate(names) if "ワッペン" in n), None)
        if hit is not None:
            p.use("nia.pitem_wappen")
            return p.done(hit, f"试镜后的 P 道具选 {names[hit]}")
    if st.difficulty == "master":
        hit = next((i for i, n in enumerate(names) if "パスケース" in n), None)
        if hit is not None:
            p.use("nia.pitem_passcase")
            p.use("nia.pitem_no_best")
            i, reason, rules = p.done(hit, f"试镜后的 P 道具选 {names[hit]}（三种没有最强的，P 点最缺）")
            return i, reason, rules
    return None, "N.I.A P 道具：攻略没写明，交回原有规则", []
