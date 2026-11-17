"""DMM qualifyz1（11-17 17:35）：Da SP 课结束，3 条支援能力横幅 + P 道具浮条盖着「ホットコーヒー」获得演出，名称栏这一行右端露出
后面横幅的「H.I.F」logo 一角，OCR 读成「ıF」（x≈659）。read_acquire_popup 见到偏离中心的文字就不算 → 整页 unknown、没处理器，
180 秒停机。名称栏里很短、不含假名 / 汉字的碎片不算文字（选饮料页、Pドリンク詳細 旁边的字都是日文，照旧排除）。"""

from pathlib import Path

import pytest

from hiro.vision import deck

FIX = Path(__file__).with_name("fixtures") / "acquire_dmm"


def _fake_boxes(monkeypatch, boxes):
    import hiro.vision.ocr as ocr

    x1 = deck.ACQUIRE_BAR[0]
    monkeypatch.setattr(ocr, "ocr_boxes", lambda img, **k: [(t, 0.9, (cx - x1 - 20, 5, cx - x1 + 20, 30)) for t, cx in boxes])


@pytest.mark.master
def test_stray_latin_fragment_does_not_hide_acquire(monkeypatch):
    import numpy as np

    _fake_boxes(monkeypatch, [("ホットコーヒー", 379), ("ıF", 659)])
    item = deck.read_acquire_popup(np.zeros((1280, 720, 3), np.uint8), art=False)
    assert item is not None and item["kind"] == "drink" and item["drink_id"] == "pdrink_02-1-008"


@pytest.mark.master
def test_offcenter_japanese_still_rejected(monkeypatch):
    """Pドリンク詳細：名字偏左、右边「捨てる」——照旧不算获得页。"""
    import numpy as np

    _fake_boxes(monkeypatch, [("ホットコーヒー", 321), ("捨てる", 600)])
    assert deck.read_acquire_popup(np.zeros((1280, 720, 3), np.uint8), art=False) is None


@pytest.mark.master
def test_dmm_frame_classified_acquire():
    import cv2

    p = FIX / "qualifyz1-hotcoffee-banners.png"
    if not p.exists():
        pytest.skip("没有 DMM 获得页样例（截图不进仓库）")
    from hiro.vision.classify import classify

    assert classify(cv2.imread(str(p))).name == "ACQUIRE"
