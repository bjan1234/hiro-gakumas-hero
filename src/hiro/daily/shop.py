"""商店的デイリー交換所（マニー换东西）：日常任务「ショップで買い物」用。KAA tasks/daily/purchase 的思路，按 OCR 文字做（没有 KAA 的模板）。

首页「ショップ」→「デイリー交换所」（マニー页签）→ 按设置逐个点商品，交換確認框里读商品名，要买就「決定」，不要就「キャンセル」。
- HIRO_SHOP：`off`（缺省，不进商店：花マニー的事默认不做，开局页的日常选项会显式传）/ `recommended` = 买标「おすすめ」的，
  一个都没有时买最便宜的一件（让日常任务完成）/ `all` = 能买的都买。
- HIRO_SHOP_ITEMS：另外要买的商品名（逗号分隔，名字里包含这几个字就算，如「倉本千奈のピース,再挑戦」）。
- 只用マニー：交換確認框里必须有「マニーを使用して」，看到「ジュエル」一律キャンセル；「リスト更新」不点。
- HIRO_SHOP_AP（可选，缺省不买）：AP 页签（用体力换）买哪几样，逗号分隔：pt（入手サポート強化Ptアップ）/ note（入手ノート数アップ）
  / retry（再挑戦チケット）/ regen（メモリー再生成チケット）。每样每天 2 次、一次 10 AP，确认框缺省就是能买的最多个数，点「決定」一次买完。
  确认框里必须是「APを使用して」。11-25 DMM 实测：AP 页签只有这 4 样，一行。

11-25 DMM 实测的画面（720x1280）：一屏 4 列 3 行，每格下面「あと N回」（还能买几次），格子上沿左边「おすすめ」；
慢慢往上滑（1.2 秒）才滚得动，一共 18 件；交換確認框：商品名在「マニーを使用して…」下面一行，「キャンセル」(168,1143)、「決定」(490,1140)。
"""

from __future__ import annotations

import logging
import os
import re

from hiro.daily import common
from hiro.daily.names import item_name
from hiro.runtime import nav

logger = logging.getLogger(__name__)

TIMEOUT = 40.0
SWIPE = (450, 850, 450, 350)  # 商品格里往上滑（快滑滚不动）
SWIPE_S = 1.2
MAX_SCREENS = 4
MAX_BUYS = 30


AP_ITEMS = {"pt": "サポート強化Pt", "note": "ノート数", "retry": "再挑戦", "regen": "再生成"}


def ap_wanted() -> list[str]:
    return [k for k in (x.strip().lower() for x in (os.environ.get("HIRO_SHOP_AP") or "").split(",")) if k in AP_ITEMS]


def mode() -> str:
    v = (os.environ.get("HIRO_SHOP") or "off").strip().lower()
    return v if v in ("recommended", "all", "off") else "off"


def wanted_names() -> list[str]:
    return [x.strip() for x in (os.environ.get("HIRO_SHOP_ITEMS") or "").split(",") if x.strip()]


def _norm(s: str) -> str:
    """商品名比较用：fold（全角半角等）+ 长音和「一」不分、去掉空白和括号。OCR 常把「ピース」读成「ピ一ス」。"""
    from hiro.vision.textnorm import fold

    s = fold(s).replace("一", "ー").replace("-", "ー")
    return re.sub(r"[\s\[\]【】()（）|Il]", "", s)


def name_wanted(name: str, wants: list[str]) -> bool:
    """wants 里的名字中日文都行：和读到的日文名比，也和它的中文译名（names.item_name）比。"""
    n, z = _norm(name), _norm(item_name(name))
    return any(_norm(w) and (_norm(w) in n or _norm(w) in z) for w in wants)


def text_at(f, word: str, *, y_min: int = 0, y_max: int = 1280, x_min: int = 0, x_max: int = 720):
    for t in f.texts:
        x, y = t.rect.center
        if word in t.text and y_min <= y <= y_max and x_min <= x <= x_max:
            return t
    return None


def tiles(f) -> list[dict]:
    """这一屏的商品格：{x, y（点哪里）, left（还能买几次）, price, recommended}。按「あと N回」定位格子。"""
    out = []
    for t in f.texts:
        m = re.search(r"あと\s*(\d+)\s*回", t.text)
        if not m:
            continue
        cx, cy = t.rect.center
        if cy > 1060:  # 页签 / 底栏
            continue
        price = None
        for p in f.texts:
            px, py = p.rect.center
            if abs(px - cx) < 75 and 0 < cy - py < 50 and (pm := re.fullmatch(r"[\d,]+", p.text.strip())):
                price = int(pm.group(0).replace(",", ""))
        rec = any(
            "おすすめ" in r.text and abs(r.rect.center.x - cx) < 85 and 150 < cy - r.rect.center.y < 230
            for r in f.texts
        )
        out.append({"x": cx, "y": cy - 110, "left": int(m.group(1)), "price": price, "recommended": rec})
    return sorted(out, key=lambda d: (d["y"] // 50, d["x"]))


def read_dialog(f) -> dict | None:
    """交換確認框：{name, money（用マニー）, jewel（有ジュエル字样）}；不是这个框 None。"""
    if text_at(f, "交換確認") is None:
        return None
    head = text_at(f, "を使用して")
    name = None
    if head is not None:
        below = [t for t in f.texts if 20 < t.rect.center.y - head.rect.center.y < 110 and t.rect.x1 > 150]
        if below:
            name = min(below, key=lambda t: t.rect.center.y).text.strip()
    texts = " ".join(t.text for t in f.texts)
    return {
        "name": name,
        "money": head is not None and "マニー" in head.text,
        "ap": head is not None and "AP" in head.text.upper(),
        "jewel": "ジュエル" in texts,
    }


def goto_daily_exchange(rt) -> bool:
    """首页 → ショップ → デイリー交換所（マニー页签）。到了返回 True。"""
    nav.goto_home(rt)

    def step(f):
        if text_at(f, "デイリー交換所", y_max=80) is not None:
            if (tab := text_at(f, "マニー", y_min=1050, y_max=1120)) is not None:
                rt.device.tap(*tab.rect.center)  # マニー 页签（不碰 AP）
                rt.sleep(0.8)
            return True
        if (t := text_at(f, "デイリー交換所", y_min=850)) is not None and text_at(f, "ショップ", y_max=80) is not None:
            rt.device.tap(*t.rect.center)
            rt.sleep(2)
            return None
        if nav.at_home(f) and (t := text_at(f, "ショップ", y_min=940, y_max=1010, x_min=500)) is not None:
            rt.device.tap(t.rect.center.x + 40, t.rect.center.y - 50)  # 「ショップ」字上面的图标
            rt.sleep(2.5)
        return None

    return bool(rt.drive(step, TIMEOUT, "进每日兑换所", every=0.8))


def wait_dialog(rt, gone: bool = False):
    ok, f = rt.wait_until(lambda f: (read_dialog(f) is None) if gone else (read_dialog(f) is not None), 6.0, every=0.5)
    return f if ok else None


def tap_word(rt, f, word: str, **kw) -> bool:
    if (t := text_at(f, word, **kw)) is not None:
        rt.device.tap(*t.rect.center)
        return True
    return False


def confirm(rt, g) -> bool:
    """在交換確認框点「決定」：框关了（买成了）返回 True，顺手关掉买完的提示；6 秒还在（按钮灰 = 不够）点キャンセル 返回 False。
    原来只等 1.5 秒，框关得慢就当成不够、买成了也没记上（review）。"""
    tap_word(rt, g, "決定", y_min=1080)
    if wait_dialog(rt, gone=True) is None:
        tap_word(rt, common.frame(rt), "キャンセル", y_min=1080)
        wait_dialog(rt, gone=True)
        return False
    for _ in range(3):  # 买完的提示框
        h = common.frame(rt)
        if not (tap_word(rt, h, "閉じる", y_min=900) or tap_word(rt, h, "OK", y_min=900)):
            break
        rt.sleep(0.8)
    return True


def cost(f) -> int | None:
    """交換確認框最下面「持有 → 换完后」那一行算出的花费（前 − 后）；读不到 None。"""
    nums = []
    for t in f.texts:
        if 940 < t.rect.center.y < 1060 and (m := re.fullmatch(r"[\d,]+", t.text.strip())):
            nums.append((t.rect.center.x, int(m.group(0).replace(",", ""))))
    if len(nums) < 2:
        return None
    nums.sort()
    return nums[0][1] - nums[-1][1]


def buy_ap(rt, keys: list[str]) -> list[str]:
    """在デイリー交換所切到 AP 页签，买 keys 对应的几样（按确认框里的名字认），返回买到的名字。"""
    f = common.frame(rt)
    if not tap_word(rt, f, "AP", y_min=1050, y_max=1120, x_min=400):
        return []
    rt.sleep(1.5)
    got: list[str] = []
    for tile in tiles(common.frame(rt)):
        if tile["left"] <= 0:
            continue
        rt.device.tap(tile["x"], tile["y"])
        g = wait_dialog(rt)
        if g is None:
            continue
        d = read_dialog(g)
        name = (d or {}).get("name") or ""
        want = d is not None and d["ap"] and not d["jewel"] and any(AP_ITEMS[k] in name for k in keys)
        if not want:
            tap_word(rt, g, "キャンセル", y_min=1080)
            wait_dialog(rt, gone=True)
            continue
        if not confirm(rt, g):  # 缺省数量就是能买的最多；没买成 = 体力不够
            break
        got.append(name)
        logger.info("AP 商店买了：%s", name)
    return got


def run(rt) -> str:
    m = mode()
    ap_keys = ap_wanted()
    if m == "off" and not ap_keys:
        return "商店：设置里关了"
    names = wanted_names()
    if not goto_daily_exchange(rt):
        return "商店：没进到每日兑换所"
    bought: list[str] = []
    skip: set[tuple] = set()  # 看过框、决定不买的格子（屏号, x, y）：买了别的之后重读这一屏时不再点开
    cheapest: dict | None = None  # recommended 模式一个おすすめ都没有时：最便宜的那件（屏号, 格）
    no_money = False
    screens = 0
    last_sig = None
    while m != "off" and screens < MAX_SCREENS and len(bought) < MAX_BUYS and not no_money:
        f = common.frame(rt)
        sig = tuple((t.text, t.rect.center.y // 20) for t in f.texts if t.rect.center.y < 1060)
        if sig == last_sig:
            break  # 滑不动了：到底
        last_sig = sig
        acted = False
        for tile in tiles(f):
            key = (screens, tile["x"] // 20, tile["y"] // 20)
            if tile["left"] <= 0 or key in skip:
                continue
            if m == "recommended" and not names and not tile["recommended"]:
                if tile["price"] is not None and (cheapest is None or tile["price"] < cheapest["price"]):
                    cheapest = {**tile, "screen": screens}
                continue
            rt.device.tap(tile["x"], tile["y"])
            g = wait_dialog(rt)
            if g is None:
                continue
            d = read_dialog(g)
            name = (d or {}).get("name") or "?"
            want = (
                d is not None
                and d["money"]
                and not d["jewel"]
                and (m == "all" or tile["recommended"] or name_wanted(name, names))
            )
            if not want:
                if d is not None and d["jewel"]:
                    logger.warning("兑换确认框里有钻石字样，不买：%s", name)
                skip.add(key)
                tap_word(rt, g, "キャンセル", y_min=1080)
                wait_dialog(rt, gone=True)
                continue
            if not confirm(rt, g):  # 决定点了框不关：マニー不够（按钮灰）
                no_money = True
                break
            bought.append(name)
            logger.info("商店买了：%s", name)
            acted = True
            break  # 画面变了，重新读这一屏
        if acted:
            last_sig = None
            continue
        rt.device.swipe(*SWIPE, duration=SWIPE_S)
        rt.sleep(1.0)
        screens += 1
    if m == "recommended" and not names and not bought and cheapest is not None and not no_money:
        # 一个おすすめ都没有：买最便宜的一件，让「ショップで買い物」完成。滑动距离不固定，回到记下的坐标可能是别的格子
        # （review）：回到顶后逐屏按价格找，确认框里实际扣的マニー也得等于这个价才「決定」，对不上就キャンセル。
        price = cheapest["price"]
        for _ in range(MAX_SCREENS):
            rt.device.swipe(SWIPE[0], SWIPE[3], SWIPE[2], SWIPE[1], duration=SWIPE_S)  # 回到顶
        rt.sleep(1.0)
        done = False
        for _ in range(MAX_SCREENS + 1):
            tile = next((t for t in tiles(common.frame(rt)) if t["price"] == price and t["left"] > 0), None)
            if tile is not None:
                rt.device.tap(tile["x"], tile["y"])
                g = wait_dialog(rt)
                d = read_dialog(g) if g is not None else None
                c = cost(g) if g is not None else None
                # 确认框缺省是能买的最多个（あと N回）：扣的マニー是单价的整数倍、不超过剩余次数才算这件
                same = c is not None and price > 0 and c % price == 0 and 0 < c // price <= tile["left"]
                if g is not None and d is not None and d["money"] and not d["jewel"] and same:
                    if confirm(rt, g):
                        bought.append(d["name"] or "?")
                    done = True
                elif g is not None:
                    logger.info("最便宜那件对不上（价 %s，框里扣 %s），不买", price, cost(g))
                    tap_word(rt, g, "キャンセル", y_min=1080)
                    wait_dialog(rt, gone=True)
                    done = True
            if done:
                break
            rt.device.swipe(*SWIPE, duration=SWIPE_S)
            rt.sleep(1.0)
    ap_got = buy_ap(rt, ap_keys) if ap_keys else []
    nav.goto_home(rt)
    parts = []
    if bought:
        parts.append(
            "商店买了：" + "、".join(item_name(b) for b in bought) + ("（金币不够，没买完）" if no_money else "")
        )
    elif no_money:
        parts.append("商店：金币不够")
    elif m != "off":
        parts.append("商店：没有要买的")
    if ap_keys:
        parts.append(
            "体力商店买了：" + "、".join(item_name(b) for b in ap_got)
            if ap_got
            else "体力商店：没买到（体力不够或今天买过了）"
        )
    return "；".join(parts)
