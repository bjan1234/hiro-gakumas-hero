"""在 Windows 上试 MaaFramework 的 Win32 截图方式能不能截到 DMM 版学マス（缺省只截图，不点）。

    python tools/maafw_probe.py [输出目录]                                    # 每种截图方式各截 5 张，报尺寸、平均亮度、耗时
    python tools/maafw_probe.py 输出目录 --click 976,1816 --input SendMessageWithWindowPos   # 点一下（坐标按原始窗口像素）

点击会真的点到游戏，只在知道这一下点了什么时用（比如打开再关上一个菜单）；游戏以管理员运行，点击要以管理员身份跑。
要先 pip install maafw pillow。结果写 输出目录/report.json，每种方式的截图写 <方式>.png（全黑说明这种方式截不到）。
"""
import argparse
import ctypes
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

METHODS = ("FramePool", "PrintWindow", "GDI", "ScreenDC", "DXGI_DesktopDup_Window", "DXGI_DesktopDup")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="maafw-probe")
    ap.add_argument("--click", default=None, help="x,y（原始窗口像素）：点一下，前后各截一张")
    ap.add_argument("--input", default="SendMessageWithWindowPos")
    ap.add_argument("--screencap", default="FramePool", help="点击测试时用的截图方式")
    a = ap.parse_args()
    from maa.controller import Win32Controller
    from maa.define import MaaWin32InputMethodEnum as I
    from maa.define import MaaWin32ScreencapMethodEnum as S
    from maa.toolkit import Toolkit
    from PIL import Image

    from hiro.device_maafw import find_window, input_method, screencap_flags

    os.makedirs(a.out, exist_ok=True)
    Toolkit.init_option(a.out)
    win = find_window(Toolkit)
    rep = {"admin": bool(ctypes.windll.shell32.IsUserAnAdmin()), "hwnd": int(win.hwnd), "methods": {}}

    def ctrl(screencap, inp):
        c = Win32Controller(win.hwnd, screencap_method=screencap_flags(screencap, S),
                            mouse_method=input_method(inp, I), keyboard_method=input_method(inp, I))
        c.set_screenshot_use_raw_size(True)
        return c, bool(c.post_connection().wait().succeeded)

    def save(img, name):
        Image.fromarray(img[:, :, ::-1]).save(os.path.join(a.out, name))

    if a.click:
        x, y = (int(v) for v in a.click.split(","))
        c, ok = ctrl(a.screencap, a.input)
        before = c.post_screencap().wait().get()
        t = time.perf_counter()
        job = c.post_click(x, y).wait()
        ms = (time.perf_counter() - t) * 1000
        time.sleep(1.5)
        after = c.post_screencap().wait().get()
        save(before, "click_before.png")
        save(after, "click_after.png")
        diff = float(abs(after.astype(int) - before.astype(int)).mean())
        rep["click"] = {"input": a.input, "xy": [x, y], "connected": ok, "succeeded": bool(job.succeeded), "ms": round(ms, 1),
                        "diff": round(diff, 2)}
        print(json.dumps(rep["click"], ensure_ascii=False))
    else:
        for name in METHODS:
            r = {}
            try:
                c, r["connected"] = ctrl(name, "SendMessage")
                ts, img = [], None
                for _ in range(5):
                    t = time.perf_counter()
                    j = c.post_screencap().wait()
                    ts.append((time.perf_counter() - t) * 1000)
                    if j.succeeded:
                        img = j.get()
                if img is not None:
                    r.update(shape=list(img.shape), mean=round(float(img.mean()), 1), ms=round(sorted(ts)[2], 1))
                    save(img, f"{name}.png")
            except Exception as e:  # noqa: BLE001
                r["error"] = f"{type(e).__name__}: {e}"[:200]
            rep["methods"][name] = r
            print(name, json.dumps(r, ensure_ascii=False), flush=True)
    with open(os.path.join(a.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
