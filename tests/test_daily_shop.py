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
    assert item_name("メモリー再生成チケット") == "回忆再生成券"
    assert item_name("入手ノート数アップ") == "笔记获取数提升"


def test_shop_default_off_and_cost(monkeypatch):
    monkeypatch.delenv("HIRO_SHOP", raising=False)
    assert shop.mode() == "off"  # 缺省不进商店（review：领日常奖励不该默认花マニー）
    f = frame(("交換確認", 100, 425), ("2,017,701", 193, 992), ("→", 387, 997), ("2,014,701", 450, 992))
    assert shop.cost(f) == 3000
    assert shop.cost(frame(("2,017,701", 193, 992))) is None


# ---- #122 review：同一天重跑不再兜底买一批、买不起跳过接着看、超时照样报已买的、长名字、扭蛋上限 ----


class _Dev:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, *a, **k):
        pass


class _Rt:
    def __init__(self):
        self.device = _Dev()

    def sleep(self, s):
        pass


def _shop(monkeypatch, screen, goods, money, *, home_raises=False):
    """screen：商店这一屏；goods：格子 x → (名字, 单价, 一次买几个)；money：有多少金币。"""
    from hiro.loop.errors import ResumeBlocked

    rt = _Rt()
    state = {"money": money}
    monkeypatch.setattr(shop, "goto_daily_exchange", lambda rt: True)
    monkeypatch.setattr(shop.common, "frame", lambda rt: screen)
    monkeypatch.setattr(shop, "tap_word", lambda *a, **k: True)

    def dialog(rt, gone=False):
        if gone:
            return screen
        x = rt.device.taps[-1][0]
        name, price, n = goods[x]
        return frame(("交換確認", 100, 425), ("マニーを使用して、以下のアイテムと交換しますか?", 300, 512),
                     (name, 380, 584), (f"{state['money']:,}", 193, 992), (f"{state['money'] - price * n:,}", 450, 992))  # fmt: skip

    def confirm(rt, g):
        x = rt.device.taps[-1][0]
        _, price, n = goods[x]
        if price * n > state["money"]:
            return False
        state["money"] -= price * n
        return True

    def home(rt):
        if home_raises:
            raise ResumeBlocked("回首页超时")

    monkeypatch.setattr(shop, "wait_dialog", dialog)
    monkeypatch.setattr(shop, "confirm", confirm)
    monkeypatch.setattr(shop.nav, "goto_home", home)
    return rt


def test_shop_recommended_sold_out_means_done_today(monkeypatch):
    """おすすめ今天已经买光（あと0回）：算今天买过了，不兜底买最便宜的（原来会按剩余次数整批买）。"""
    monkeypatch.setenv("HIRO_SHOP", "recommended")
    monkeypatch.delenv("HIRO_SHOP_ITEMS", raising=False)
    monkeypatch.delenv("HIRO_SHOP_AP", raising=False)
    screen = frame(("おすすめ", 61, 319), ("3,000", 120, 480), ("あと0回", 104, 509),
                   ("1,000", 290, 480), ("あと2回", 274, 509))  # fmt: skip
    rt = _shop(monkeypatch, screen, {274: ("ノート", 1000, 2)}, 100000)
    r = shop.run(rt)
    assert rt.device.taps == [] and "今天买过了" in r


def test_shop_fallback_only_buys_exactly_one(monkeypatch):
    """没有おすすめ：最便宜那件确认框里一次要买 2 个（扣 2 件的钱）就不买，写明原因。"""
    monkeypatch.setenv("HIRO_SHOP", "recommended")
    monkeypatch.delenv("HIRO_SHOP_ITEMS", raising=False)
    monkeypatch.delenv("HIRO_SHOP_AP", raising=False)
    screen = frame(("1,000", 290, 480), ("あと2回", 274, 509))
    rt = _shop(monkeypatch, screen, {274: ("ノート", 1000, 2)}, 100000)
    r = shop.run(rt)
    assert "一次要买 2 个" in r and "买了" not in r
    screen = frame(("1,000", 290, 480), ("あと1回", 274, 509))
    rt = _shop(monkeypatch, screen, {274: ("ロジックノート", 1000, 1)}, 100000)
    assert "商店买了" in shop.run(rt)


def test_shop_all_skips_unaffordable_and_keeps_going(monkeypatch):
    """all：先碰到买不起的 6,000，后面 3,000 的照样买（CodeRabbit #122）。"""
    monkeypatch.setenv("HIRO_SHOP", "all")
    monkeypatch.delenv("HIRO_SHOP_AP", raising=False)
    screen = frame(("6,000", 120, 480), ("あと1回", 104, 509), ("3,000", 290, 480), ("あと1回", 274, 509))
    rt = _shop(monkeypatch, screen, {104: ("高い物", 6000, 1), 274: ("ロジックノート", 3000, 1)}, 5000)
    r = shop.run(rt)
    assert "商店买了" in r and "有的金币不够" in r


def test_shop_timeout_still_reports_bought(monkeypatch):
    """买完回首页超时（ResumeBlocked）：结果里照样写出买了什么（#122 review）。"""
    monkeypatch.setenv("HIRO_SHOP", "all")
    monkeypatch.delenv("HIRO_SHOP_AP", raising=False)
    screen = frame(("3,000", 120, 480), ("あと1回", 104, 509))
    rt = _shop(monkeypatch, screen, {104: ("ロジックノート", 3000, 1)}, 5000, home_raises=True)
    r = shop.run(rt)
    assert "商店买了" in r and "中途停下" in r


def test_shop_items_ignored_when_off(monkeypatch):
    """不买时「另外要买的」不算（只是推荐 / 全部的补充），也不进商店。"""
    monkeypatch.setenv("HIRO_SHOP", "off")
    monkeypatch.setenv("HIRO_SHOP_ITEMS", "再挑戦")
    monkeypatch.delenv("HIRO_SHOP_AP", raising=False)
    assert shop.run(_Rt()) == "商店：设置里关了"


def test_shop_dialog_reads_long_name():
    """长名字左端靠左（x1 < 150）也读得到（CodeRabbit #122）。"""
    f = frame(("交換確認", 100, 425), ("マニーを使用して、以下のアイテムと交換しますか?", 300, 512))
    f.__dict__["texts"].append(Text("[Wonder Scale]倉本千奈のピース(とても長い名前)", Box(120, 572, 640, 596)))
    assert shop.read_dialog(f)["name"].startswith("[Wonder Scale]")


def test_coin_gacha_times_capped(monkeypatch):
    monkeypatch.setenv("HIRO_COIN_GACHA", "friend:999,sense:3")
    assert coin_gacha.plan() == [("friend", coin_gacha.MAX_TIMES), ("sense", 3)]


def test_shop_can_skip_by_known_price():
    """按名字买：价格只出现在记下来的、不要的商品上才不点开；没见过的价格、和要的同价的照样点开（11-27：挨个点开太慢）。"""
    prices = {"ロジックノート(ボーカル)": 3000, "ロジックノート(ビジュアル)": 3000, "倉本千奈のピース": 1500}
    wants = ["理性笔记（视觉）"]
    assert shop.can_skip(1500, wants, prices)  # 只有碎片是这个价，不要
    assert not shop.can_skip(3000, wants, prices)  # 同价里有要的
    assert not shop.can_skip(4000, wants, prices)  # 没见过的价
    assert not shop.can_skip(None, wants, prices)
    assert not shop.can_skip(1500, [], prices)


def test_shop_skips_known_unwanted_and_learns_prices(monkeypatch):
    monkeypatch.setenv("HIRO_SHOP", "recommended")
    monkeypatch.setenv("HIRO_SHOP_ITEMS", "再挑戦")
    monkeypatch.delenv("HIRO_SHOP_AP", raising=False)
    saved = {}
    monkeypatch.setattr(shop, "load_prices", lambda: {"倉本千奈のピース": 1500})
    monkeypatch.setattr(shop, "save_prices", lambda p: saved.update(p))
    screen = frame(("おすすめ", 61, 319), ("3,000", 120, 480), ("あと1回", 104, 509),
                   ("1,500", 290, 480), ("あと1回", 274, 509), ("2,000", 460, 480), ("あと1回", 444, 509))  # fmt: skip
    goods = {104: ("ロジックノート", 3000, 1), 274: ("倉本千奈のピース", 1500, 1), 444: ("再挑戦チケット", 2000, 1)}
    rt = _shop(monkeypatch, screen, goods, 100000)
    r = shop.run(rt)
    opened = {x for x, _ in rt.device.taps}
    assert 274 not in opened and {104, 444} <= opened  # 碎片（已知不要的价）没点开
    assert "再挑戦チケット" in r or "再挑战" in r
    assert saved.get("再挑戦チケット") == 2000
