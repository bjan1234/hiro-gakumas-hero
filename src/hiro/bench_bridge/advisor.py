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


# 偶像之路（tower-* 场次）的出牌算法：用户 2026-11-14 定「偶像之塔这里我们用 gnrpa 去搜索吧，这一块就不要强制性使用 uinet」。
# HIRO_TOWER_ALGO 写法同 HIRO_BENCH_ALGO（包.模块:类名[:参数]，bench Algorithm 接口：begin(ctx) / decide(ctx) → Decision）；
# 缺省 TOWER_DEFAULT_ALGO = Rust GNRPA（hiro.search.tower_algo）。加载失败（Rust 后端没装 / 没有 search、plan_many）时用 H.I.F
# 那个算法（uinet）兜底，每步决策的理由里写明「兜底」和原因。
TOWER_DEFAULT_ALGO = "hiro.search.tower_algo:TowerGnrpa"


def tower_algo_spec() -> str:
    return (os.environ.get("HIRO_TOWER_ALGO") or TOWER_DEFAULT_ALGO).strip()


def exam_search_algo_spec() -> str:
    """初 / N.I.A 场次的出牌算法（HIRO_EXAM_SEARCH_ALGO）；缺省空 = 用 H.I.F 那个（uinet）。"""
    return (os.environ.get("HIRO_EXAM_SEARCH_ALGO") or "").strip()


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
    if base.startswith(("tower", "hajime", "nia")):  # 偶像之路 / 初 / N.I.A：倍率由编成定（编成给了就用编成的），没有 H.I.F 的参考值
        return permil, alloc
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


def _audition_number(label: str | None) -> int | None:
    """标签 tag 里的试镜档位：nia-mid1#audition-2 → 2（平台 11-17 约定）。"""
    for tag in str(label or "").split("#")[1:]:
        k, _, v = tag.partition("-")
        if k == "audition" and v.isdigit():
            return int(v)
    return None


def _exam_loadout(ctx: dict) -> dict | None:
    """初 / N.I.A 这一场的编成：context 的 exam_loadout，或 HIRO_EXAM_LOADOUT 指的 JSON 文件（bench 题存档或编成本身）。没有就 None。"""
    if isinstance(ctx.get("exam_loadout"), dict):
        return ctx["exam_loadout"]
    path = os.environ.get("HIRO_EXAM_LOADOUT")
    if not path:
        return None
    try:
        doc = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("HIRO_EXAM_LOADOUT=%s 读不了：%s", path, e)
        return None
    return doc.get("loadout", doc)


def _tower_loadout(ctx: dict) -> dict | None:
    """偶像之路这一场的编成（gkms.exam_loadout.v1）：context 的 tower_loadout，或 HIRO_TOWER_LOADOUT 指的 JSON 文件
    （编成决策写出来、驱动设好）。没有就 None（只靠画面）。"""
    if isinstance(ctx.get("tower_loadout"), dict):
        return ctx["tower_loadout"]
    path = os.environ.get("HIRO_TOWER_LOADOUT")
    if not path:
        return None
    try:
        doc = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("HIRO_TOWER_LOADOUT=%s 读不了：%s", path, e)
        return None
    return doc.get("loadout", doc)  # 题目存档（带 loadout）或编成本身都行


def tower_cache_dir() -> Path:
    return Path(os.environ.get("HIRO_TOWER_CACHE") or Path.home() / ".cache" / "hiro" / "tower").expanduser()


def known_draws(loadout: dict | None) -> list | None:
    """偶像之路同一编成重试时，上一次挑战在画面上看到的抽牌顺序（用户 2026-11-14 定：可以交给搜索；只限偶像之路同一编成）。
    记录由执行层写在 <HIRO_TOWER_CACHE>/<tower_id>-<layer>-<编成签名>.json：
    {"tower_id", "layer", "formation_signature", "draws": [{"id", "u"}, …（按抽到的先后，跨回合）]}。
    编成签名（主 / サブ1 / サブ2 回忆按顺序）由编成页写进 loadout 的 formation_signature；对不上、没记录或格式不对返回 None。"""
    lo = loadout or {}
    sig, tower, layer = lo.get("formation_signature"), lo.get("tower_id"), lo.get("layer")
    if not (sig and tower and layer):
        return None
    path = tower_cache_dir() / f"{tower}-{int(layer)}-{sig}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if doc.get("formation_signature") != sig or doc.get("tower_id") != tower or int(doc.get("layer") or 0) != int(layer):
        logger.warning("偶像之路抽牌记录 %s 和本场编成对不上，不用", path)
        return None
    draws = [{"id": d["id"], "u": int(d.get("u") or 0)} for d in doc.get("draws") or () if isinstance(d, dict) and d.get("id")]
    return draws or None


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
        self.algo = None  # H.I.F 的算法（HIRO_BENCH_ALGO，缺省 uinet）；也是偶像之路的兜底
        self.round_algo = None  # 这一场用的算法（偶像之路场次可能是 HIRO_TOWER_ALGO）
        self.round_name = ""  # 这一场算法的名字（写进决策理由）
        self.round_note = ""  # 兜底说明：偶像之路没用上指定算法时写原因
        self._tower_algos: dict = {}  # spec → 算法或加载失败的说明（同一进程多场只载一次）
        self.tower_loadout: dict | None = None
        self.exam_loadout: dict | None = None
        self.known_draws: list | None = None
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
        self.tower_loadout = None
        self.known_draws = None
        if str(self.label or "").lower().startswith("tower") and (lo := _tower_loadout(ctx)) is not None:
            from hiro.bench_bridge.screen import tower_context

            self.tower_loadout = lo  # 搜索类算法（GNRPA）要整份编成：ctx.loadout
            self.known_draws = known_draws(lo)
            if self.known_draws:
                logger.info("[%s] 同一编成重试：上一次看到的抽牌顺序 %d 张交给算法（ctx.known_draws）", self.label, len(self.known_draws))
            tc = tower_context(lo)
            self.exam.update({k: tc[k] for k in ("turns", "permil_fixed", "max_stamina") if tc[k]})
            self.exam["idol"] = tc["idol"] or self.exam.get("idol")
            if not self.deck and tc["deck"]:
                self.deck = list(tc["deck"])
            logger.info("[%s] 偶像之路编成：%d 回合，倍率 %s，最大体力 %s，开局牌组 %d 张", self.label, tc["turns"] or 0,
                        tc["permil_fixed"], tc["max_stamina"], len(self.deck))  # fmt: skip
        number = _audition_number(self.label)
        lo = _exam_loadout(ctx) if str(self.label or "").lower().startswith(("hajime", "nia")) else None
        if lo is not None and number and not lo.get("audition_number"):
            lo = {**lo, "audition_number": number}  # 平台在标签里带的档位（nia-mid1#audition-2）
        self.exam_loadout = lo
        if lo is None and number and str(self.label or "").lower().startswith(("hajime", "nia")):
            from hiro.bench_bridge.screen import audition_context

            try:
                ac = audition_context(self.label, idol, number)
            except Exception as e:  # noqa: BLE001  查不到：只靠画面
                logger.warning("[%s] 档位 %s 查不到审查基准：%s: %s", self.label, number, type(e).__name__, e)
            else:
                self.exam["crit"], self.exam["permil_default"], self.exam["allocation"] = ac["crit"], {}, None
                if ac["turns"]:
                    self.exam["turns"] = ac["turns"]
        if lo is not None:
            from hiro.bench_bridge.screen import exam_context, exam_fields

            try:
                xc = exam_context(lo)
            except Exception as e:  # noqa: BLE001  查不到这场试镜：只靠画面
                logger.warning("[%s] 编成换算失败，只靠画面读数：%s: %s", self.label, type(e).__name__, e)
            else:
                idol = xc["idol"] or idol
                self.exam = exam_fields(self.label, idol=idol, plan=_plan_number(idol), crit=xc["crit"], produce=xc["produce"])
                self.exam["permil_default"], self.exam["allocation"] = {}, None
                self.exam.update({k: xc[k] for k in ("turns", "permil_fixed", "max_stamina") if xc[k]})
                if not self.deck and xc["deck"]:
                    self.deck = list(xc["deck"])
                logger.info("[%s] 编成：%s 回合，审查基准 %s，倍率 %s，最大体力 %s，开局牌组 %d 张", self.label, xc["turns"], xc["crit"],
                            xc["permil_fixed"], xc["max_stamina"], len(self.deck))  # fmt: skip
        ench = items = None
        if self.algo is not None:
            try:
                from hiro.bench_bridge.enchants import Enchants

                ench = self._ench = getattr(self, "_ench", None) or Enchants()
                items = ench.idol_items(idol)
            except Exception as e:  # noqa: BLE001  没有主数据：持续效果不记
                logger.info("持续效果记账不可用：%s: %s", type(e).__name__, e)
        self.tracker = ScreenTracker(self.deck, trend, enchants=ench, items=items)
        self._pick_algo()
        self.began = False
        self.rng = random.Random(hash((self.label, round_no)) & 0xFFFFFFFF)
        self.stats = {"bench": 0, "rules": 0}
        if self.algo is None:
            logger.info("[%s] 考试出牌用规则：%s", self.label, self.load_error)

    def _pick_algo(self) -> None:
        """这一场用哪个算法：偶像之路用 HIRO_TOWER_ALGO（加载失败或没配置就用 H.I.F 的算法兜底，写明原因），其余用 H.I.F 的。"""
        self.round_algo, self.round_name, self.round_note = self.algo, algo_spec().split(":")[0], ""
        label = str(self.label or "").lower()
        if not enabled():
            return
        if label.startswith(("hajime", "nia")):
            # 初 / N.I.A：HIRO_EXAM_SEARCH_ALGO 设了才走搜索（如 hiro.search.exam_algo:ExamGnrpa，自己按 UIObs 对齐引擎局面，
            # 不要 screen_source 跟踪）；缺省不设 = uinet（行为变化开关默认关：bench 上 GNRPA 还只比 uinet 略好，目标没按场次填）
            spec = exam_search_algo_spec()
            if not spec:
                return
            what = "初 / N.I.A"
        elif label.startswith("tower"):
            spec, what = tower_algo_spec(), "偶像之路"
        else:
            return
        if not spec:
            self.round_note = "偶像之路指定算法（GNRPA）还没接上，HIRO_TOWER_ALGO 未设"
        else:
            got = self._tower_algos.get(spec)
            if got is None:
                try:
                    got = load_algo(spec)
                except Exception as e:  # noqa: BLE001  缺依赖 / 写错：兜底
                    got = f"{type(e).__name__}: {e}"
                self._tower_algos[spec] = got
            if isinstance(got, str):
                self.round_note = f"{what}指定算法 {spec} 加载失败（{got}）"
            else:
                self.round_algo, self.round_name = got, spec.split(":")[-1] if ":" in spec else spec
                logger.info("[%s] %s出牌：%s", self.label, what, spec)
                return
        logger.warning("[%s] %s，用 %s 兜底", self.label, self.round_note, self.round_name)

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
        full = self.tower_loadout or self.exam_loadout  # 搜索类算法要整份编成（偶像之路 / 初 / N.I.A）
        loadout = dict(full) if full else {"idol_card_id": self.exam.get("idol")}
        return SimpleNamespace(obs=obs, budget=DECIDE_BUDGET_S, loadout=loadout, meta=meta, known_draws=self.known_draws,
                               rng=self.rng, worlds=worlds, true_session=None, seed=None)  # fmt: skip

    def _fallback(self, state, memory, previews, legal, why: str) -> Decision:
        self.stats["rules"] += 1
        out = self.rules.decide(state, memory, previews, legal)
        out.warnings.append(f"bench 算法这一步没用上，改用规则：{why}")
        return out

    def decide(self, state: Any, memory: Any, previews: list[Preview] | None, legal: list[Action]) -> Decision:
        algo = self.round_algo if self.round_algo is not None else self.algo
        if algo is None:
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
                algo.begin(ctx)
                self.began = True
            d = algo.decide(ctx)
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
            dv = next((x for x in state.drinks if x.slot == slot), None)
            what = dv.name if dv is not None else f"饮料 {slot}"
            if dv is not None:
                self.tracker.drank(getattr(dv, "drink_id", None))
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
        name = self.round_name or algo_spec().split(":")[0]
        reason = f"{name}（{'引擎局面' if origin == 'engine' else '画面读数'}）：{what}"
        if self.round_note:
            reason = f"{name}（兜底：{self.round_note}；{'引擎局面' if origin == 'engine' else '画面读数'}）：{what}"
        if q:
            reason += f"；终局分预测中位 {q.get('50%')}"
        return Decision(action=action, reason=reason, source="bench", confidence=None, candidates=cands,
                        seconds=time.monotonic() - t0, decider="battle")
