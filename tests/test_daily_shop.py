"""日常 11-26：竞赛停止条件 / 挑对手、商店（デイリー交換所）、硬币扭蛋的读数（按 11-25 DMM 实机截图的 OCR 文字和位置造的帧）。"""

from hiro.daily import coin_gacha, contest, shop
from hiro.runtime.frame import Frame
from hiro.vision.ocr import Box, Text

import numpy as np


def frame(*texts):
    f = Frame(np.zeros((1280, 720, 3), np.uint8), 0.0)
    f.__dict__["texts"] = [Text(t, Box(x - 40, y - 12, x + 40, y + 12)) for t, x, y in texts]
    return f


def test_contest_used_up_by_text_or_counter(monkeypatch):
    monkeypatch.setattr(contest.nav, "find", lambda f, name, **kw: None)  # 模板没认出（DMM 实测 0.79 < 0.8）
    assert contest.used_up(frame(("本日の挑戦権を消費しました", 360, 885)))
    assert contest.used_up(frame(("0/5", 600, 40)))
    assert contest.remaining(frame(("3/5", 600, 40))) == 3
    assert not contest.used_up(frame(("3/5", 600, 40), ("ランキング", 100, 390)))


def test_contest_pick_choice(monkeypatch):
    monkeypatch.delenv("HIRO_CONTEST_PICK", raising=False)
    assert contest.pick_choice() == "lowest"
    monkeypatch.setenv("HIRO_CONTEST_PICK", "3")
    assert contest.pick_choice() == "3" and contest.PICKS["3"] == 2
    monkeypatch.setenv("HIRO_CONTEST_PICK", "hard")
    assert contest.pick_choice() == "lowest"


def test_shop_tiles_read_price_left_and_recommended():
    f = frame(("おすすめ", 61, 319), ("3,000", 120, 480), ("あと1回", 104, 509),
              ("6,000", 290, 480), ("あと2回", 274, 509), ("あと0回", 444, 509), ("マニー", 190, 1083))  # fmt: skip
    t = shop.tiles(f)
    assert [(d["x"], d["left"], d["price"], d["recommended"]) for d in t] == [
        (104, 1, 3000, True), (274, 2, 6000, False), (444, 0, None, False)
    ]  # fmt: skip
    assert t[0]["y"] == 509 - 110


def test_shop_dialog_name_and_currency():
    f = frame(("交換確認", 100, 425), ("マニーを使用して、以下のアイテムと交換しますか?", 300, 512),
              ("[Wonder Scale]倉本千奈のピース", 380, 584), ("キャンセル", 168, 1143), ("決定", 490, 1140))  # fmt: skip
    d = shop.read_dialog(f)
    assert d == {"name": "[Wonder Scale]倉本千奈のピース", "money": True, "ap": False, "jewel": False}
    assert shop.read_dialog(frame(("デイリー交換所", 100, 40))) is None
    j = shop.read_dialog(frame(("交換確認", 100, 425), ("ジュエルを使用して", 300, 512), ("何か", 300, 584)))
    assert j["money"] is False and j["jewel"] is True


def test_shop_name_matching_tolerates_ocr():
    assert shop.name_wanted("IWonderScalel倉本千奈のピ一ス", ["倉本千奈のピース"])
    assert shop.name_wanted("再挑戦チケット", ["ロジックノート", "再挑戦"])
    assert not shop.name_wanted("ロジックノート(ボーカル", ["再挑戦"])


def test_coin_gacha_count_and_plan(monkeypatch):
    assert coin_gacha.count(frame(("ガシャ回数:4回", 300, 816))) == 4
    assert coin_gacha.count(frame(("ガシャ回数:", 300, 816))) == 0  # SIMD 把「0回」漏读
    assert coin_gacha.count(frame(("フレンドガシャ", 300, 545))) is None
    monkeypatch.delenv("HIRO_COIN_GACHA", raising=False)
    assert coin_gacha.plan() == []  # 缺省不抽（花币的事默认关，开局页的日常选项会显式传）
    monkeypatch.setenv("HIRO_COIN_GACHA", "auto")
    assert coin_gacha.plan() == "auto"
    monkeypatch.setenv("HIRO_COIN_GACHA", "friend:2,sense,bogus:3,logic:0")
    assert coin_gacha.plan() == [("friend", 2), ("sense", 1)]
    monkeypatch.setenv("HIRO_COIN_GACHA", "off")
    assert coin_gacha.plan() == []
    t = coin_gacha._gacha_title(frame(("センスガシヤ(毎月1日5時00分更新)", 200, 987)), "sense")
    assert t is not None and t.rect.center.y == 987


def test_shop_ap_dialog_and_options(monkeypatch):
    """体力商店（11-26）：确认框「APを使用して」；HIRO_SHOP_AP 选哪几样；名字翻中文。"""
    from hiro.daily.names import item_name

    d = shop.read_dialog(frame(("交換確認", 100, 425), ("APを使用して、以下のアイテムと交換しますか?", 300, 512),
                               ("再挑戦チケット", 300, 584)))  # fmt: skip
    assert d["ap"] and not d["money"] and not d["jewel"] and d["name"] == "再挑戦チケット"
    monkeypatch.setenv("HIRO_SHOP_AP", "retry, regen,bogus")
    assert shop.ap_wanted() == ["retry", "regen"]
    assert shop.AP_ITEMS["regen"] in "メモリー再生成チケット" and shop.AP_ITEMS["pt"] in "入手サポート強化Ptアップ"
    assert item_name("メモリー再生成チケット", "zh") == "回忆再生成券"
    assert item_name("入手ノート数アップ", "zh") == "笔记获取数提升"
    assert item_name("入手ノート数アップ", "ja") == "入手ノート数アップ"


def test_shop_default_off_and_cost(monkeypatch):
    monkeypatch.delenv("HIRO_SHOP", raising=False)
    assert shop.mode() == "off"  # 缺省不进商店（review：领日常奖励不该默认花マニー）
    f = frame(("交換確認", 100, 425), ("2,017,701", 193, 992), ("→", 387, 997), ("2,014,701", 450, 992))
    assert shop.cost(f) == 3000
    assert shop.cost(frame(("2,017,701", 193, 992))) is None
