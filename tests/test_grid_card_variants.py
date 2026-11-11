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


def test_kaa_patch_resolves_unknown_character_suffix(monkeypatch):
    """KAA 考试手牌识别自己遍历 CharacterId 去后缀：-hmsz 变体以前查不到卡（DMM 一局 68 次「no database match」）。"""
    import kaa.game_ui.skill_card_select as scs
    from kaa.db.skill_card import SkillCard

    from hiro.loop.kaa_patches import patch_character_suffix

    monkeypatch.setattr(SkillCard, "from_asset_id", SkillCard.__dict__["from_asset_id"])  # 测完还原（classmethod 本身）
    monkeypatch.setattr(scs, "strip_character_suffix", scs.strip_character_suffix)
    assert SkillCard.from_asset_id("img_general_skillcard_men-2_008-hmsz") is None
    patch_character_suffix()
    patch_character_suffix()  # 重复调用不叠加
    assert SkillCard.from_asset_id("img_general_skillcard_men-2_008-hmsz")._id == "p_card-02-men-2_008"
    assert SkillCard.from_asset_id("img_general_skillcard_men-2_008")._id == "p_card-02-men-2_008"
    assert scs.strip_character_suffix("img_general_skillcard_men-3_041-hmsz") == "img_general_skillcard_men-3_041"
