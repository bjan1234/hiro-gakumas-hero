"""第 3 步四格回忆图标（hiro.vision.memory_icons.read_step3_icons）：空格、プラン不一致（卡图压暗）。账号 2 11-16 实机帧。"""

import os
from pathlib import Path

import cv2
import pytest

FIX = Path(os.environ.get("HIRO_FIXTURES", Path(__file__).parent / "fixtures")) / "pages"


def _img(name):
    p = FIX / name
    if not p.exists():
        pytest.skip(f"需要实机截图 pages/{name}")
    return cv2.resize(cv2.imread(str(p)), (720, 1280))


def test_plan_mismatch_slot_is_read_after_brightening():
    from hiro.vision.memory_icons import read_step3_icons

    r = read_step3_icons(_img("step3-plan-mismatch-acct2.png"))
    assert [x["card"] for x in r] == ["men-2_004", "act-1_037", "act-3_039", "men-3_036"] and all(x["known"] for x in r)
    assert r[3].get("plan_mismatch") and not any(x.get("plan_mismatch") for x in r[:3])


def test_empty_slots_are_marked_empty():
    from hiro.vision.memory_icons import read_step3_icons

    r = read_step3_icons(_img("step3-empty-slots-acct2.png"))
    assert r[0]["card"] == "men-3_036" and r[0]["known"] and r[0].get("plan_mismatch")
    assert [x.get("empty") for x in r[1:]] == [True, True, True] and all(x["card"] is None for x in r[1:])
