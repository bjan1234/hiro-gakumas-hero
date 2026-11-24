package shell

import (
	"testing"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/hiroapi"
	"github.com/matto49/hiro-gakumas-hero/app/plugin"
)

func TestClampChatPercent(t *testing.T) {
	for _, c := range []struct{ p, w, want float32 }{
		{55, 1048, 55},                 // 默认：面板 45%
		{10, 1048, 400.0 / 1048 * 100}, // 对话至少 400 px
		{20, 2000, 30},                 // 面板最多 70%
		{95, 1048, 80},                 // 面板至少留一点（不会被拖没）
	} {
		if got := ClampChatPercent(c.p, c.w); got < c.want-0.01 || got > c.want+0.01 {
			t.Errorf("ClampChatPercent(%v, %v) = %v，要 %v", c.p, c.w, got, c.want)
		}
	}
}

func liveCall(state string) *fakeCall {
	return &fakeCall{resp: map[string]hiroapi.Result{
		"run status": ok(`{"current":{"id":"j7","kind":"hajime","state":"` + state + `","summary":"初 · 月村手毬","started_at":1}, "recent":[]}`),
		"run events": ok(`{"state":"` + state + `","events":[{"seq":0,"t":2,"type":"step","text":"选了上课","step":1,"page":"ACTION_SELECT","source":"gnrpa"}]}`),
	}}
}

func TestLiveJobPinnedAndOpensPanel(t *testing.T) {
	reg := viewReg()
	reg.Add(&plugin.Plugin{ID: "cockpit", Name: "游戏运行现状", Panel: func(c *ui.Context, _ plugin.Host, _ string) { ui.Text(c, "实时画面") }})
	a, run := newTestApp(newMem(), liveCall("running"), nil, reg)
	a.PollJobs()
	run.Drain()
	tt := ui.NewTester(a.View, 1280, 800)
	if !tt.HasText("初 · 月村手毬") {
		t.Fatalf("没有钉住的对局卡：%q", tt.Texts())
	}
	if v := a.Job("j7"); v == nil || len(v.Steps()) != 1 || !v.Live() {
		t.Fatalf("任务数据 %+v", v)
	}
	if err := tt.Click("初 · 月村手毬"); err != nil {
		t.Fatal(err)
	}
	tt.Frame()
	if !a.ui.panelOpen || a.ui.panelPlugin != "cockpit" || !tt.HasText("实时画面") {
		t.Errorf("没打开游戏运行现状：%q", tt.Texts())
	}
}

func TestPollingStopsWhenJobEnds(t *testing.T) {
	call := liveCall("done")
	call.resp["run status"] = ok(`{"current":null,"recent":[{"id":"j7","kind":"hajime","state":"done","started_at":1}]}`)
	a, run := newTestApp(newMem(), call, nil, nil)
	a.Job("j7") // 对话里的对局卡要看这局
	a.PollJobs()
	run.Drain()
	if v := a.Job("j7"); v == nil || v.State != "done" || len(v.Events) != 1 {
		t.Fatalf("结束的任务也读一次：%+v", v)
	}
	n := len(call.calls)
	a.PollJobs()
	run.Drain()
	for _, c := range call.calls[n:] {
		if c[0] == "run" && c[1] == "events" {
			t.Errorf("结束了还在读事件：%v", c)
		}
	}
	if a.LiveJob() != "" {
		t.Error("没有活着的任务")
	}
}

func TestConfirmStartOpensPanelOnce(t *testing.T) {
	a, run, _, tt := confirmApp(t, 4102444800)
	a.reg.Add(&plugin.Plugin{ID: "cockpit", Name: "游戏运行现状", Panel: func(c *ui.Context, _ plugin.Host, _ string) {}})
	tt.Click("开始")
	run.Drain()
	if !a.ui.panelOpen || a.ui.panelPlugin != "cockpit" {
		t.Error("开局后自动打开游戏运行现状")
	}
	a.ClosePanel()
	a.onJobStarted(plugin.Card{"type": "run", "jobId": "j7"})
	if a.ui.panelOpen {
		t.Error("同一局关掉后不再自动打开")
	}
}
