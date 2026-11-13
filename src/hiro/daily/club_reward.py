"""社团（サークル），移植 KAA tasks/daily/club_reward：≡ 菜单进社团页 → 没有进行中的笔记请求就发起一轮 → 给成员送礼（至多 5 位）。

笔记选 KAA 配置的缺省（selected_note = AnomalyNoteVisual，アノマリーノート（ビジュアル））；run_daily 一直用缺省，没改过。
「リクエスト受け取り」这种只有閉じる 的说明框由日常中断 Popup 关；确认框里有ジュエル时 Popup 只点キャンセル，
点击本身也过危险点击拦截（点在ジュエル 等字上直接拦下）。
"""

from __future__ import annotations

import logging

from hiro.daily import common
from hiro.runtime import nav

logger = logging.getLogger(__name__)

TITLE = "Daily.Club.TitleIcon"
CLOSE = "Common.ButtonClose"
MENU = "Common.ButtonToolbarMenu"
MENU_CLUB = "Daily.IconMenuClub"
REQUEST = "Daily.Club.ButtonRequest"
REQUEST_ONGOING = "Daily.Club.ButtonRequestOngoing"
CONFIRM = "Common.ButtonConfirm"
NOTE = "Shop.ItemAnomalyNoteVisual"
SEND = "Daily.ButtonClubSendGift"
SEND_NEXT = "Daily.ButtonClubSendGiftNext"
MAX_MEMBERS = 5  # 同 KAA：至多切 5 位成员
TIMEOUT = 60.0


def goto_club(rt) -> None:
    def step(f):
        if nav.find(f, TITLE) is not None:
            return True
        for name, wait in ((CLOSE, 0.5), (MENU, 0.5), (MENU_CLUB, 1.0)):  # 奖励框先关（关了就领了）→ 开菜单 → 点社团
            if (m := nav.find(f, name)) is not None:
                nav.tap_match(rt, m)
                rt.sleep(wait)
                return None
        return None

    rt.drive(step, TIMEOUT, "进社团页", every=1.0)


def request_note(rt) -> str:
    asked = {"n": 0}

    def step(f):
        if nav.find(f, REQUEST_ONGOING) is not None:
            return "发起了笔记请求" if asked["n"] else "笔记请求进行中"
        if nav.find(f, CONFIRM) is not None:  # 选笔记的窗口：选配置的笔记再确认
            if (m := nav.find(f, NOTE)) is not None:
                nav.tap_match(rt, m)
                rt.sleep(1)
                if (c := nav.find(common.frame(rt), CONFIRM)) is not None:
                    nav.tap_match(rt, c)
                    asked["n"] += 1
                    rt.sleep(0.5)
            return None
        if (m := nav.find(f, REQUEST)) is not None:
            nav.tap_match(rt, m)
            rt.sleep(0.5)
        return None

    return rt.drive(step, TIMEOUT, "发起笔记请求", every=1.0)


def send_gifts(rt) -> int:
    state = {"next": 0, "sent": 0}

    def step(f):
        if (m := nav.find(f, CONFIRM)) is not None:  # 送完的确认框
            nav.tap_match(rt, m)
            rt.sleep(0.5)
            return None
        send = nav.find(f, SEND)
        if send is not None and common.enabled(f, send) is True:
            nav.tap_match(rt, send)
            state["sent"] += 1
            rt.sleep(0.5)
            return None
        nxt = nav.find(f, SEND_NEXT)
        if nxt is not None:
            nav.tap_match(rt, nxt)
            state["next"] += 1
            if state["next"] >= MAX_MEMBERS:
                return True
            rt.sleep(0.5)
            return None
        return True  # 没有下一位、送礼按钮也没有或是灰的：送完了（KAA 碰到灰按钮会一直等到超时）

    rt.drive(step, TIMEOUT, "送社团礼物", every=1.0)
    return state["sent"]


def run(rt, *, request: bool = True, send: bool = True) -> str:
    nav.goto_home(rt)
    goto_club(rt)
    out = []
    if request:
        out.append(request_note(rt))
    if send:
        out.append(f"送礼 {send_gifts(rt)} 次")
    nav.goto_home(rt)
    return "；".join(out)
