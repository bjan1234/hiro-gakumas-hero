"""相談货架价格按已知价格核对（实机帧在私有 fixtures）：DMM 实机 パワフル漢方ドリンク（R2 饮料，非 SALE）画面上是 75，
RapidOCR 四种读法 2:2 平票（[15] / 15 / 75 / ddddocr 75），以前取了 15、预算按 15 算，买下实扣 75。
同一帧第 0 格是 SALE 卡 24P（原价 35），卡价不规整，只设下限、不给预期价。"""

from test_shop_exec import frame

from hiro.vision import shop


def test_known_price_helpers():
    assert shop.expected_price({"kind": "drink", "drink_id": "pdrink_00-2-009"}, False) == 75
    assert shop.expected_price({"kind": "drink", "drink_id": "pdrink_02-3-007"}, True) == 70
    assert shop.expected_price({"kind": "drink", "drink_id": "pdrink_02-1-006"}, True) == 35
    assert shop.expected_price({"kind": "card", "card_id": "p_card-02-men-2_056", "upgrade": 1}, False) is None
    assert shop.price_floor("drink", False) == 50 and shop.price_floor("card", False) == 70 and shop.price_floor("card", True) == 20


def test_shelf_prices():
    shelf = shop.read_consult(frame("price75_read15"))["shelf"]
    got = {c["index"]: (c.get("card_id") or c.get("drink_id"), c["price"], c["sale"]) for c in shelf}
    assert got[7] == ("pdrink_00-2-009", 75, False)
    assert got[0][1:] == (24, True)
    assert [got[i][1] for i in range(1, 7)] == [70, 70, 77, 52, 50, 100]
