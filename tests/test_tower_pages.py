"""偶像之路页面（hiro.vision.tower + pages / classify 接入）：Mac 实机采样 12 张（11-14，协调）。"""

from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "tower" / "pages"


def _hit(name):
    import cv2

    from hiro.vision.classify import classify

    path = FIX / name
    if not path.exists():
        pytest.skip(f"需要实机截图 tests/fixtures/tower/pages/{name}")
    h = classify(cv2.imread(str(path)))
    return h.name, {k: v for k, v in (h.fields or {}).items() if k != "_quick"}


def test_list_layers_info():
    name, f = _hit("03_list.png")
    assert name == "TOWER_LIST" and [(i["stage"], i["name"], i["progress"]) for i in f["idols"][:3]] == [
        (22, "花海咲季", "62/81"), (14, "月村手毬", "37/81"), (25, "藤田ことね", "75/81")]  # fmt: skip
    name, f = _hit("04_idol_layers.png")
    assert name == "TOWER_LAYERS" and f["idol"] == "月村手毬" and f["stage"] == 15 and f["challenge"] and not f["locked"]
    # 层号取居中放大那层的大数字（左栏「STAGE 15 報酬」滑动后不变）；星数是那层的三颗星；最前沿锁着时挑戦する是灰的
    for frame, stage, stars, locked in (("21_layers_after_clear.png", 15, 1, False), ("22_layers_scroll_down1.png", 13, 2, False),
                                        ("23_layers_scroll_down2.png", 10, 3, False), ("26_layers_frontier.png", 16, 0, True)):  # fmt: skip
        name, f = _hit(frame)
        assert (name, f["stage"], f["stars"], f["locked"]) == ("TOWER_LAYERS", stage, stars, locked), frame
    name, f = _hit("05_layer_info.png")
    assert name == "TOWER_LAYER_INFO" and [(c["star"], c["text"]) for c in f["conditions"]] == [
        (3, "1位でクリア"), (2, "2位以上でクリア"), (1, "3位以上でクリア")]  # fmt: skip


def test_formation_reads_loadout_fields():
    """编成页给 HIRO_TOWER_LOADOUT：回合数、三属性倍率千分比、体力上限（8a3a1e7 的 tower_context 读这个格式）。"""
    name, f = _hit("06_challenge.png")
    assert name == "TOWER_FORMATION"
    assert (f["layer"], f["turns"], f["score_bonus_permils"], f["max_stamina"]) == (15, 15, [23090, 11980, 2600], 46)
    assert f["challenge"] and f["omakase"]  # おまかせ 只记位置，处理器绝不点


def test_memory_select_result_retry_exam():
    assert _hit("07_memory_select.png")[0] == "TOWER_MEMORY_SELECT"
    name, f = _hit("09_result.png")
    assert name == "TOWER_RESULT" and (f["cleared"], f["layer"], f["stars"]) == (True, 15, 1) and f["back"] and f["retry"]
    name, f = _hit("10_retry_confirm.png")
    assert name == "TOWER_RETRY_CONFIRM" and f["cost"] is None and f["same"] and f["ok"]  # 没有消耗字样
    assert _hit("11_retry_started.png")[0] == "TOWER_EXAM"  # 先于 KAA 的 EXAM 模板
