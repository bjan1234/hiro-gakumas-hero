package shell

import (
	"context"
	"testing"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/plugin"
)

func viewReg() *plugin.Registry {
	r := &plugin.Registry{}
	r.Add(&plugin.Plugin{ID: "start", Name: "开局", Panel: func(c *ui.Context, _ plugin.Host, route string) { ui.Text(c, "开局面板"+route) },
		Commands: []plugin.Command{{Name: "开局", Hint: "开一局"}},
		Chips:    []plugin.Chip{{Label: "/开局"}}})
	r.Add(&plugin.Plugin{ID: "library", Name: "资料库", Panel: func(c *ui.Context, _ plugin.Host, _ string) { ui.Text(c, "资料库面板") },
		Commands: []plugin.Command{{Name: "资料库"}, {Name: "扫描", Route: "scan"}}})
	return r
}

func TestViewShowsSidebarThreadsAndPlugins(t *testing.T) {
	a, _ := newTestApp(newMem(oldThread), &fakeCall{}, nil, viewReg())
	tt := ui.NewTester(a.View, 1280, 800)
	for _, s := range []string{"初星助手", "新对话", "用月村手毬打一把初", "开局", "资料库", "帮我用月村手毬打一把初", "要开始吗？"} {
		if !tt.HasText(s) {
			t.Errorf("没有 %q：%q", s, tt.Texts())
		}
	}
}

func TestTypingEnterSendsToAgent(t *testing.T) {
	asked := ""
	ask := func(_ context.Context, _ []Turn, text, _ string, _ func(string, string)) (Reply, error) {
		asked = text
		return Reply{Text: "好的，马上"}, nil
	}
	a, run := newTestApp(newMem(), &fakeCall{}, ask, viewReg())
	tt := ui.NewTester(a.View, 1280, 800)
	tt.Type("你好")
	tt.Key(0, ui.KeyEnter)
	run.Drain()
	tt.Frame()
	if asked != "你好" || !tt.HasText("好的，马上") {
		t.Errorf("问了 %q，界面 %q", asked, tt.Texts())
	}
}

func TestSlashListsCommandsAndOpensPanel(t *testing.T) {
	a, _ := newTestApp(newMem(), &fakeCall{}, nil, viewReg())
	tt := ui.NewTester(a.View, 1280, 800)
	tt.Type("/")
	tt.Frame()
	if !tt.HasText("/开局") || !tt.HasText("/扫描") {
		t.Fatalf("没列出命令：%q", tt.Texts())
	}
	if err := tt.Click("/扫描"); err != nil {
		t.Fatal(err)
	}
	if !a.ui.panelOpen || a.ui.panelPlugin != "library" || a.ui.panelRoute != "scan" {
		t.Errorf("面板 open=%v plugin=%q route=%q", a.ui.panelOpen, a.ui.panelPlugin, a.ui.panelRoute)
	}
}
