package main

import (
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/shell"
)

// TestLiveUsage 用真的工具层和真的模型（HIRO_HOME 里配好的服务商）问一句，核对流水账有一行、用量面板能画出来。
// 不碰桌面：界面离屏画，截图写到 HIRO_PREVIEW_OUT。
func TestLiveUsage(t *testing.T) {
	if os.Getenv("HIRO_LIVE") != "usage" {
		t.Skip("设 HIRO_LIVE=usage、HIRO_HOME、HIRO_CLI 才跑（会真的调一次模型）")
	}
	home := os.Getenv("HIRO_HOME")
	hiro := &Hiro{}
	a := &Assistant{Home: home, Keys: fileKeys{Path: filepath.Join(home, "model-keys.json")}, Hiro: hiro}
	hiro.Env = a.jobEnv
	run := &shell.SyncRunner{}
	app := buildApp(appDeps{Home: home, Call: hiro.Call, Hiro: hiro, Assistant: a, Bootstrap: &Bootstrap{Home: home, Hiro: hiro}, Run: run})
	tt := ui.NewTester(app.View, 1280, 800)
	tt.SetScale(2)
	settle := func() {
		for i := 0; i < 20; i++ {
			tt.Frame()
			if run.Drain() == 0 {
				break
			}
		}
		tt.Frame()
	}
	settle()
	before := len(ledgerLines(t, home))
	th := app.NewThread()
	app.Send("今天模型花了多少钱？用 usage 工具查一下。")
	settle()
	rows := ledgerLines(t, home)
	if len(rows) <= before {
		t.Fatalf("流水账没有新行（%d → %d）", before, len(rows))
	}
	for _, r := range rows[before:] {
		t.Logf("row source=%v thread=%v provider=%v model=%v input=%v output=%v cache_read=%v ok=%v",
			r["source"], r["thread"], r["provider"], r["model"], r["input"], r["output"], r["cache_read"], r["ok"])
		if r["thread"] != th.ID || r["source"] != "chat" {
			t.Errorf("行没归到这个对话：%v", r)
		}
	}
	msgs := app.Current().Messages
	t.Logf("回答：%s", strings.TrimSpace(msgs[len(msgs)-1].Text))
	out := os.Getenv("HIRO_PREVIEW_OUT")
	save := func(name string) {
		if out == "" {
			return
		}
		_ = os.MkdirAll(out, 0o755)
		f, err := os.Create(filepath.Join(out, name+".png"))
		if err != nil {
			t.Fatal(err)
		}
		defer f.Close()
		_ = png.Encode(f, tt.Image())
	}
	save("live-chat")
	app.OpenPanel("usage", "")
	settle()
	if !tt.HasText("今天") || !tt.HasText("模型用量") {
		t.Errorf("用量面板 %q", tt.Texts())
	}
	save("live-usage")
}
