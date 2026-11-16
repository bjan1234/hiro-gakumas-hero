"""回忆选择页（hiro.produce.memory_picker）离线测试：总控上次扫描留下的半分辨率实拍帧（放大到 720x1280）。"""

import json
from pathlib import Path

import cv2
import pytest

import hiro  # noqa: F401
from hiro.produce import memory_picker as mp
from hiro.produce import ops

FIX = Path(__file__).parent / "fixtures" / "memory"


def frame(name):
    return cv2.resize(cv2.imread(str(FIX / name)), (720, 1280))


@pytest.mark.lowres_sample("回忆选择页样例 picker-*.jpg 是 360x640 截图放大，RapidOCR 读不出「開始時 / 後に獲得」；DMM 回忆页待编成库存扫描取实机帧补进回归集")
def test_page_readers_on_real_frames():
    p1 = frame("picker-p1-daydreaming.jpg")
    b = ops.ocr_boxes(p1)
    assert mp.picker_open(b) and mp.detail_page(b) == 1
    assert mp.read_stats(b) == {"Vo": 139, "Da": 130, "Vi": 15, "hp": 0}
    card = mp.read_card_page(b)
    assert card["timing"] == "start" and card["card"]["card_id"] == "p_card-02-act-1_037" and card["card"]["upgrade"] == 1
    k = mp.read_card_page(ops.ocr_boxes(frame("picker-p1-kamifubuki.jpg")))
    assert k["timing"] == "mid" and k["card"]["card_id"] == "p_card-02-act-2_062"


@pytest.mark.lowres_sample("回忆选择页样例 picker-*.jpg 是 360x640 截图放大，RapidOCR 读不出「開始時 / 後に獲得」；DMM 回忆页待编成库存扫描取实机帧补进回归集")
def test_ability_tiles_grouped():
    ab = mp.read_ability_page(ops.ocr_boxes(frame("picker-p2.jpg")))
    texts = [a["text"] for a in ab]
    assert any("初期Pポイント+30" in t for t in texts) and any("初期ビジュアル上昇+15" in t for t in texts)
    assert sum(a["disabled"] for a in ab) == 2  # 两张【センス専用】发動不可
    assert all("センス専用" in a["text"] for a in ab if a["disabled"])


@pytest.mark.parametrize("name", ["picker-p1-daydreaming.jpg", "picker-p1-kamifubuki.jpg", "picker-p2.jpg"])
def test_grid_three_full_rows_nine_cells(name):
    img = frame(name)
    rows = mp.grid_rows(img)
    assert len(rows) in (2, 3) and all(108 <= y2 - y1 <= 128 and y2 <= mp.ROW_BOTTOM_MAX for y1, y2 in rows)  # 压到浮动按钮的行不算
    cells = mp.grid_cells(img)
    assert len(cells) == 3 * len(rows) and len({c["hash"] for c in cells}) == len(cells)
    assert [c["center"][0] for c in cells[:3]] == list(mp.COL_X)


class FakeDevice:
    def __init__(self):
        self.frames = {"p1": frame("picker-p1-daydreaming.jpg"), "p2": frame("picker-p2.jpg"),
                       "closed": cv2.imread(str(Path(__file__).parent / "fixtures" / "shop" / "consult-r5.jpg"))}  # fmt: skip
        self.state, self.taps, self.swipes, self.t, self._ocr = "p1", [], 0, 0.0, {}

    def shoot(self):
        return self.frames[self.state]

    def click(self, x, y):
        self.taps.append((x, y))
        near = lambda p: abs(x - p[0]) <= 30 and abs(y - p[1]) <= 30  # noqa: E731
        if near(mp.PAGE_NEXT) and self.state == "p1":
            self.state = "p2"
        elif near(mp.PAGE_PREV) and self.state == "p2":
            self.state = "p1"
        elif near(mp.CANCEL_TAP):
            self.state = "closed"

    def swipe(self, *a):
        self.swipes += 1  # 画面不变 = 到底

    def ocr(self, im):
        key = next(k for k, v in self.frames.items() if v is im)
        if key not in self._ocr:
            self._ocr[key] = ops.ocr_boxes(im)
        return self._ocr[key]

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.mark.lowres_sample("回忆选择页样例 picker-*.jpg 是 360x640 截图放大，RapidOCR 读不出「開始時 / 後に獲得」；DMM 回忆页待编成库存扫描取实机帧补进回归集")
@pytest.mark.fixtures
def test_scan_reads_each_cell_and_cancels(tmp_path):
    dev = FakeDevice()
    picker = mp.Picker(dev.shoot, dev.click, dev.swipe, ocr=dev.ocr, clock=dev.clock, sleep=dev.sleep)
    out = tmp_path / "inv.json"
    inv = mp.scan(picker, out)
    assert len(inv["entries"]) == 3 * len(mp.grid_rows(dev.frames["p1"]))  # 每个格子一条（同内容的回忆分开记，不再按内容去重）
    e = inv["entries"][0]
    assert e["card"]["name"] == "デイドリーミング" and e["timing"] == "start" and any("初期Pポイント" in a["text"] for a in e["abilities"])
    assert inv["complete"] and dev.state == "closed"  # 画面不动 = 到顶也到底
    assert (475, 1160) not in dev.taps  # 从不点「決定」
    assert json.loads(out.read_text(encoding="utf-8"))["entries"][0]["card"]["card_id"] == "p_card-02-act-1_037"


def test_scan_refuses_outside_picker(tmp_path):
    dev = FakeDevice()
    dev.state = "closed"
    picker = mp.Picker(dev.shoot, dev.click, dev.swipe, ocr=dev.ocr, clock=dev.clock, sleep=dev.sleep)
    with pytest.raises(RuntimeError):
        mp.scan(picker, tmp_path / "inv.json")
    assert dev.taps == []


# ---------------------------------------------------------------- 滚动核对（2026-11-01 实机：快滑带惯性，整行漏扫）

import numpy as np

PAGES = [cv2.imread(str(FIX / f"scan-{n}.jpg")) for n in ("0001-page000", "0002-page001", "0003-page002", "0004-page003")]


def list_rows():
    """4 张实拍页的完整行（实机核对过页与页之间没有重叠，行各不相同；压到浮动按钮的行不算）。"""
    out = []
    for img in PAGES:
        for y1, y2 in mp.grid_rows(img):
            out.append(img[y1 : y1 + 118, :].copy())
    return out


class ScrollList:
    """把实拍行按行距 137.5 排成一个长列表，按滚动位置重画回忆格区；fling = 第 k 次上滑多滚的行数。"""

    TOP = 600  # 第 0 行在滚动位置 0 时的上沿

    def __init__(self, fling=None, slop=1.0, stuck=(), copies=1):
        self.rows, self.base = list_rows() * copies, PAGES[0].copy()
        if copies > 1:  # 重复拼接时给每一份打上不同的色块，保证行各不相同
            for i in range(len(self.rows)):
                self.rows[i] = self.rows[i].copy()
                for c in range(3):  # 每格都打一块（压进缩略图区），重复的几份行也对不上
                    x0 = mp.COL_X[c] - 60
                    self.rows[i][30:90, x0 : x0 + 120] = ((i * 37 + c * 80) % 255, (i * 91) % 255, (i * 53 + c * 40) % 255)
        self.slop, self.stuck = slop, set(stuck)
        gap = self.base[575:580, 40:680].reshape(-1, 3).mean(0)
        self.base[mp.GRID_Y[0] : mp.GRID_Y[1] + 60, :] = gap.astype(np.uint8)
        self.offset, self.fling, self.swipes, self.read = 0.0, dict(fling or {}), 0, []
        self.selected = None  # 最后点过的格子 (行, 列)：画橙色选中框（实机：读完一页，选中框留在下一页的重叠行上）
        self.max_offset = (len(self.rows) - 2) * mp.ROW_PITCH

    def shoot(self):
        img = self.base.copy()
        for i, row in enumerate(self.rows):
            y = int(round(self.TOP + i * mp.ROW_PITCH - self.offset))
            y1, y2 = max(y, mp.GRID_Y[0] - 5), min(y + 118, mp.GRID_Y[1] + 60)
            if y2 > y1:
                img[y1:y2] = row[y1 - y : y2 - y]
        if self.selected is not None:
            r, c = self.selected
            y = int(round(self.TOP + r * mp.ROW_PITCH - self.offset))
            x = mp.COL_X[c] - mp.CELL_W // 2
            if mp.GRID_Y[0] <= y and y + 118 <= mp.GRID_Y[1] + 60:
                cv2.rectangle(img, (x + 6, y + 6), (x + mp.CELL_W - 7, y + 111), (0, 140, 255), 12)  # 选中框画在格子里（伸进缩略图区）
        img[1005:1060, 30:690] = (250, 250, 250)  # 浮在列表上的「編成詳細 / 筛选 / 排序」按钮
        return img

    def swipe(self, x1, y1, x2, y2):
        self.swipes += 1
        if self.swipes in self.stuck:
            return  # 这一次滑动没让列表动
        rows = (y1 - y2) * self.slop / mp.ROW_PITCH + (self.fling.pop(self.swipes, 0) if y1 > y2 else 0)
        self.offset = min(max(0.0, self.offset + rows * mp.ROW_PITCH), self.max_offset)

    def row_at(self, y):
        return int((y - self.TOP + self.offset) // mp.ROW_PITCH)


class ListPicker(mp.Picker):
    def __init__(self, lst):
        super().__init__(lst.shoot, lambda x, y: None, lst.swipe, ocr=lambda im: [], clock=lambda: 0.0, sleep=lambda s: None)
        self.lst = lst

    def select(self, cell):
        self.select_checked(cell)

    def select_checked(self, cell):
        rc = (self.lst.row_at(cell["center"][1]), cell["col"])
        self.lst.read.append(rc)
        self.lst.selected = rc
        return True, None

    def read_selected(self):
        r, c = self.lst.read[-1]
        return {"card": {"card_id": f"m{r}-{c}"}}  # 每格内容不同

    def cancel(self):
        return True


def run_scan(tmp_path, lst, monkeypatch):
    monkeypatch.setattr(mp, "picker_open", lambda boxes: True)
    return mp.scan(ListPicker(lst), tmp_path / "inv.json")


@pytest.mark.fixtures
def test_scan_reads_every_row_once(tmp_path, monkeypatch):
    lst = ScrollList()
    lst.offset = 4 * mp.ROW_PITCH  # 从列表中间开始：先滑回顶部
    inv = run_scan(tmp_path, lst, monkeypatch)
    assert sorted(set(lst.read)) == all_cells(lst) and len(lst.read) == len(all_cells(lst))
    assert inv["complete"] and inv["gaps"] == [] and [e["slot"] for e in inv["entries"]] == list(range(len(all_cells(lst))))


@pytest.mark.fixtures
def test_scan_backtracks_after_fling_overshoot(tmp_path, monkeypatch):
    lst = ScrollList(fling={2: 2})  # 第 2 次上滑多滚 2 行（实机快滑的惯性）
    inv = run_scan(tmp_path, lst, monkeypatch)
    assert sorted(set(lst.read)) == all_cells(lst) and len(lst.read) == len(all_cells(lst))
    assert inv["gaps"] == []


def test_row_overlap_tolerates_band_shift():
    img = PAGES[0]
    rows = mp.page_rows(img)
    shifted = np.roll(img, -2, axis=0)  # 行带上下差 2 像素
    assert mp.row_overlap(rows, mp.page_rows(shifted)) == len(rows)
    assert mp.row_overlap(rows, mp.page_rows(PAGES[1])) == 0  # 实机：相邻两页没重叠（漏行）


def all_cells(lst):
    return [(r, c) for r in range(len(lst.rows)) for c in range(3)]


@pytest.mark.fixtures
def test_scan_with_slop_and_occluded_bottom_rows(tmp_path, monkeypatch):
    """第二次实机扫描：每次少滑一点（3%），几页后最下面一行跑到浮动按钮下面、和下一页对不上，最后被误判到底。"""
    lst = ScrollList(slop=0.97, copies=3)  # 36 行
    inv = run_scan(tmp_path, lst, monkeypatch)
    assert sorted(set(lst.read)) == all_cells(lst) and len(lst.read) == len(all_cells(lst))
    assert inv["complete"] and inv["gaps"] == []


@pytest.mark.fixtures
def test_one_stuck_swipe_is_not_the_end(tmp_path, monkeypatch):
    lst = ScrollList(stuck={4}, copies=2)  # 中途有一次滑动没动（不是到底）
    inv = run_scan(tmp_path, lst, monkeypatch)
    assert sorted(set(lst.read)) == all_cells(lst)
    assert inv["complete"]


@pytest.mark.fixtures
def test_occluded_row_is_not_counted():
    lst = ScrollList()
    lst.offset = 0.6 * mp.ROW_PITCH  # 第 3 个完整行的下沿压到按钮下面
    rows = mp.grid_rows(lst.shoot())
    assert rows and all(y2 <= mp.ROW_BOTTOM_MAX for _, y2 in rows)


@pytest.mark.fixtures
def test_scan_stops_at_gap_instead_of_rereading_old_rows(tmp_path, monkeypatch):
    """账号 2 11-15：对不上后往回滑了几行接着记，旧行被当成新行记了一遍又一遍（仕切り直し 记了 7 份），后面行号全偏。
    现在：找不到上一页最后一行就停，complete=False，记 aborted；已记的行号不重复。"""
    lst = ScrollList(fling={4: 5}, copies=3)  # 第 4 次滑动（前两次是回顶部的下滑）多滚 5 行：往回滑能找回来，照常扫完
    inv = run_scan(tmp_path, lst, monkeypatch)
    assert inv["complete"] and not inv.get("aborted") and sorted(set(lst.read)) == all_cells(lst)
    lst = ScrollList(fling={4: 12}, copies=3)  # 多滚 12 行：往回滑 6 行也找不到
    inv = run_scan(tmp_path, lst, monkeypatch)
    assert inv.get("aborted") and not inv["complete"] and inv["gaps"]
    slots = [e["slot"] for e in inv["entries"]]
    assert len(slots) == len(set(slots)) and len(lst.read) == len(set(lst.read))  # 没有重读、没有重号


class StalePicker(ListPicker):
    """点格子后详情栏不刷新：stale 里的格子第一次读到上一格的内容；always 里的格子一直读到上一格的内容。"""

    def __init__(self, lst, stale=(), always=()):
        super().__init__(lst)
        self.stale, self.always, self.seen = set(stale), set(always), {}

    def read_selected(self):
        rc = self.lst.read[-1]
        self.seen[rc] = self.seen.get(rc, 0) + 1
        prev = next((x for x in reversed(self.lst.read) if x != rc), rc)  # 上一个不同的格子（重读时同一格会再记一次）
        if rc in self.always or (rc in self.stale and self.seen[rc] == 1):
            return {"card": {"card_id": f"m{prev[0]}-{prev[1]}"}} if prev != rc else {"card": {"card_id": "x"}}
        return {"card": {"card_id": f"m{rc[0]}-{rc[1]}"}}


@pytest.mark.fixtures
def test_stale_detail_is_reread_or_marked_suspect(tmp_path, monkeypatch):
    """详情栏没刷新（读到上一格的内容、缩略图不同）：再点一次重读；重读还是一样就标 suspect=same_as_prev（formation_plan 不选）。"""
    monkeypatch.setattr(mp, "picker_open", lambda boxes: True)
    lst = ScrollList()
    inv = mp.scan(StalePicker(lst, stale={(1, 1)}, always={(2, 0)}), tmp_path / "inv.json")
    by = {tuple(e["cell"]): e for e in inv["entries"]}
    assert by[(1, 1)]["card"]["card_id"] == "m1-1" and "suspect" not in by[(1, 1)]  # 重读后对了
    assert by[(2, 0)]["suspect"] == "same_as_prev" and inv["suspects"] == 1


def test_mark_suspects_rules():
    es = [{"slot": 0, "thumb": "a", "card": {"card_id": "c1"}}, {"slot": 1, "thumb": "b", "card": {"card_id": "c1"}},
          {"slot": 2, "thumb": "b", "card": {"card_id": "c1"}}, {"slot": 3, "thumb": "c", "card": None},
          {"slot": 4, "thumb": "d", "card": {"card_id": "c4"}, "refreshed": False}]  # fmt: skip
    assert mp.mark_suspects(es) == 3
    # 同内容同缩略图：真的有两份一样的回忆（不是没刷新），不标
    assert [e.get("suspect") for e in es] == [None, "same_as_prev", None, "card_unread", "detail_not_refreshed"]
