"""开局前检查（hiro run start 的 precheck / 确认摘要）：问题在待确认之前就说清楚，不开一个注定失败的任务。

Mac 11-24：H.I.F（01:31）和「初」藤田ことね（16:08）的编成方案是给月村手毬的，任务进了游戏流程才报
「开局要编成号」退出；18:27 那局考试出牌算法没加载上，整局退回规则打，只有日志里一行 WARNING。"""

import json

import pytest

KOTONE = "i_card-skin-fktn-3-000"


def _plan(home, idol="i_card-ttmr-3-000", name="Luna say maybe"):
    home.mkdir(parents=True, exist_ok=True)
    plan = {"idol": {"idol_card_id": idol, "name": name}, "support": {"set": 16}, "memory": {"set": 9}}
    (home / "formation-plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def _algo_ok(monkeypatch):
    from hiro.cli import cmd_run

    monkeypatch.setattr(cmd_run, "exam_algo_problem", lambda: None)


@pytest.mark.parametrize("kind", ["hajime", "nia"])
def test_plan_for_another_idol_is_refused_before_confirm(run_cli, hiro_home, kind):
    _plan(hiro_home)
    _code, env = run_cli("run", "start", kind, "--idol", KOTONE, "--difficulty", "master")
    assert env["ok"] is False and env["error"]["code"] == "plan_other_idol"
    assert "Luna say maybe" in env["error"]["message"]
    assert "plan formation --idol i_card-fktn-3-000" in env["error"]["hint"]
    assert f"write-formation --scenario {kind}" in env["error"]["hint"]


def test_no_plan_is_refused_before_confirm(run_cli, hiro_home):
    _code, env = run_cli("run", "start", "hajime", "--idol", KOTONE)
    assert env["ok"] is False and env["error"]["code"] == "no_plan"
    assert "plan formation --idol i_card-fktn-3-000" in env["error"]["hint"]


def test_hif_qualify_checks_plan_but_main_and_resume_do_not(run_cli, hiro_home):
    _plan(hiro_home)
    _code, env = run_cli("run", "start", "hif", "--idol", KOTONE, "--mode", "qualify")
    assert env["error"]["code"] == "plan_other_idol"
    for extra in (("--mode", "main"), ("--command", "resume")):
        code, env = run_cli("run", "start", "hif", "--idol", KOTONE, *extra)
        assert code == 3 and env["data"]["pending"], extra  # 本战不走编成步骤、续跑不重新编成


def test_matching_plan_or_explicit_sets_pass(run_cli, hiro_home):
    _plan(hiro_home, idol="i_card-fktn-3-000", name="世界一可愛い私")
    code, env = run_cli("run", "start", "hajime", "--idol", KOTONE)
    assert code == 3 and env["data"]["pending"]
    (hiro_home / "formation-plan.json").unlink()
    code, env = run_cli("run", "start", "hajime", "--idol", KOTONE, "--support-set", "3", "--memory-set", "7")
    assert code == 3 and env["data"]["pending"]


def test_confirm_summary_warns_when_exam_algo_is_missing(run_cli, hiro_home, monkeypatch):
    from hiro.cli import cmd_run

    _plan(hiro_home, idol="i_card-fktn-3-000")
    monkeypatch.setattr(cmd_run, "exam_algo_problem", lambda: "缺 Python 模块 gkbench")
    code, env = run_cli("run", "start", "hajime", "--idol", KOTONE)
    summary = env["data"]["pending"]["summary"]
    assert code == 3 and "考试出牌只能用规则" in summary and "gkbench" in summary
