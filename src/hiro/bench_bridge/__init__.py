"""bench 中转层：hiro 的考试局面 ↔ gakumas-bench 的算法接口（UIObs v1 公开观测）。

- uiobs：局面 → UIObs v1（格式照 GKMSUINet 公开的 uiobs.v1.schema.json）
- advisor：ExamAdvisor 实现，按名字加载 bench 算法（HIRO_BENCH_ALGO，缺省 uinet）出牌，出错时退回规则
"""
