"""hiro usage …：模型调用的 token 用量与花费（设计稿 docs/ryugi/specs/2026-11-25-token-usage-design.md §4，逻辑参考 ccusage）。

都是只读命令：读 HIRO_HOME/usage/*.jsonl（流水账）和各任务的 jobs/<id>/usage.json；桌面「用量」插件和对话助手都调这些。
"""

from __future__ import annotations

import json

from hiro.cli.home import hiro_home
from hiro.cli.registry import Arg, Risk, command
from hiro.usage import ledger
from hiro.usage import report as usage_report

_RANGE = (
    Arg("--since", "从这一天起（YYYY-MM-DD，含）"),
    Arg("--until", "到这一天为止（YYYY-MM-DD，含）"),
    Arg("--breakdown", "每组再按模型拆", type="bool"),
)


def _rows(a: dict | None = None) -> list[dict]:
    rows = ledger.read_rows(hiro_home() / "usage")
    a = a or {}
    if a.get("since"):
        rows = [r for r in rows if (r.get("ts") or "")[:10] >= a["since"]]
    if a.get("until"):
        rows = [r for r in rows if (r.get("ts") or "")[:10] <= a["until"]]
    return rows


def _table(rows: list[dict], key: str | None, breakdown: bool = False) -> dict:
    prices = usage_report.load_prices()
    (totals,) = usage_report.summarize(rows, prices=prices) or [{"key": "all", "calls": 0}]
    totals.pop("key", None)
    return {"rows": usage_report.summarize(rows, key=key, breakdown=breakdown, prices=prices), "totals": totals,
            "prices_checked": prices.get("checked")}  # fmt: skip


@command(
    "usage daily",
    Risk.READ,
    "模型用量按天汇总：调用次数、token（输入 / 输出 / 缓存读 / 缓存写）、花费（按币种）。",
    args=_RANGE,
)
def _daily(a: dict) -> dict:
    return _table(_rows(a), "day", bool(a.get("breakdown")))


@command("usage monthly", Risk.READ, "模型用量按月汇总（同 usage daily）。", args=_RANGE)
def _monthly(a: dict) -> dict:
    return _table(_rows(a), "month", bool(a.get("breakdown")))


@command("usage job", Risk.READ, "一局的模型用量：合计、按来源（决策 / 兜底）和模型拆、每次调用一行。",
         args=(Arg("job", "任务编号（hiro run status 里的 id）", required=True),))  # fmt: skip
def _job(a: dict) -> dict:
    saved = hiro_home() / "jobs" / str(a["job"]) / "usage.json"
    if saved.is_file():  # 局结束时定下来的那份
        return json.loads(saved.read_text(encoding="utf-8"))
    return usage_report.job_usage(str(a["job"]), _rows())


@command("usage chat", Risk.READ, "对话助手的模型用量，按对话分组。", args=(Arg("--thread", "只看这个对话"),))
def _chat(a: dict) -> dict:
    rows = [r for r in _rows() if r.get("source") == "chat" and (not a.get("thread") or r.get("thread") == a["thread"])]
    return _table(rows, "thread")


@command("usage recent", Risk.READ, "最近几局的模型用量（每局一行：模式、偶像、调用次数、token、花费）。",
         args=(Arg("--limit", "最多几局（缺省 20）", type="int"),))  # fmt: skip
def _recent(a: dict) -> dict:
    out = []
    jobs = hiro_home() / "jobs"
    for d in sorted(jobs.glob("*/usage.json"), reverse=True) if jobs.is_dir() else []:
        try:
            u = json.loads(d.read_text(encoding="utf-8"))
            meta_p = d.parent / "job.json"
            meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.is_file() else {}
        except ValueError:
            continue
        out.append({"job": d.parent.name, "kind": meta.get("kind"), "summary": meta.get("summary"),
                    "params": meta.get("params") or {}, "started_at": meta.get("started_at"),
                    **{k: u.get(k) for k in ("calls", "total", "cost", "subscription_usd", "unpriced", "no_usage")}})  # fmt: skip
        if len(out) >= (a.get("limit") or 20):
            break
    return {"jobs": out, "prices_checked": usage_report.load_prices().get("checked")}
