"""KAA 出手次数（去 KAA 第 0 步：只记不改行为）。

数三类：
- KAA 页面上下文（kaa.tasks.produce.new.page 的 Context 子类）上被我们调用的方法，例如 ActionSelectContext.fetch_available_actions、
  StudyContext.commit；kaa_patches 已经换成我们自己函数的（action_commit、pitem_commit、换卡两阶段）不算；
- KAA 策略基类的钩子（HifGrindStrategy 及其父类的 on_* / try_handle_commu），也就是我们 super() 交回 KAA 或没覆盖的页面；
- ProducePage.check_scene 和 _dispatch 在 UNKNOWN / IDLE 上的 (12,12) 盲点（主循环里记）。

只数最外层：KAA 方法内部再调别的 KAA 方法不重复算。结果在 run_hif 结束时写进 reports/runs/<名>.json 的 kaa_usage。
"""

from __future__ import annotations

import functools
import threading
from collections import Counter

USAGE: Counter = Counter()
_depth = threading.local()
_INSTALLED = "_hiro_kaa_usage"


def count(key: str, n: int = 1) -> None:
    USAGE[key] += n


def reset() -> None:
    USAGE.clear()


def snapshot() -> dict[str, int]:
    return dict(sorted(USAGE.items(), key=lambda kv: (-kv[1], kv[0])))


def _counted(key: str, fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        depth = getattr(_depth, "n", 0)
        if depth == 0:
            USAGE[key] += 1
        _depth.n = depth + 1
        try:
            return fn(*args, **kwargs)
        finally:
            _depth.n = depth

    setattr(wrapper, _INSTALLED, True)
    return wrapper


def _ours(fn) -> bool:
    return (getattr(fn, "__module__", "") or "").startswith("hiro.")


def _wrap_class(cls, want) -> int:
    n = 0
    for name, attr in list(vars(cls).items()):
        if not want(name) or not callable(attr) or isinstance(attr, (staticmethod, classmethod, type)):
            continue
        if getattr(attr, _INSTALLED, False) or _ours(attr):
            continue
        setattr(cls, name, _counted(f"{cls.__name__}.{name}", attr))
        n += 1
    return n


def _subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def install() -> int:
    """给 KAA 的页面上下文和策略基类挂计数（kaa_patches.apply 之后调；重复调用不会重复包）。返回新包的方法数。"""
    from kaa.tasks.produce.new.page import Context, ProducePage
    from kaa.tasks.produce.new.strategies.hif_grind import HifGrindStrategy

    public = lambda name: not name.startswith("_")  # noqa: E731
    n = 0
    for cls in (Context, *_subclasses(Context)):
        if cls.__module__.startswith("kaa."):
            n += _wrap_class(cls, public)
    if not getattr(ProducePage.check_scene, _INSTALLED, False):  # 定义在 _SceneCheckMixin 上，包到 ProducePage 自己身上
        ProducePage.check_scene = _counted("ProducePage.check_scene", ProducePage.check_scene)
        n += 1
    for cls in HifGrindStrategy.__mro__:
        if cls.__module__.startswith("kaa."):
            n += _wrap_class(cls, lambda name: name.startswith("on_") or name == "try_handle_commu")
    return n
