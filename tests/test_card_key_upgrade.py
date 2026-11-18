"""考试引擎的卡定义缓存（gakumas_exam.battle._Library）：强化次数超过主数据最高等级、或生成定义失败时不留半截缓存。

dmmw1 本战（2026-11-11）：KeyError 'p_card-02-men-2_100@3' 在轮间估值和 R2 预演里出现 25 次。原因是 card_key 先登记键名再算定义，
算定义抛错后键名留在缓存里，之后同一张卡直接返回这个键，按它查定义表就 KeyError（同一进程里一直坏下去）。
"""

import pytest

pytestmark = pytest.mark.sim_master


@pytest.fixture()
def lib():
    from gakumas_exam.battle import _Library
    from gakumas_exam.catalog import Catalog
    from gakumas_exam.master import shared

    cat = Catalog()
    try:
        commit = cat.info["commit"]
    finally:
        cat.db.close()
    return _Library(shared(commit))  # 不用进程共享的那份，免得影响别的测试


def _ref(cid, upgrade):
    from gakumas_exam.native_battle import _CardRef

    return _CardRef("g-1", cid, upgrade, [])


def test_upgrade_above_max_uses_highest_variant(lib):
    # 気まぐれハート 主数据只有 0–3；考试中再强化一次到 4，游戏按最高等级算（同 ExamCard.base_row）
    key = lib.card_key(_ref("p_card-02-men-2_100", 4))
    assert lib.cards[key]["name"] == "気まぐれハート+++"


def test_failed_definition_leaves_no_half_cache(lib, monkeypatch):
    calls = []

    def boom(card):
        calls.append(card.upgrade)
        raise RuntimeError("定义生成失败")

    real = lib._card_def
    monkeypatch.setattr(lib, "_card_def", boom)
    with pytest.raises(RuntimeError):
        lib.card_key(_ref("p_card-02-men-2_100", 1))
    monkeypatch.setattr(lib, "_card_def", real)
    key = lib.card_key(_ref("p_card-02-men-2_100", 1))  # 第二次重新生成，不是拿到一个查不到定义的键
    assert lib.cards[key]["name"] == "気まぐれハート+"
