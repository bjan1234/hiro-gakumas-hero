"""三选一选卡：从跳转表外的页面（N.I.A 営業话题）进来，页面要防抖几帧；决策前要等候选真的进了 state（11-17 N.I.A：读空停了）。"""

from pathlib import Path
from types import SimpleNamespace as NS

import cv2
import pytest

from hiro.contracts import Action, ActionKind, Decision

FIX = Path(__file__).with_name("fixtures") / "pages" / "nia-sales-reward-select-card.png"


def test_select_card_waits_for_debounce(tmp_path, monkeypatch):
    if not FIX.exists():
        pytest.skip("需要实机截图 pages/nia-sales-reward-select-card.png")
    import hiro.produce.hif as hif
    from hiro.contracts import TraceWriter
    from hiro.loop.session import Session

    img = cv2.imread(str(FIX))
    monkeypatch.setattr(hif, "device", NS(screenshot=lambda: img, click=lambda *a: None))
    monkeypatch.setattr(hif, "sleep", lambda s: None)
    session = Session(TraceWriter(name="sel", root=tmp_path), shoot=lambda: img)
    for _ in range(3):  # 前一页：N.I.A 営業话题（稳定）
        session.observe(scene="NIA_SALES_EVENT", img=img, fields={"choices": []}, ready=True)
    seen = []

    class Stop(Exception):
        pass

    def decide(page, state, **kw):
        seen.append([c["card_id"] for c in state.page_fields.get("candidates") or []])
        raise Stop

    core = hif.HifCore.__new__(hif.HifCore)
    core.s, core.deciders, core.rec = session, NS(decide=decide), NS(log=lambda *a, **k: None)
    with pytest.raises(Stop):
        core.on_select_card()
    assert seen and len(seen[-1]) == 3  # 决策时 state 里已经有三张候选
