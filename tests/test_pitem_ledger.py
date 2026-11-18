"""P 道具记账（任务 ②：搜索起点要带这一局的 P 道具）：识别的 PITEM_ACQUIRE（参数 pitem_id）进 produce.items；
选定制 P 道具（背包 → 毛绒 → 装饰）后记 PITEM_CUSTOMIZE，按 master ID 替换上一段。"""

from hiro.brain import pitem
from hiro.loop.events import events_from_step
from hiro.state.events import predict


def _items(prod, ev):
    preds = predict({"produce": prod}, ev)
    return preds[0].fields["produce.items"].value if preds else None


def test_observed_acquire_uses_pitem_id():
    ev = {"seq": 3, "kind": "PITEM_ACQUIRE", "origin": "observed", "args": {"pitem_id": "pitem_02-3-062-0"}}
    assert _items({"items": []}, ev) == ["pitem_02-3-062-0"]
    ev = {"seq": 3, "kind": "PITEM_ACQUIRE", "origin": "observed", "args": {"pitem_id": None, "pitem_ids": ["pitem_00-2-004-0"]}}
    assert _items({"items": ["x"]}, ev) == ["pitem_00-2-004-0", "x"]


def test_custom_id_matches_master_format():
    assert pitem.custom_id(pitem.parse({"name": "ポーチ（黄）"})) == "customize_pitem-02-04-3-003"
    assert pitem.custom_id(pitem.parse({"name": "ロボ（黄）"})) == "customize_pitem-02-04-3-003_00-04-2-003_02-02-1-001"
    assert pitem.custom_id(pitem.parse({"name": "花ロボ（黄）"})) == "customize_pitem-02-04-3-003_00-04-2-003_02-02-1-001_00-04-4-001"
    assert pitem.parse({"item_id": "customize_pitem-02-04-3-003_00-04-2-003_02-02-1-001_00-04-4-002"})["deco"] == "リボン"


def test_select_pitem_emits_customize_replacing_previous_stage():
    fields = {"pitems": [{"slot": 0, "name": "羽ロボ（黄）"}, {"slot": 1, "name": "花ロボ（黄）"}, {"slot": 2, "name": "リボンロボ（黄）"}]}
    prod = {"items": ["pitem_02-3-062-0", "customize_pitem-02-04-3-003_00-04-2-003_02-02-1-001"]}
    ev = events_from_step("SELECT_PITEM", {"kind": "ActivateEffect", "args": {"pick_indexes": [1]}}, True, fields, prod, seq=9)
    assert [e.kind for e in ev] == ["PITEM_CUSTOMIZE"]
    assert ev[0].args == {"item_id": "customize_pitem-02-04-3-003_00-04-2-003_02-02-1-001_00-04-4-001",
                          "replaces": "customize_pitem-02-04-3-003_00-04-2-003_02-02-1-001"}
    assert _items(prod, ev[0].to_dict()) == sorted(["pitem_02-3-062-0", ev[0].args["item_id"]])
