"""在 Windows 上试 MaaFramework 的 Win32 截图方式能不能截到 DMM 版学マス（缺省只截图，不点）。

    python tools/maafw_probe.py [输出目录]                                    # 每种截图方式各截 5 张，报尺寸、平均亮度、耗时
    python tools/maafw_probe.py 输出目录 --click 976,1816 --input SendMessageWithWindowPos   # 点一下（坐标按原始窗口像素）

    python tools/maafw_probe.py 输出目录 --harness --input SendMessageWithWindowPos  # 不碰游戏：点自己开的测试窗口，量落点精度

点击会真的点到游戏，只在知道这一下点了什么时用（比如打开再关上一个菜单）；游戏以管理员运行，点击要以管理员身份跑。
--harness 开一个 540×960 的测试窗口（普通权限即可），用指定输入方式点 15 个已知位置，每次记下窗口收到的消息坐标和那一刻
真实光标的位置（DMM 版游戏认的是真实光标），报两者相对目标的偏差（像素）。会挪测试窗口、可能动光标：别在有对局时跑。
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
    ap.add_argument("--harness", action="store_true", help="点测试窗口量落点精度，不碰游戏")
    a = ap.parse_args()
    if a.harness:
        return harness(a)
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


def harness(a):
    """测试窗口：收到按下时记消息坐标（event.x / y）和真实光标（相对窗口客户区）。MaaFramework 在另一个线程里点。"""
    import threading
    import tkinter as tk

    from maa.controller import Win32Controller
    from maa.define import MaaWin32InputMethodEnum as I
    from maa.define import MaaWin32ScreencapMethodEnum as S
    from maa.toolkit import Toolkit

    from hiro.device_maafw import input_method, screencap_flags

    os.makedirs(a.out, exist_ok=True)
    W, H = 540, 960
    root = tk.Tk()
    root.title("hiro-maafw-harness")
    root.geometry(f"{W}x{H}+200+40")
    canvas = tk.Canvas(root, width=W, height=H, bg="white", highlightthickness=0)
    canvas.pack()
    hits = []

    def on_down(ev):
        px, py = root.winfo_pointerxy()
        hits.append({"msg": [ev.x, ev.y], "cursor": [px - canvas.winfo_rootx(), py - canvas.winfo_rooty()]})

    canvas.bind("<ButtonPress-1>", on_down)
    targets = [(x, y) for y in (60, 300, 480, 700, 900) for x in (40, 270, 500)]
    rep = {"input": a.input, "targets": targets, "hits": []}

    def run():
        time.sleep(1.0)
        Toolkit.init_option(a.out)
        hwnd = next(w.hwnd for w in Toolkit.find_desktop_windows() if w.window_name == "hiro-maafw-harness")
        c = Win32Controller(hwnd, screencap_method=screencap_flags("FramePool|GDI", S),
                            mouse_method=input_method(a.input, I), keyboard_method=input_method(a.input, I))
        c.set_screenshot_use_raw_size(True)
        c.post_connection().wait()
        for x, y in targets:
            n = len(hits)
            ok = c.post_click(x, y).wait().succeeded
            t0 = time.time()
            while len(hits) == n and time.time() - t0 < 1.0:
                time.sleep(0.02)
            got = hits[n] if len(hits) > n else None
            rep["hits"].append({"target": [x, y], "ok": bool(ok), "got": got})
        root.after(0, root.destroy)

    threading.Thread(target=run, daemon=True).start()
    root.mainloop()
    errs = {k: [] for k in ("msg", "cursor")}
    for h in rep["hits"]:
        if h["got"]:
            for k in errs:
                gx, gy = h["got"][k]
                errs[k].append(max(abs(gx - h["target"][0]), abs(gy - h["target"][1])))
    rep["summary"] = {"received": sum(1 for h in rep["hits"] if h["got"]), "of": len(targets),
                      **{f"{k}_err_max": (max(v) if v else None) for k, v in errs.items()},
                      **{f"{k}_err_mean": (round(sum(v) / len(v), 2) if v else None) for k, v in errs.items()}}
    print(json.dumps(rep["summary"], ensure_ascii=False))
    with open(os.path.join(a.out, "harness.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
