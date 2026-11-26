package main

import (
	"log"
	"os"
	"path/filepath"
	"runtime/debug"
)

// appLogMax 是 app.log 超过多大时启动先清空（只留最近一次运行的排查信息）。
const appLogMax = 4 << 20

// logToHome 把程序自己的日志写到 HIRO_HOME/app.log，崩溃（未捕获的 panic）的调用栈写到 app-crash.log。
// Windows 上界面程序没有控制台：原来日志和崩溃信息都没地方去，11-25 实测切页面整个程序退出，什么线索都没留下。
func logToHome(home string) {
	if err := os.MkdirAll(home, 0o755); err != nil {
		return
	}
	p := filepath.Join(home, "app.log")
	if st, err := os.Stat(p); err == nil && st.Size() > appLogMax {
		_ = os.Remove(p)
	}
	if f, err := os.OpenFile(p, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
		// 只写文件：界面程序（-H=windowsgui）没有能用的 stderr，MultiWriter 遇到第一个写失败就不往后写了
		log.SetOutput(f)
	}
	if f, err := os.OpenFile(filepath.Join(home, "app-crash.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
		_ = debug.SetCrashOutput(f, debug.CrashOptions{})
	}
}
