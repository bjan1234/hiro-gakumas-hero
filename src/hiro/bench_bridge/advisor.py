"""ExamAdvisor：考试出牌交给 gakumas-bench 的开源算法（缺省 UINet），出错时这一步退回规则。

用户 2026-11-12 决定：考试出牌主要交给 bench 算法，不再调 LLM；默认开。
- 算法：HIRO_BENCH_ALGO，写法同 bench（`uinet`、`uinet:threads=2`、`my.py:Cls`），缺省 uinet。只能用只看画面的算法
  （sees_seed / privileged 的拒绝加载；要 GKMS「世界」的算法拿不到世界，会在决策时出错并退回规则）。
- 关掉：HIRO_BENCH_ADVISOR=0（回到 hiro.defaults.advisor:RuleLLMAdvisor 的行为，含 LLM）；或 HIRO_EXAM_ADVISOR 换别的插件。
- 局面：缺省用画面读数 + 本场跟踪（hiro.bench_bridge.screen）。HIRO_BENCH_OBS=engine 时改用模拟器跟踪的引擎局面
  （hiro.sim.screen_source 挂在 state.sim_game 上），画面能看到的再用画面覆盖（_overlay_screen）。
- 依赖（可选，setup 默认装）：gkbench、gkms-uinet、onnxruntime；UINet 模型按固定提交下载并校验 sha256，
  主数据从引擎的 catalog（我们下载的 gakumasu-diff 快照）导出 9 张表。缺任何一样：开局日志写明原因，整场用规则。
- 退回规则时不调 LLM（RuleLLMAdvisor 去掉 LLM）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hiro.contracts import Action, Candidate, Decision, Preview

logger = logging.getLogger(__name__)
uiobs_log = logging.getLogger("hiro.bench_bridge.uiobs")  # 每步一行 JSON，量大：不想要时把这个 logger 调到 WARNING

UINET_COMMIT = "1201b841828d9874b604f7d48f7b00ddf3b71d95"  # yuzeis/GKMSUINet Ver1.1-Hingebungsvoll（MIT）
UINET_MODEL_URL = f"https://raw.githubusercontent.com/yuzeis/GKMSUINet/{UINET_COMMIT}/model/gkms_uinet.onnx"
UINET_MODEL_SHA256 = "a8addb1a221100dd251b7846cc3ba3898ec3698c9d3b9b35768d5965472ebd5a"
UINET_TABLES = ("ProduceCard", "ProduceCardCustomize", "ProduceCardGrowEffect", "ProduceCardSearch", "ProduceExamEffect",
                "ProduceExamTrigger", "ProduceExamStatusEnchant", "ProduceDrink", "ProduceDrinkEffect")
DEFAULT_ALGO = "uinet"
DECIDE_BUDGET_S = float(os.environ.get("HIRO_BENCH_BUDGET_S", "5"))
# 给算法的局面从哪来：screen（缺省，画面读数 + 本场跟踪）/ engine（模拟器跟踪的引擎局面，画面能看到的再用画面覆盖）。
# 2026-11-12 dmmt1 R1 21.6 万后离线重放 dmmw1：跟踪大多步按画面重建，重建丢了打出的卡挂上的附魔；合成开局还带着
# 模板那局的回忆 / P 道具附魔、山札里有模拟器自己随机的强化。引擎局面反而不如画面跟踪，先默认用画面。
OBS_SOURCE = os.environ.get("HIRO_BENCH_OBS", "screen").strip().lower()


def enabled() -> bool:
    return os.environ.get("HIRO_BENCH_ADVISOR", "1").strip().lower() not in ("0", "false", "off", "no")


def cache_dir() -> Path:
    return Path(os.environ.get("HIRO_BENCH_CACHE") or Path.home() / ".cache" / "hiro" / "bench").expanduser()


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ort_reads_ir10() -> bool:
    import onnxruntime

    parts = [int(x) for x in onnxruntime.__version__.split(".")[:2] if x.isdigit()]
    return tuple(parts) >= (1, 18)


def _convert(src: Path, dst: Path) -> None:
    """原模型 → opset 18（convert_model.py），在 uv 的隔离环境里跑（要 onnx，不装进 hiro 环境）。"""
    import shutil
    import subprocess

    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("onnxruntime < 1.18 读不了 UINet 原模型，转换要用 uv（没找到 uv）")
    script = Path(__file__).with_name("convert_model.py")
    tmp = dst.with_suffix(".part")
    r = subprocess.run([uv, "run", "--isolated", "--no-project", "--with", "onnx", "--with", "numpy", "python", str(script), str(src), str(tmp)],
                       capture_output=True, text=True, timeout=600)  # fmt: skip
    if r.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"UINet 模型转换失败：{(r.stderr or r.stdout).strip()[-400:]}")
    tmp.replace(dst)


def ensure_model(download: bool = True) -> Path:
    """UINet 模型：GKMS_UINET_MODEL 指定的文件；否则缓存目录里按固定提交下载的那份（校验 sha256）。
    onnxruntime < 1.18（KAA 钉在 1.14）读不了原模型：用转换成 opset 18 的那份（第一次用时转换并缓存）。"""
    env = os.environ.get("GKMS_UINET_MODEL")
    if env:
        p = Path(env).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"GKMS_UINET_MODEL 指向的文件不存在：{p}")
        return p
    orig = _download_model(download)
    if _ort_reads_ir10():
        return orig
    conv = orig.with_name(orig.stem + "-opset18.onnx")
    if not conv.is_file():
        if not download:
            raise FileNotFoundError(f"没有转换好的 UINet 模型（{conv}）；运行 python -m hiro.bench_bridge setup")
        _convert(orig, conv)
    return conv


def _download_model(download: bool) -> Path:
    p = cache_dir() / f"gkms_uinet-{UINET_COMMIT[:12]}.onnx"
    if p.is_file() and _sha256(p) == UINET_MODEL_SHA256:
        return p
    if not download:
        raise FileNotFoundError(f"没有 UINet 模型（{p}）；运行 python -m hiro.bench_bridge setup 下载")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    logger.info("下载 UINet 模型 %s", UINET_MODEL_URL)
    with urllib.request.urlopen(UINET_MODEL_URL, timeout=120) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    got = _sha256(tmp)
    if got != UINET_MODEL_SHA256:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"UINet 模型校验失败：sha256 {got[:12]}… ≠ {UINET_MODEL_SHA256[:12]}…")
    tmp.replace(p)
    return p


def _engine_on_path() -> None:
    """把考试引擎（vendor/gakumas-player 里的 gakumas_exam）放进 sys.path：hiro.sim 导入时做这件事。
    实机开局时它早就导入了；`python -m hiro.bench_bridge setup / check` 单独跑时没有，gkbench 导入 gakumas_exam 就失败
    （Windows 上 setup 报 No module named 'gakumas_exam'，模型和主数据都没准备）。"""
    import hiro.sim  # noqa: F401


def ensure_master() -> Path:
    """UINet 读的 9 张主数据表：从考试引擎的 catalog（gakumasu-diff 快照）导出 jsonl，按快照提交号缓存。"""
    env = os.environ.get("GKBENCH_UINET_MASTER")
    if env:
        return Path(env).expanduser()
    _engine_on_path()
    from gakumas_exam.catalog import Catalog

    cat = Catalog()
    try:
        out = cache_dir() / f"uinet-master-{cat.info['commit'][:12]}"
        if all((out / f"{t}.jsonl").is_file() for t in UINET_TABLES):
            return out
        tmp = out.with_name(out.name + ".part")
        tmp.mkdir(parents=True, exist_ok=True)
        for t in UINET_TABLES:
            with (tmp / f"{t}.jsonl").open("w", encoding="utf-8") as f:
                for row in cat.rows(t):
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if out.exists():
            import shutil

            shutil.rmtree(out)
        tmp.replace(out)
        return out
    finally:
        cat.db.close()


def algo_spec() -> str:
    return (os.environ.get("HIRO_BENCH_ALGO") or DEFAULT_ALGO).strip()


def load_algo(spec: str | None = None, *, download: bool = True):
    """按名字加载 bench 算法。uinet 自动带上我们的主数据和模型（spec 里写了 master= / model= 就用写的）。"""
    _engine_on_path()
    from gkbench.algos import make

    spec = spec or algo_spec()
    name, _, rest = spec.partition(":")
    if name == "uinet":
        extra = []
        if "master=" not in rest:
            extra.append(f"master={ensure_master()}")
        if "model=" not in rest:
            extra.append(f"model={ensure_model(download)}")
        spec = name + ":" + ",".join(x for x in [rest, *extra] if x)
    try:
        algo = make(spec)
    except SystemExit as e:  # bench 的 make 用 SystemExit 报参数错
        raise ValueError(str(e)) from None
    if getattr(algo, "sees_seed", False) or getattr(algo, "privileged", False):
        raise ValueError(f"{spec} 要看种子 / 真实局面，实战不能用")
    return algo


def _plan_number(idol: str | None) -> int | None:
    if not idol:
        return None
    try:
        from gakumas_exam.catalog import Catalog

        cat = Catalog()
        try:
            row = cat.one("IdolCard", idol)
        finally:
            cat.db.close()
        plan = (row or {}).get("planType") or ""
        return {"ProducePlanType_Common": 1, "ProducePlanType_Plan1": 2, "ProducePlanType_Plan2": 3, "ProducePlanType_Plan3": 4}.get(plan)
    except Exception:  # noqa: BLE001
        return None


def _customize_ids():
    """(card_id, 强化次数) → 主数据的可定制列表（超过最高等级取最高）。"""
    from gakumas_exam.catalog import Catalog

    cat = Catalog()
    cache: dict = {}

    def get(card_id: str, u: int) -> list:
        k = (card_id, u)
        if k not in cache:
            ids = []
            for v in range(int(u), -1, -1):
                try:
                    row = cat.one("ProduceCard", card_id, v)
                except Exception:  # noqa: BLE001  主数据没有这一级 / 这张卡：再往下找，都没有就当没有定制
                    row = None
                if row is not None:
                    ids = row.get("produceCardCustomizeIds") or []
                    break
            cache[k] = ids
        return cache[k]

    return get


def _overlay_screen(obs: dict, screen: dict, state) -> dict:
    """引擎局面转出的 UIObs 上，画面能看到的一律换成画面的。模拟器合成开局只按画面粗对齐（dmmw1 R1 离线重放）：
    回合属性是模板的占位顺序；手牌强化被模拟器自己的随机支援强化抬高（画面 + 引擎 +++）；やる気 / 好印象 / 分数有偏差。
    引擎只补画面看不到的：山札 / 弃牌 / 除外 / 保留的内容、附魔、其余状态。"""
    for k in ("turn", "limit", "types", "permil"):
        obs["exam"][k] = screen["exam"][k]
    if [c["id"] for c in obs["hand"]] == [c["id"] for c in screen["hand"]]:
        obs["hand"] = [dict(c, u=h["u"], p=h["p"]) for c, h in zip(obs["hand"], screen["hand"])]
    else:
        obs["hand"] = screen["hand"]  # 手牌顺序 / 内容和画面对不上：动作要落到画面，用画面的
    obs["drinks"], obs["legal"] = screen["drinks"], screen["legal"]
    for k, attr in (("score", "score"), ("stamina", "hp"), ("max_stamina", "max_hp"), ("block", "genki")):
        if getattr(state, attr, None) is not None:
            obs["num"][k] = screen["num"][k]
    screen_kinds = {}
    for k, attr in (("aggressive", "motivation"), ("review", "impression")):
        if getattr(state, attr, None) is not None:
            screen_kinds[k] = int(getattr(state, attr))
    if screen_kinds:
        obs["status"] = [x for x in obs["status"] if x[0] not in screen_kinds] + \
            [[k, float(v), -1] for k, v in screen_kinds.items() if v]
    return obs


def _round_defaults(label: str | None, deck: list) -> tuple[dict, dict | None]:
    """画面还没读到时的倍率（R1 记下的 / 参考值），和本战回合属性配额（模拟器合成模板那场的配额，本战每局相同：
    dmmw1、dmmt2 的 R1 都是 Vo4 / Da3 / Vi2、末三回合 Vi → Da → Vo）。选拔考试没有模板，配额给 None。"""
    base = str(label or "").split("#", 1)[0].lower()
    permil, alloc = {}, None
    try:
        if base in ("r1", "r2"):
            from hiro.state.finals_context import CONTEXT
            from hiro.state.knowledge import FINALS_REFERENCE_PERMIL

            permil = {k: v for k, v in (CONTEXT.get("permil") or {}).items() if v} or dict(FINALS_REFERENCE_PERMIL)
        else:
            from hiro.sim.resource import REFERENCE_PERMIL

            permil = dict(REFERENCE_PERMIL)
    except Exception as e:  # noqa: BLE001
        logger.info("参考倍率不可用：%s: %s", type(e).__name__, e)
    if base in ("r1", "r2") and deck:
        try:
            from hiro.sim import interval as iv
            from hiro.sim import resource as rv

            setup, _ = rv.setup_for(base, deck=list(deck), drinks=[], hp=33, max_hp=33, permil=permil or None)
            alloc = (getattr(iv.bare_exam(setup), "meta", None) or {}).get("allocation")
        except Exception as e:  # noqa: BLE001  没有模拟器 / 主数据：未知回合按流向填
            logger.info("本战回合配额不可用：%s: %s", type(e).__name__, e)
    return permil, alloc


def _engine_state(game) -> dict | None:
    """SimGame → 引擎导出局面（Python / Rust 后端同一格式）。"""
    env = getattr(game, "env", None)
    if env is None:
        return None
    rx = getattr(env, "rx", None)
    if rx is not None:
        return json.loads(rx.export_json())
    ex = getattr(env, "ex", None)
    if ex is not None:
        from gakumas_exam.native import export_state

        return export_state(ex)
    return None


class BenchAdvisor:
    """考试每一步：局面 → UIObs → bench 算法 → hiro 动作；不行就这一步用规则（不调 LLM）。"""

    def __init__(self, profile=None, llm=None):
        from hiro.brain.battle import BattleBrain
        from hiro.defaults.advisor import RuleLLMAdvisor

        if enabled():
            # 开着 bench：退回规则的那一步不调 LLM（传 False 免得 RuleLLMAdvisor 去读 HIRO_LLM 建客户端）
            self.rules = RuleLLMAdvisor(profile, llm=False)
            self.rules.brain = BattleBrain(profile, None)
        else:
            self.rules = RuleLLMAdvisor(profile, llm)  # 关掉 bench：就是原来的默认出招（规则 + LLM）
        self.profile = profile
        self.algo = None
        self.load_error: str | None = None
        self.exam: dict = {}
        self.label: str | None = None
        self.tracker = None
        self.began = False
        self.rng = random.Random(0)
        self.stats = {"bench": 0, "rules": 0}
        self.deck: list = []
        self._cz = None
        if not enabled():
            self.load_error = "HIRO_BENCH_ADVISOR=0"
        else:
            try:
                self.algo = load_algo()
                logger.info("考试出牌：bench 算法 %s", algo_spec())
            except Exception as e:  # noqa: BLE001  缺依赖 / 模型下载失败：整场用规则
                self.load_error = f"{type(e).__name__}: {e}"
                logger.warning("bench 算法 %s 加载失败，考试出牌用规则（不调 LLM）：%s", algo_spec(), self.load_error)

    # ---------------------------------------------------------------- 生命周期
    def on_round_start(self, round_no: int, context: dict[str, Any]) -> None:
        from hiro.bench_bridge.screen import ScreenTracker, exam_fields
        from hiro.brain.state import profile_for

        ctx = context or {}
        self.rules.on_round_start(round_no, ctx)
        if enabled():
            self.rules.brain.llm = None
        idol = ctx.get("idol") or (self.profile.idol_id if self.profile else None)
        if idol and (p := profile_for(idol)) is not None:
            self.profile = p
        self.label = ctx.get("exam")
        deck = [(c["card_id"], int(c.get("upgrade") or 0)) if isinstance(c, dict) else tuple(c[:2]) for c in ctx.get("deck") or ()]
        self.deck = [c for c in deck if c and c[0]]
        trend = None
        try:
            from hiro.state.knowledge import idol_trend

            trend = tuple(idol_trend(idol)[1]) if idol else None
        except Exception:  # noqa: BLE001
            trend = None
        self.exam = exam_fields(self.label, idol=idol, plan=_plan_number(idol))
        self.exam["permil_default"], self.exam["allocation"] = _round_defaults(self.label, self.deck)
        ench = items = None
        if self.algo is not None:
            try:
                from hiro.bench_bridge.enchants import Enchants

                ench = self._ench = getattr(self, "_ench", None) or Enchants()
                items = ench.idol_items(idol)
            except Exception as e:  # noqa: BLE001  没有主数据：持续效果不记
                logger.info("持续效果记账不可用：%s: %s", type(e).__name__, e)
        self.tracker = ScreenTracker(self.deck, trend, enchants=ench, items=items)
        self.began = False
        self.rng = random.Random(hash((self.label, round_no)) & 0xFFFFFFFF)
        self.stats = {"bench": 0, "rules": 0}
        if self.algo is None:
            logger.info("[%s] 考试出牌用规则：%s", self.label, self.load_error)

    def on_round_end(self, result: dict[str, Any] | None) -> None:
        logger.info("[%s] 考试出牌统计：bench %d 步，规则 %d 步", self.label, self.stats["bench"], self.stats["rules"])
        self.rules.on_round_end(result)

    # ---------------------------------------------------------------- 决策
    def _obs(self, state, memory, legal: list[Action]) -> tuple[dict, list, str]:
        """UIObs、饮料下标 → 画面槽位、来源（engine / screen）。"""
        from hiro.bench_bridge.screen import from_screen
        from hiro.bench_bridge.uiobs import from_engine

        keys = [a.legal_key() for a in legal]
        self.tracker.observe(state, memory)
        game = getattr(state, "sim_game", None) if OBS_SOURCE == "engine" else None
        if game is not None:
            try:
                eng = _engine_state(game)
                if eng is not None:
                    screen_obs, slot_of = from_screen(state, memory, keys, self.tracker, self.exam)
                    if self._cz is None:
                        self._cz = _customize_ids()
                    obs = from_engine(eng, self.exam, [], customize_ids=self._cz, played=self.tracker.played)
                    return _overlay_screen(obs, screen_obs, state), slot_of, "engine"
            except Exception as e:  # noqa: BLE001
                logger.info("引擎局面转 UIObs 失败，改用画面读数：%s: %s", type(e).__name__, e)
        obs, slot_of = from_screen(state, memory, keys, self.tracker, self.exam)
        return obs, slot_of, "screen"

    def _ctx(self, obs: dict):
        def worlds(k):
            raise RuntimeError("实战没有 GKMS 世界（ctx.worlds 不可用）")

        meta = {"produce_id": self.exam.get("produce"), "step_type": self.exam.get("step"), "plan_type": self.exam.get("plan"),
                "idol_card_id": self.exam.get("idol")}
        return SimpleNamespace(obs=obs, budget=DECIDE_BUDGET_S, loadout={"idol_card_id": self.exam.get("idol")}, meta=meta,
                               rng=self.rng, worlds=worlds, true_session=None, seed=None)

    def _fallback(self, state, memory, previews, legal, why: str) -> Decision:
        self.stats["rules"] += 1
        out = self.rules.decide(state, memory, previews, legal)
        out.warnings.append(f"bench 算法这一步没用上，改用规则：{why}")
        return out

    def decide(self, state: Any, memory: Any, previews: list[Preview] | None, legal: list[Action]) -> Decision:
        if self.algo is None:
            self.stats["rules"] += 1
            return self.rules.decide(state, memory, previews, legal)
        t0 = time.monotonic()
        try:
            obs, slot_of, origin = self._obs(state, memory, legal)
            # 每步给算法的 UIObs 记进运行日志（复盘用：实机局能直接看出 UINet 看到的局面和画面差在哪）
            uiobs_log.info("[%s T%s %s] %s", self.label, getattr(memory, "turn", None), origin,
                           json.dumps(obs, ensure_ascii=False, separators=(",", ":")))
            ctx = self._ctx(obs)
            if not self.began:
                self.algo.begin(ctx)
                self.began = True
            d = self.algo.decide(ctx)
            act = tuple(d.action)
        except Exception as e:  # noqa: BLE001
            logger.warning("bench 算法出错，这一步用规则：%s: %s", type(e).__name__, e)
            return self._fallback(state, memory, previews, legal, f"{type(e).__name__}: {e}")
        if list(act) not in obs["legal"]:
            return self._fallback(state, memory, previews, legal, f"算法给的动作 {list(act)} 不在合法动作 {obs['legal']} 里")
        if act[0] == "play":
            action = Action.play_card(int(act[1]))
            card = next((c for c in state.hand if c.slot == int(act[1])), None)
            what = card.name if card else f"手牌 {act[1]}"
            if card is not None:
                self.tracker.played_card(card)
        elif act[0] == "drink":
            slot = slot_of[int(act[1])]
            action = Action.use_drink(slot)
            what = next((x.name for x in state.drinks if x.slot == slot), f"饮料 {slot}")
        else:
            action = Action.skip()
            what = "结束回合"
        keys = {a.legal_key() for a in legal}
        if action.legal_key() not in keys:
            return self._fallback(state, memory, previews, legal, f"{action.legal_key()} 不在 hiro 的合法动作里")
        self.stats["bench"] += 1
        meta = dict(getattr(d, "meta", None) or {})
        cands = []
        for a, p in (meta.get("top") or [])[:3]:
            try:
                k = a[0]
                ca = Action.play_card(int(a[1])) if k == "play" else Action.use_drink(slot_of[int(a[1])]) if k == "drink" else Action.skip()
                cands.append(Candidate(ca, note=f"概率 {p}"))
            except Exception:  # noqa: BLE001
                continue
        q = meta.get("score_quantiles")
        reason = f"{algo_spec().split(':')[0]}（{'引擎局面' if origin == 'engine' else '画面读数'}）：{what}"
        if q:
            reason += f"；终局分预测中位 {q.get('50%')}"
        return Decision(action=action, reason=reason, source="bench", confidence=None, candidates=cands,
                        seconds=time.monotonic() - t0, decider="battle")
