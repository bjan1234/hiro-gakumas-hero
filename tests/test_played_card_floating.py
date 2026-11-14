"""刚打出的牌还停在画面中间时不决策（偶像之路 Mac 15 层 11-14，8a3a1e7：回合正在结束时又决策了一次）。
选中待确认的卡也抬在手牌上方，但卡面上方有粉色得分预览；刚打出的没有。"""

from pathlib import Path
from types import SimpleNamespace as NS

import pytest

FIX = Path(__file__).parent / "fixtures" / "tower"


def _img(name):
    import cv2

    path = FIX / name
    if not path.exists():
        pytest.skip(f"需要实机截图 tests/fixtures/tower/{name}")
    return cv2.imread(str(path))


@pytest.mark.parametrize(("name", "raised", "floating"), [
    ("exam-played-floating-mac15.jpg", True, True),    # 深呼吸+ 刚打出，停在中间
    ("exam-selected-preview-mac15.jpg", True, False),  # スタンドプレー+ 选中待确认，上方有「9260」预览
    ("exam-normal-mac15.jpg", False, False),
])  # fmt: skip
def test_played_card_floating(name, raised, floating):
    from hiro.vision.hand_slots import played_card_floating, raised_card

    img = _img(name)
    assert (raised_card(img) is not None) is raised and played_card_floating(img) is floating


def test_stale_before_tap_rejects_floating_frames(monkeypatch):
    import hiro.exec.exam as ex
    import hiro.vision.hand_slots as hs

    sig = ((5, 20, 10), ((1, 2), (3, 4)))
    monkeypatch.setattr(ex, "_lite_sig", lambda img: sig)
    monkeypatch.setattr(ex, "device", NS(screenshot=lambda: "fresh"))
    monkeypatch.setattr(hs, "played_card_floating", lambda img: img == "decision")
    assert "过渡帧" in ex._stale_before_tap(NS(img="decision"))  # 决策帧就是过渡帧
    monkeypatch.setattr(hs, "played_card_floating", lambda img: img == "fresh")
    assert "点击前" in ex._stale_before_tap(NS(img="decision"))  # 点击前那一帧是过渡帧
    monkeypatch.setattr(hs, "played_card_floating", lambda img: False)
    assert ex._stale_before_tap(NS(img="decision")) is None
