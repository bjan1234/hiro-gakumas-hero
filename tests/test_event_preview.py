"""11-27 实机（刷回忆第一局）：二选一事件只看得到选中那项的效果，另一项没读到 → 规则选不了、没开 LLM 就停。
现在像玩家一样逐个单击选项（只选中不确认），读它上方的说明框；说明框在选中按钮正上方约 100 px（不在授業三选一的 EFFECT_Y）。"""

from types import SimpleNamespace as NS

from hiro.produce import hif
from hiro.vision import event


def _box(t, cx, cy, w=200, h=24):
    return (t, 0.9, (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2))


OPTS = ["梦想的进展怎么样了?", "有个新的课程建议"]


def test_effect_above_reads_tooltip_not_buttons():
    boxes = [_box("特定のPドリンクを選択して獲得", 440, 701, 420), _box(OPTS[0], 220, 801), _box(OPTS[1], 220, 904)]
    assert event.effect_above(boxes, 801, OPTS) == "特定のPドリンクを選択して獲得"
    # 选第二项：说明框盖在第一项按钮上，露出来的第一项按钮字不算
    boxes = [
        _box("スキルカードを選択して獲得", 440, 801, 420),
        _box("梦想的进展", 120, 801, 100),
        _box(OPTS[1], 220, 904),
    ]
    assert event.effect_above(boxes, 904, OPTS) == "スキルカードを選択して獲得"
    assert event.effect_above([_box(OPTS[0], 220, 801)], 904, OPTS) == ""


def test_preview_taps_each_option_once_and_reads_effects(monkeypatch):
    taps = []
    shown = {801: "特定のPドリンクを選択して獲得", 904: "スキルカードを選択して獲得"}
    monkeypatch.setattr(hif, "device", NS(click=lambda x, y: taps.append(y), screenshot=lambda: taps[-1]))
    monkeypatch.setattr(hif, "sleep", lambda s: None)
    monkeypatch.setattr(
        hif.ops,
        "ocr_boxes",
        lambda y: [_box(shown[y], 440, y - 100, 420), _box(OPTS[0], 220, 801), _box(OPTS[1], 220, 904)],
    )
    import hiro.vision.classify as classify

    monkeypatch.setattr(classify, "option_regions", lambda img: [1, 2])
    choices = [
        {"index": 0, "text": OPTS[0], "center": [360, 801], "selected": False},
        {"index": 1, "text": OPTS[1], "center": [360, 904], "selected": False},
    ]
    notes = []
    fake = NS(s=NS(state=NS(page_fields={"choices": choices}), note=notes.append), PREVIEW_WAIT_S=0)
    sel = hif.HifCore._preview_event_effects(fake, choices)
    assert taps == [801, 904] and sel == 1  # 每项单击一次，不双击
    assert choices[0]["effect"] == shown[801] and choices[1]["effect"] == shown[904]
    from hiro.brain import event_choice as ev

    assert all(ok for _, ok in (ev.parse(c) for c in choices))  # 规则能解析：不用 LLM


def test_preview_puts_preselected_option_last(monkeypatch):
    taps = []
    monkeypatch.setattr(hif, "device", NS(click=lambda x, y: taps.append(y), screenshot=lambda: taps[-1]))
    monkeypatch.setattr(hif, "sleep", lambda s: None)
    monkeypatch.setattr(hif.ops, "ocr_boxes", lambda y: [_box(OPTS[0], 220, 801), _box(OPTS[1], 220, 904)])
    import hiro.vision.classify as classify

    monkeypatch.setattr(classify, "option_regions", lambda img: [1])
    choices = [
        {"index": 0, "text": OPTS[0], "center": [360, 801], "selected": True},  # 已选中：单击会确认，放最后点
        {"index": 1, "text": OPTS[1], "center": [360, 904], "selected": False},
    ]
    fake = NS(s=NS(state=NS(page_fields={"choices": choices}), note=lambda t: None), PREVIEW_WAIT_S=0)
    hif.HifCore._preview_event_effects(fake, choices)
    assert taps == [904, 801]


def test_preview_skips_dialogue_only():
    choices = [{"index": 0, "text": "a", "center": [1, 1]}, {"index": 1, "text": "b", "center": [1, 2]}]
    fake = NS(s=NS(state=NS(page_fields={"dialogue_only": True}), note=lambda t: None))
    assert hif.HifCore._preview_event_effects(fake, choices) is None


def test_tooltip_row_is_not_an_option():
    """11-27 实机第二次：第 1 项已选中，它的说明框落在第 0 行位置，被读成第 3 个选项；它的文字又把真正的说明当按钮字排除了。"""
    assert event._looks_like_effect("特定のPドリンクを選択して獲得")
    assert event._looks_like_effect("ボーカル+20")
    assert not event._looks_like_effect("梦想的进展怎么样了?")
    assert not event._looks_like_effect("夢の進捗はどう?")
    assert not event._looks_like_effect(None)
