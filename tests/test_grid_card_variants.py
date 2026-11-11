"""卡格认卡：角色专属卡图变体按 base 归并（实机帧在私有 fixtures）。
DMM 的游戏数据里有新角色（秦谷美鈴，后缀 -hmsz）的卡图变体，KAA 的 strip_character_suffix 不认这个后缀：
同一张卡票数被拆开、卡图相关第一第二是同一张卡（领先差 0），本战相談 2 格卡认不出、整个货架判不完整，决策直接离开。"""

from test_shop_exec import frame

from hiro.vision import shop
from hiro.vision.deck import base_asset


def test_base_asset_strips_any_character_suffix():
    assert base_asset("img_general_skillcard_men-3_041-hmsz") == "img_general_skillcard_men-3_041"
    assert base_asset("img_general_skillcard_act-2_047-jsna") == "img_general_skillcard_act-2_047"
    assert base_asset("img_general_skillcard_ido-100_047") == "img_general_skillcard_ido-100_047"


def test_main_consult_shelf_complete():
    r = shop.read_consult(frame("main_consult_hmsz"))
    assert r["complete"] is True
    assert [c.get("card_id") for c in r["shelf"][:4]] == ["p_card-00-men-2_012", "p_card-00-men-3_003", "p_card-02-men-3_041", "p_card-02-act-1_028"]
    assert [c["price"] for c in r["shelf"]] == [53, 70, 105, 70, 35, 100, 75, 100]
