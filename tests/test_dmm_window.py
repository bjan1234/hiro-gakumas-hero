"""DMM 窗口尺寸（用户 11-14）：客户区按显示器自适应 9:16，开局检查不对就调、调不了停。"""

from types import SimpleNamespace as NS

from hiro.devices.win_window import fit_size


def test_fit_size_rule():
    assert fit_size(1032, 39) == (559, 993)  # 1920x1080 / 150%：工作区 1032 高、外框 39
    assert fit_size(2112, 59) == (1080, 1920)  # 4K：夹到上限
    assert fit_size(900, 39) is None  # 放不下 540x960


def test_open_check_fits_and_notes(monkeypatch):
    from hiro.devices import win_window
    from hiro.runtime import play

    notes = []
    monkeypatch.setenv("HIRO_DEVICE", "dmm")
    monkeypatch.delenv("HIRO_DMM_FIT", raising=False)
    monkeypatch.setattr(win_window, "ensure", lambda: ((600, 1067), (559, 993)))
    dev = NS(screenshot=lambda: None, screen=NS(native=(559, 993)))
    assert play.fit_dmm_window(dev, NS(note=notes.append)) is None and "600x1067 → 559x993" in notes[0]
    dev.screen.native = (600, 1067)  # 调完截图尺寸没变：停
    assert "停下" in play.fit_dmm_window(dev, NS(note=notes.append))
    monkeypatch.setattr(win_window, "ensure", lambda: (_ for _ in ()).throw(RuntimeError("找不到游戏窗口")))
    assert "找不到游戏窗口" in play.fit_dmm_window(dev, NS(note=notes.append))
    monkeypatch.setenv("HIRO_DMM_FIT", "0")
    assert play.fit_dmm_window(dev, NS(note=notes.append)) is None
    monkeypatch.setenv("HIRO_DEVICE", "maatools")
    monkeypatch.delenv("HIRO_DMM_FIT")
    assert play.fit_dmm_window(dev, NS(note=notes.append)) is None  # 不是 DMM 不查
