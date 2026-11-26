"""商店的コインガシャ（用各自的コイン抽，不花ジュエル）：日常任务「コインガシャを引く」用。KAA tasks/daily/capsule_toys 的思路，按 OCR 文字做。

HIRO_COIN_GACHA：要抽哪几个、各几次，写成 `friend:1,sense:2`（friend フレンド / sense センス / logic ロジック / anomaly アノマリー，0 = 不抽）；
`auto` = 按 フレンド → センス → ロジック → アノマリー 的顺序抽 1 次（第一个币够的）；`off`（缺省：花币的事默认不做，开局页的日常选项会显式传）= 不抽。

11-25 DMM 实测：コインガシャ页从上到下四个池，每个池标题「フレンドガシャ（毎月1日 5時00分更新）」下面约 80 像素是「引く 1回10」；
点了弹「コインガシャ確認」（「〇〇コインを消費して」），「ガシャ回数: N回」缺省是能抽的最多次，「－」最少到 0，
「－」「＋」在回数那行下面约 80 像素的左右两头；「決定」后是 Result 页，点「閉じる」回来。
"""

from __future__ import annotations

import logging
import os
import re

from hiro.daily import common
from hiro.daily.shop import tap_word, text_at
from hiro.runtime import nav

logger = logging.getLogger(__name__)

POOLS = {"friend": "フレンド", "sense": "センス", "logic": "ロジック", "anomaly": "アノマリー"}
NAMES = {"friend": "友情", "sense": "感性", "logic": "理性", "anomaly": "非凡"}  # 结果里给人看的
TIMEOUT = 40.0
SWIPE = (600, 950, 600, 300)
SWIPE_S = 1.5
MAX_COUNT_TAPS = 30


def plan() -> list[tuple[str, int]] | str:
    """[(池, 次数)]；auto 返回 "auto"；off 返回 []。"""
    v = (os.environ.get("HIRO_COIN_GACHA") or "off").strip().lower()
    if v == "off":
        return []
    if v == "auto":
        return "auto"
    out = []
    for part in v.split(","):
        k, _, n = part.strip().partition(":")
        if k in POOLS:
            times = int(n) if n.strip().isdigit() else 1
            if times > 0:
                out.append((k, times))
    return out


def _gacha_title(f, pool: str):
    """池的标题（OCR 常把「ガシャ」读成「ガシヤ」）。"""
    for t in f.texts:
        x = t.text.replace("ヤ", "ャ")
        if POOLS[pool] + "ガシャ" in x and t.rect.center.x < 400:
            return t
    return None


def goto_coin_gacha(rt) -> bool:
    nav.goto_home(rt)

    def step(f):
        if text_at(f, "コインガシャ", y_max=80) is not None:
            return True
        if (t := text_at(f, "コインガシャ", y_min=760, y_max=880)) is not None and text_at(
            f, "ショップ", y_max=80
        ) is not None:
            rt.device.tap(*t.rect.center)
            rt.sleep(2.5)
            return None
        if nav.at_home(f) and (t := text_at(f, "ショップ", y_min=940, y_max=1010, x_min=500)) is not None:
            rt.device.tap(t.rect.center.x + 40, t.rect.center.y - 50)
            rt.sleep(2.5)
        return None

    return bool(rt.drive(step, TIMEOUT, "进硬币扭蛋页", every=0.8))


def count(f) -> int | None:
    """确认框里「ガシャ回数: N回」的 N。SIMD OCR 有时把「0回」整个漏掉、只剩「ガシャ回数:」：那一行没有数字也没有别的字时算 0。"""
    for t in f.texts:
        if "回数" not in t.text:
            continue
        if m := re.search(r"(\d+)\s*回\s*$", t.text):
            return int(m.group(1))
        if re.fullmatch(r".*回数\s*[:：]?\s*", t.text):
            return 0
    return None


def find_pool(rt, pool: str):
    """滑到能看见这个池的「引く」，返回 (帧, 标题)；找不到 (帧, None)。先回到顶再往下找。"""
    for _ in range(2):
        rt.device.swipe(SWIPE[0], SWIPE[3], SWIPE[2], SWIPE[1], duration=SWIPE_S)
    rt.sleep(1.0)
    f = common.frame(rt)
    for _ in range(4):
        title = _gacha_title(f, pool)
        if title is not None and title.rect.center.y < 1080:
            return f, title
        rt.device.swipe(*SWIPE, duration=SWIPE_S)
        rt.sleep(1.0)
        f = common.frame(rt)
    return f, None


def draw(rt, pool: str, times: int) -> int:
    """抽 times 次（币不够就抽能抽的），返回实际抽了几次。"""
    _, title = find_pool(rt, pool)
    if title is None:
        logger.info("没找到%s扭蛋", NAMES[pool])
        return 0
    rt.device.tap(360, title.rect.center.y + 80)  # 标题下面的「引く」
    ok, g = rt.wait_until(lambda f: text_at(f, "コインガシャ確認") is not None, 6.0, every=0.5)
    if not ok:
        return 0
    texts = " ".join(t.text for t in g.texts)
    if "ジュエル" in texts or "コインを消費" not in texts.replace(" ", ""):
        logger.warning("扭蛋确认框不是用硬币的，不抽：%s", texts[:120])
        tap_word(rt, g, "キャンセル", y_min=1080)
        return 0
    line = text_at(g, "回数")
    if line is None:
        tap_word(rt, g, "キャンセル", y_min=1080)
        return 0
    y = line.rect.center.y + 80
    minus, plus = (133, y), (586, y)
    rt.device.swipe(500, y, 180, y, duration=0.6)  # 滑块拖到最左（缺省在最右 = 能抽的最多次，可能几十次）
    rt.sleep(0.5)
    n = count(common.frame(rt))
    for _ in range(MAX_COUNT_TAPS):  # 先减到 0（缺省是最多次）
        if n == 0:
            break
        rt.device.tap(*minus)
        rt.sleep(0.3)
        n = count(common.frame(rt))
    if n != 0:
        tap_word(rt, common.frame(rt), "キャンセル", y_min=1080)
        return 0
    for _ in range(times):
        rt.device.tap(*plus)
        rt.sleep(0.3)
    h = common.frame(rt)
    n = count(h) or 0
    if n <= 0 or n > times:  # 币不够一次；或者读数比要的多（OCR 漏读了「回数」后的数字，没减到 0）：不抽，宁可少不可多
        if n > times:
            logger.warning("扭蛋次数读到 %d 次，比要的 %d 次多，不抽", n, times)
        tap_word(rt, h, "キャンセル", y_min=1080)
        return 0
    tap_word(rt, h, "決定", y_min=1080)

    def back(f):
        if (
            text_at(f, "コインガシャ", y_max=80) is not None
            and text_at(f, "コインガシャ確認") is None
            and text_at(f, "Result") is None
        ):
            return True
        if not tap_word(rt, f, "閉じる", y_min=900):
            rt.device.tap(360, 1240)  # 抽卡演出：点下面空白跳过
        return None

    rt.drive(back, 60, "关抽卡结果", every=1.0)
    logger.info("%s扭蛋 抽了 %d 次", NAMES[pool], n)
    return n


def run(rt) -> str:
    p = plan()
    if p == []:
        return "硬币扭蛋：设置里关了"
    if not goto_coin_gacha(rt):
        return "硬币扭蛋：没进到硬币扭蛋页"
    done = []
    if isinstance(p, str):  # auto
        for pool in POOLS:
            if (n := draw(rt, pool, 1)) > 0:
                done.append(f"{NAMES[pool]} {n} 次")
                break
    else:
        for pool, times in p:
            if (n := draw(rt, pool, times)) > 0:
                done.append(f"{NAMES[pool]} {n} 次")
    nav.goto_home(rt)
    return "硬币扭蛋：" + ("、".join(done) if done else "币不够，没抽")
