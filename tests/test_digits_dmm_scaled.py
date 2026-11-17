"""缩放过的画面（DMM 1080 宽窗口缩到 720）上的游戏字体读数（hiro.vision.digits）：描边被混浅，原来字形全被当背景丢掉、
read_text 返回空（9580c0c 11-17）。现在第一遍切不出字时按浅描边再切一遍：读得出就要读对，读不出就是空（交 ddddocr 退路），不许读错。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

DMM = Path(__file__).with_name("fixtures") / "genki_dmm"  # 截图样例不进仓库，没有时跳过


def _cases():
    for p in sorted(DMM.glob("*.png")):
        stem, x, y = p.stem.rsplit("_", 2)
        yield p, int(x), int(y), stem.rsplit("-", 1)[1]


def _canvas(p, x, y):
    img = np.zeros((1280, 720, 3), np.uint8)
    crop = cv2.imread(str(p))
    img[y : y + crop.shape[0], x : x + crop.shape[1]] = crop
    return img


def test_dmm_genki_font_read_right_or_empty():
    from hiro.vision import assets
    from hiro.vision.digits import read_text
    from hiro.vision.hif import BOX_GENKI

    cases = list(_cases())
    if not cases:
        pytest.skip("没有 DMM 元気样例 tests/fixtures/genki_dmm/")
    if assets.font_path() is None:
        pytest.skip("没有游戏数字字体（素材包 font/）")
    got = [(want, read_text(_canvas(p, x, y), BOX_GENKI, align=True)) for p, x, y, want in cases]
    wrong = [(w, t) for w, (t, _) in got if t and t != w]
    assert wrong == []  # 读出来的都对
    assert sum(1 for w, (t, _) in got if t == w) >= 7  # 11-17：9 张读对 7 张（一张 0、1252 那张背景是浅色，读空）
