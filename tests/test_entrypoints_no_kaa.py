"""去 KAA 验收：初星助手能启动的每个任务（hiro.cli.jobs.KINDS）的入口模块 / 脚本，导入时都不加载 kaa / kotonebot。

每个入口在单独的子进程里导入（脚本按文件导入，不当 __main__ 跑），导入完看 sys.modules。
入口模块缺 play 组依赖导入不了时跳过（CI 只装 dev 组）；缺的是 kaa / kotonebot 本身就算失败。
"""

import json
import subprocess
import sys
from pathlib import Path

from hiro.cli import jobs

import pytest

ROOT = Path(__file__).resolve().parents[1]
PARAMS = {"command": "new", "idol": "x", "mode": "qualify", "scenario": "hif", "items": "", "seconds": 1}

PROBE = r"""
import importlib.util, json, sys
kind, target = sys.argv[1], sys.argv[2]
try:
    if kind == "module":
        importlib.import_module(target)
    else:
        sys.path.insert(0, str(__import__("pathlib").Path(target).parent))
        spec = importlib.util.spec_from_file_location("entry_under_test", target)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    err = None
except ModuleNotFoundError as e:
    err = e.name or str(e)
loaded = sorted(m for m in sys.modules if m.split(".")[0] in ("kaa", "kotonebot"))
print(json.dumps({"missing": err, "loaded": loaded}))
"""


def _entries():
    out = []
    for name, k in jobs.KINDS.items():
        argv = k.argv(dict(PARAMS), Path("/tmp/job"))
        if argv[1] == "-c":
            continue  # selftest：内联脚本，不导入 hiro 的入口
        if argv[1] == "-m":
            out.append(pytest.param("module", argv[2], id=name))
        else:
            out.append(pytest.param("script", argv[1], id=name))
    return out


def test_every_kind_has_an_entry():
    assert len(_entries()) >= len(jobs.KINDS) - 1


@pytest.mark.parametrize(("kind", "target"), _entries())
def test_entry_does_not_load_kaa(kind, target):
    r = subprocess.run(
        [sys.executable, "-c", PROBE, kind, target],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
        timeout=120,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    res = json.loads(r.stdout.strip().splitlines()[-1])
    if res["missing"]:
        assert res["missing"].split(".")[0] not in ("kaa", "kotonebot"), f"{target} 还要 KAA：{res['missing']}"
        pytest.skip(f"缺可选依赖 {res['missing']}（CI 只装 dev 组）")
    assert res["loaded"] == [], f"{target} 导入时加载了 {res['loaded']}"
