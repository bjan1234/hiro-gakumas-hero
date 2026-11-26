import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location("check_settings_tool", REPO / "tools" / "check_settings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_settings_json_output(tmp_path, monkeypatch):
    mod = _tool()
    found = dict.fromkeys(mod.WANT, "ON")
    found["支援事件剧情跳过"] = "OFF"
    monkeypatch.setattr(mod, "check", lambda save_dir=None: found)
    out = tmp_path / "out.json"
    code = mod.main(["--json", str(out)])
    d = json.loads(out.read_text(encoding="utf-8"))
    assert code == 1 and d["ok"] is False and d["items"]["支援事件剧情跳过"] == "OFF" and "OFF" in d["verdict"]


def test_ingest_and_info_and_doctor(run_cli, tmp_path):
    inv = {
        "items": {
            "未読早送り": "ON",
            "支援事件剧情跳过": "OFF",
            "开始说明剧情跳过": "ON",
            "定期公演剧情跳过": "ON",
            "親愛度映像跳过": "ON",
        },
        "verdict": "设置被重置：1 项 OFF",
        "ok": False,
    }
    p = tmp_path / "s.json"
    p.write_text(json.dumps(inv, ensure_ascii=False), encoding="utf-8")
    _, env = run_cli("doctor")
    gs = {i["id"]: i for i in env["data"]["items"]}["game_settings"]
    assert gs["ok"] is None and "检查" in gs["next"]
    run_cli("info", "import", "--kind", "game_settings", str(p))
    _, env = run_cli("info", "game-settings")
    assert env["data"]["verdict"] == "设置被重置：1 项 OFF"
    assert {"item": "支援事件剧情跳过", "state": "OFF", "want": "ON"} in env["data"]["items"]
    _, env = run_cli("doctor")
    gs = {i["id"]: i for i in env["data"]["items"]}["game_settings"]
    assert gs["ok"] is False and "支援事件剧情跳过" in gs["detail"]


def test_doctor_follows_goal_and_suggests_fix(run_cli, tmp_path):
    """D3：要的状态是 OFF 的（HIRO_UNREAD_STORY=stop 时的未読早送り）读到 OFF 不算错；不对的提示一键改好。"""
    items = dict.fromkeys(
        ("未読早送り", "支援事件剧情跳过", "开始说明剧情跳过", "定期公演剧情跳过", "親愛度映像跳过"), "ON"
    )
    goal = dict(items)
    items["未読早送り"], goal["未読早送り"] = "OFF", "OFF"
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"items": items, "goal": goal, "verdict": "ok", "ok": True}, ensure_ascii=False), "utf-8")
    run_cli("info", "import", "--kind", "game_settings", str(p))
    _, env = run_cli("doctor")
    assert {i["id"]: i for i in env["data"]["items"]}["game_settings"]["ok"] is True
    items["親愛度映像跳过"] = "OFF"
    p.write_text(json.dumps({"items": items, "goal": goal, "verdict": "x", "ok": False}, ensure_ascii=False), "utf-8")
    run_cli("info", "import", "--kind", "game_settings", str(p))
    _, env = run_cli("doctor")
    gs = {i["id"]: i for i in env["data"]["items"]}["game_settings"]
    assert gs["ok"] is False and gs["detail"].startswith("这几项不对：親愛度映像跳过") and "--fix" in gs["next"]


def test_info_formations_lists_empty_sets(run_cli, tmp_path):
    # 11-25：助手里的模型从 40 行里自己数空位，把回忆空位说成 7–14；空位直接算好给出来
    sets = [{"kind": "memory", "set": n, "filled": 0 if 7 <= n <= 18 else 4, "cards": []} for n in range(1, 21)]
    sets += [{"kind": "support", "set": n, "filled": 0 if n in (3, 11, 12) else 5, "cards": []} for n in range(1, 21)]
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"mode": "hif", "complete": True, "sets": sets}), encoding="utf-8")
    run_cli("info", "import", "--kind", "formations", str(p))
    _, env = run_cli("info", "formations")
    e = env["data"]["empty"]
    assert e["memory"]["sets"] == list(range(7, 19)) and e["memory"]["text"] == "7–18"
    assert e["support"]["text"] == "3、11–12"
