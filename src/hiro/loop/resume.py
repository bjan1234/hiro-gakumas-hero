# 调用 KAA / kotonebot（kotones-auto-assistant，GPL-3.0）
"""继续进行中的 H.I.F 培育（选拔赛 / 本战都可），不依赖 KAA 的 resume_produce_pre。

KAA 的再開流程只认识本战的再開对话框（ResumeDialogHifMain），选拔赛会报「Failed to detect produce scenario」。
这里：首页 → 点「プロデュース中」→ 认「再開する」就点；遇到「プロデュースデータの破棄」（其他端末有进行中的培育）
一律点「キャンセル」并停止——破弃是用户才能做的决定。已经在培育页面时直接开始主循环。
"""

import time

from kaa.config.const import HifScenario
from kaa.kaa_context import init_produce_session
from kaa.tasks.actions.scenes import at_home
from kaa.tasks.produce.session import ProduceSession
from kotonebot import device, logging

from hiro.loop.pause_flag import active_clock  # noqa: E402

logger = logging.getLogger(__name__)

DISCARD_TITLE = "プロデュースデータの破棄"
CANCEL_BUTTON = (218, 1160)  # 破弃对话框左下「キャンセル」
ENTER_TIMEOUT = 40.0


from hiro.loop.errors import ResumeBlocked  # noqa: E402,F401  定义挪到 hiro.loop.errors（不依赖 KAA）
from hiro import imgio
from hiro.vision.ocr import find_text, screen_texts
from hiro.vision.ui_templates import box, tap, tpl


def _discard_dialog_visible(img) -> bool:
    """「プロデュースデータの破棄」（其他端末有进行中的培育）。KAA 的 do_produce 会直接按「開始する」破弃，这里绝不这么做。"""
    return bool(tpl("Produce.BreakProduceDialog.Title").exists(img) or find_text(img, "データの破棄"))


def guard_new(*, timeout: float = 15.0) -> None:
    """新开培育前的保护：从首页点「プロデュース中」看是否已有进行中的培育。
    有破弃提示 → 取消并抛 ResumeBlocked；有「再開する」→ 抛 ResumeBlocked（应改用 resume）；看到剧本 Logo 才放行。"""
    device.screenshot()
    if not at_home():
        return  # 不在首页：交给 do_produce 自己导航；它遇到破弃对话框时 kaa_patches.NeverConfirmDiscard 只点キャンセル 并抛 ResumeBlocked
    device.click(*box("Produce.BoxProduceOngoing").center)
    deadline = active_clock() + timeout  # 录屏暂停期间不计时（hiro.loop.pause_flag）
    while active_clock() < deadline:
        time.sleep(1)
        img = device.screenshot()
        if _discard_dialog_visible(img):
            device.click(*CANCEL_BUTTON)
            raise ResumeBlocked(f"游戏提示「{DISCARD_TITLE}」：其他端末有进行中的培育，新开会把它破弃。已点「キャンセル」，不自动新开；是否破弃由用户决定。")
        if tpl("Produce.ButtonResume").exists(img):
            raise ResumeBlocked("本机有进行中的培育（看到「再開する」），请用 `run_hif resume` 继续，而不是新开。")
        if any(tpl(f"Produce.{logo}").exists(img) for logo in ("LogoHajime", "LogoNia", "LogoHif")):
            return
    raise TimeoutError("点「プロデュース中」后既没有再開对话框也没有剧本选择页")


RESUME_FORBIDDEN = ("破棄", "開始する")  # 有这些字就不是「再開」对话框，绝不点


def resume_button(boxes):
    """「プロデュース再開」对话框的「再開する」按钮（OCR 判，KAA 的 ButtonResume 模板在第二十局日期切换后没认出，40s 超时）。
    boxes：hiro.vision.ocr.screen_texts 的结果（.text / .rect）。只在标题「プロデュース再開」+ 按钮「再開する」都在、且没有破棄 / 開始する 时返回按钮。"""
    texts = [b.text.replace(" ", "") for b in boxes]
    if not any("プロデュース再開" in t for t in texts) or any(k in t for t in texts for k in RESUME_FORBIDDEN):
        return None
    return next((b for b in boxes if b.text.replace(" ", "").strip() == "再開する"), None)


def _click_resume_by_ocr(img) -> bool:
    btn = resume_button(screen_texts(img))
    if btn is None:
        return False
    logger.info("点「再開する」（OCR）")
    device.click(*btn.rect.center)
    time.sleep(3)
    return True


LOGIN_BONUS_MAX_PAGES = 10


def skip_login_bonus(*, shoot=None, click=None, sleep=time.sleep) -> bool:
    """续跑开局停在活动登录奖励（培育外）上：点底部空白翻掉，返回翻过没有。
    DMM dmm2 -r4：画面认不出就当「已在培育内（unknown）」进了主循环，翻过奖励后到首页却不会点「プロデュース中」，眼看 180s 停机。"""
    from hiro.vision.quick import quick_page

    shoot = shoot or device.screenshot
    click = click or (lambda x, y: device.click(x, y))
    tapped = False
    for _ in range(LOGIN_BONUS_MAX_PAGES):
        q = quick_page(shoot())
        if not q or q.get("page") != "TRANSITION" or (q.get("fields") or {}).get("kind") != "login_bonus" or not q.get("tap"):
            break
        logger.info("续跑开局：活动登录奖励，点底部空白 %s", q["tap"])
        click(*q["tap"])
        tapped = True
        sleep(1.5)
    return tapped


def enter_produce(*, timeout: float = ENTER_TIMEOUT) -> str:
    """从首页进入进行中的培育。返回进入方式：already / resumed。"""
    from hiro.vision.scene import classify_current

    if _click_resume_by_ocr(device.screenshot()):
        # 首页上挂着「プロデュース再開」对话框时 at_home 为假、整页判 unknown，旧逻辑当成「已在培育内」直接开主循环（第二十局 04:02）
        return "resumed"
    if not at_home() and skip_login_bonus():
        device.screenshot()
    if not at_home():
        scene = classify_current()
        if scene.area == "produce" or scene.scene in ("commu", "unknown"):
            logger.info("已在培育内（%s），直接开始主循环", scene.scene)
            return "already"
    deadline = active_clock() + timeout  # 录屏暂停期间不计时（hiro.loop.pause_flag）
    clicked_ongoing = False
    while active_clock() < deadline:
        img = device.screenshot()
        if _discard_dialog_visible(img):
            device.click(*CANCEL_BUTTON)
            raise ResumeBlocked(
                f"游戏提示「{DISCARD_TITLE}」：进行中的培育在其他端末。已点「キャンセル」。"
                "请在原端末「保存して中断」后再运行，或由用户决定是否破弃并新开。"
            )
        if tap("Produce.ButtonResume", img, device.click):
            logger.info("点「再開する」")
            time.sleep(3)
            if not tpl("Produce.ButtonResume").exists(device.screenshot()) and not at_home():
                return "resumed"
            continue
        if _click_resume_by_ocr(img):
            return "resumed"
        if at_home() and not clicked_ongoing:
            logger.info("点「プロデュース中」")
            device.click(*box("Produce.BoxProduceOngoing").center)
            clicked_ongoing = True
            time.sleep(2)
            continue
        if not at_home():
            scene = classify_current()
            if scene.area == "produce":
                return "resumed"
        time.sleep(1)
    raise TimeoutError(f"{timeout:.0f}s 内没有进入培育")


def run(scenario: HifScenario, strategy_cls, controller_cls, *, idol: str | None) -> None:
    how = enter_produce()
    logger.info("进入培育：%s", how)
    init_produce_session(ProduceSession(idol_card=idol or "", scenario=scenario, is_resumed=True, deck=None))
    controller = controller_cls(scenario=scenario, strategy=strategy_cls)
    controller.run()


END_BUTTON_TEXTS = ("次へ", "閉じる", "OK", "スキップ", "決定", "完了する")  # 完了する：选拔赛通过证书页
# 登录奖励 / 活动获得画面（第二十六局 4 点日切换后「学マ水曜日」ガシャチケット，点空白继续共 4 屏）：正中央是奖励道具框，
# 点中央不翻页，180s 后停机。这类画面没有按钮，点底部空白推进；有购买 / ジュエル字样一律不点
REWARD_HINTS = ("ログインボーナス", "ガシャチケット", "獲得", "開催期間", "受け取りました", "プレゼント", "TAP", "タップ")
REWARD_DANGER = ("購入", "ジュエル", "有償", "課金")
REWARD_TAP = (360, 1180)


def reward_tap(boxes) -> tuple[int, int] | None:
    """领奖 / 活动获得画面 → 底部空白的点击位置；不是、有危险字样、或底部那块有文字（可能是按钮）时 None。
    boxes：.text / .rect.center（kotonebot ocr）。"""
    texts = [t.text.replace(" ", "") for t in boxes]
    if not any(h in t for t in texts for h in REWARD_HINTS) or any(d in t for t in texts for d in REWARD_DANGER):
        return None
    x, y = REWARD_TAP
    if any(abs(t.rect.center.x - x) <= 200 and abs(t.rect.center.y - y) <= 60 for t in boxes):
        return None
    return REWARD_TAP


def is_home_move_confirm(texts: list[str]) -> bool:
    """「ホーム移動確認」弹窗：标题或正文「ホームに移動しますか」「プロデュース > 本戦」任一命中。"""
    joined = "".join(t.replace(" ", "") for t in texts)
    return "ホーム移動" in joined or "ホームに移動" in joined or ("ホーム" in joined and "本戦」から開始" in joined)


def _assist_step(assist, img, boxes) -> bool:
    """screen_texts 的框（.text / .rect）→ assist.step 的 (text, conf, (x1, y1, x2, y2))；出任何错都当没处理（不打断收尾流程）。"""
    try:
        tb = [(t.text, 1.0, (int(t.rect.x1), int(t.rect.y1), int(t.rect.x2), int(t.rect.y2))) for t in boxes]
        return assist.step(img, tb)
    except Exception as e:  # noqa: BLE001
        logger.debug("收尾阶段认不出画面处理出错：%r", e)
        return False


def finish_produce_end(*, timeout: float = 180.0, go_home: bool = False) -> bool:
    """把培育结束后的结算画面（「プロデュース完了」、获得道具、升级、活动积分、关注制作人等）点回首页。
    KAA 的 goto_home 不认 H.I.F 的「プロデュース完了」页；这里按时间封顶（kotonebot Loop 不检查 timeout）。
    不点「再挑戦」「生成」以外的花费类按钮；关注制作人一律跳过。返回是否回到首页。"""
    from kotonebot import device as dev

    from hiro.loop.assist import Assist

    assist = Assist("结算收尾 / 回首页", click=lambda x, y: dev.click(x, y))  # 快速判页 + 卡住交 LLM（同主循环）
    deadline = active_clock() + timeout  # 录屏暂停期间不计时（hiro.loop.pause_flag）
    while active_clock() < deadline:
        img = dev.screenshot()
        if at_home():
            logger.info("结算画面已点完，回到首页")
            return True
        boxes = screen_texts(img)
        texts = [t.text for t in boxes]
        if go_home and is_home_move_confirm(texts):
            # 本战开始确认页点首页会弹「ホーム移動確認」，KAA goto_home 不认，空转（main12 卡 11 分钟）。点 OK 只是回首页，回忆保留
            # 第十八局：OCR 把按钮读成「→OK」、标题读不全，旧判据没命中，卡满 180s。判据放宽 + 按钮包含 OK 即可
            ok = next((t for t in boxes if "OK" in t.text.strip().upper() and t.rect.center.y > 1000), None)
            if ok is not None:
                dev.click(*ok.rect.center)
            else:
                dev.click(500, 1160)
            logger.info("ホーム移動確認：点 OK 回首页（之后从「プロデュース > 本戦」开始）")
            time.sleep(2.0)
            continue
        if go_home and any("開始確認" in t or "本戦へ" in t for t in texts):
            # run_hif new：要从首页走 KAA 的开局流程，这里自己回首页（不点「本戦へ」，开局由 KAA 走带回忆核对的 step4）
            if not tap("Common.ButtonHome", img, dev.click):
                dev.click(85, 1185)  # 左下角首页图标
            time.sleep(1.0)
            continue
        if any("開始確認" in t or "本戦へ" in t for t in texts):
            # 选拔赛通关后游戏直接带到「本战开始确认」：到此为止，是否开本战（花 AP）由上层决定，绝不在这里点
            logger.info("结算后到了培育开始确认页（%s），停止点击", "本战" if any("本戦へ" in t for t in texts) else "新培育")
            return True
        if any("メモリーにするフォト" in t for t in texts):
            # 选回忆照片页（q14：重新登录后不再自动跳过，180s 没回首页）：默认第一张已选中，点「次へ」
            nxt = next((t for t in boxes if t.text.strip() == "次へ"), None)
            dev.click(*nxt.rect.center) if nxt is not None else dev.click(360, 1157)
            logger.info("选回忆照片：用默认第一张，点「次へ」")
            time.sleep(1.5)
            continue
        if any("メモリーとして保存しますか" in t for t in texts):
            # 「選択したフォトをメモリーとして保存しますか? ※保存していないフォトは削除されます」：正常流程，点「決定」
            ok = next((t for t in boxes if t.text.strip() == "決定"), None)
            dev.click(*ok.rect.center) if ok is not None else dev.click(500, 1157)
            logger.info("回忆照片确认：点「決定」")
            time.sleep(1.5)
            continue
        if go_home and tap("Common.ButtonHome", img, dev.click):
            # 不在结算画面、而在带底栏的普通页面（第二十局开局：每日跑完停在サークル页，下面的点中央 / 次へ 都没用，空等 180s）：直接点首页
            logger.info("开局前不在首页（%s）：点底栏首页", " / ".join(texts[:2]))
            time.sleep(1.5)
            continue
        if tap("InProduce.End.ButtonGenerate", img, dev.click):
            logger.info("生成回忆")
        elif tpl("Produce.SaveMemoPic.Title").exists(img):
            tap("Produce.SaveMemoPic.ButtonConfirm", img, dev.click)
        elif any(tap(n, img, dev.click) for n in ("Common.ButtonIconClose", "InProduce.ButtonNextNoIcon", "Common.ButtonNext")):
            pass
        else:
            hit = next((t for t in boxes if t.text.strip() in END_BUTTON_TEXTS and t.rect.center.y > 700), None)  # 同一帧（模板点击不换帧）
            if hit is not None:
                dev.click(*hit.rect.center)
            elif (spot := reward_tap(boxes)) is not None:
                logger.info("登录奖励 / 获得画面（%s）：点底部空白 %s", " / ".join(texts[:3]), spot)
                dev.click(*spot)
            elif _assist_step(assist, img, boxes):
                pass  # 快速判页认出并点了 / LLM 兜底执行了一个受限动作
            else:
                dev.click_center()
        time.sleep(1.2)
    try:  # 超时时存一帧，方便查是哪一页卡住（第十八局这里卡 180s 却没有任何记录）
        from pathlib import Path

        import cv2

        p = Path("reports/live/calib") / f"{time.strftime('%Y%m%d-%H%M%S')}-finish-timeout.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        shot = dev.screenshot()
        imgio.imwrite(str(p), shot)
        logger.warning("结算收尾超时，存帧 %s，画面文字：%s", p, " / ".join(t.text for t in screen_texts(shot))[:200])
    except Exception:  # noqa: BLE001
        pass
    logger.warning("%.0fs 内没有从结算画面回到首页", timeout)
    return False
