"""python -m hiro.bench_bridge setup | check

setup：准备考试出牌算法要的东西（下载并校验 UINet 模型、onnxruntime 旧时转换、导出主数据），失败时退出码 1。
check：只检查（不下载），打印现在能不能用、缺什么。
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "check"
    from hiro.bench_bridge import advisor as A

    if not A.enabled():
        print("HIRO_BENCH_ADVISOR=0：考试出牌用社区规则 + LLM")
    try:
        algo = A.load_algo(download=(cmd == "setup"))
    except Exception as e:  # noqa: BLE001
        print(f"考试出牌算法 {A.algo_spec()} 不能用：{type(e).__name__}: {e}")
        print("考试出牌会退回社区规则（不调 LLM）")
        return 1
    print(f"考试出牌算法 {A.algo_spec()} 可用：{algo.describe()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
