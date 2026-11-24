package main

import (
	"context"
	"encoding/json"
	"path/filepath"
	"testing"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/hiroapi"
	"github.com/matto49/hiro-gakumas-hero/app/shell"
)

func TestBuildAppShowsBuiltinPlugins(t *testing.T) {
	home := t.TempDir()
	ready := func(context.Context) bool { return true }
	call := func(_ context.Context, args []string) hiroapi.Result {
		return hiroapi.Result{OK: true, Data: json.RawMessage(`{}`)}
	}
	a := &Assistant{Home: home, Keys: fileKeys{Path: filepath.Join(home, "model-keys.json")}}
	_ = a.Save(Settings{Provider: "deepseek", WizardDone: true}, "")
	run := &shell.SyncRunner{}
	app := buildApp(appDeps{Home: home, Call: call, Assistant: a, Bootstrap: &Bootstrap{Home: home, Hiro: &Hiro{}}, Ready: ready, Run: run})
	tt := ui.NewTester(app.View, 1280, 800)
	run.Drain() // 环境检查在后台
	tt.Frame()
	for _, s := range []string{"初星助手", "新对话", "开局", "编成方案", "资料库", "游戏运行现状", "管理插件", "设置"} {
		if !tt.HasText(s) {
			t.Errorf("没有 %q：%q", s, tt.Texts())
		}
	}
}
