"""HifCore 的考试出招插件：缺省是 SearchAdvisor（带 profile / llm），环境变量指定 BenchAdvisor 一系也带上；别的实现交给插件。"""

from types import SimpleNamespace

from hiro import plugins
from hiro.brain.state import CAMPUS_HIRO
from hiro.produce.hif import HifCore


def _adv(monkeypatch, env=None):
    monkeypatch.setenv("HIRO_BENCH_ADVISOR", "0")  # 不加载 UINet
    if env is None:
        monkeypatch.delenv("HIRO_EXAM_ADVISOR", raising=False)
    else:
        monkeypatch.setenv("HIRO_EXAM_ADVISOR", env)
    plugins.reset()
    return HifCore._exam_advisor(SimpleNamespace(profile=CAMPUS_HIRO), None)


def test_default_is_search_advisor(monkeypatch):
    from hiro.search.advisor import SearchAdvisor

    adv = _adv(monkeypatch)
    assert type(adv) is SearchAdvisor and adv.profile is CAMPUS_HIRO


def test_env_bench_advisor_gets_profile(monkeypatch):
    from hiro.bench_bridge.advisor import BenchAdvisor

    adv = _adv(monkeypatch, "hiro.bench_bridge.advisor:BenchAdvisor")
    assert type(adv) is BenchAdvisor and adv.profile is CAMPUS_HIRO


def test_other_plugin_left_to_run_exam(monkeypatch):
    assert _adv(monkeypatch, "hiro.defaults.exam_state:ScreenExamStateSource") is None
