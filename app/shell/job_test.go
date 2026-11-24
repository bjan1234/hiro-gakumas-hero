package shell

import (
	"strings"
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

// I4：结束了的任务读到一次之后就不再查事件，即使一条事件都没有。
func TestEndedJobWithoutEventsStopsPolling(t *testing.T) {
	call := &fakeCall{resp: map[string]hiroapi.Result{
		"run status": ok(`{"current":null,"recent":[{"id":"j9","kind":"daily","state":"done","started_at":1}]}`),
		"run events": ok(`{"state":"done","events":[]}`),
	}}
	a, run := newTestApp(newMem(), call, nil, nil)
	a.Job("j9")
	a.PollJobs()
	run.Drain()
	n := len(call.calls)
	for i := 0; i < 3; i++ {
		a.PollJobs()
		run.Drain()
	}
	for _, c := range call.calls[n:] {
		if c[0] == "run" && c[1] == "events" {
			t.Fatalf("结束的任务还在被查：%v", c)
		}
	}
}

// M13：任务停下要用户管时（接手、出错、结束），在对话里冒一条消息，只冒一次。
func TestJobStateChangePostsOnce(t *testing.T) {
	call := liveCall("running")
	a, run := newTestApp(newMem(), call, nil, nil)
	a.NewThread()
	a.PollJobs()
	run.Drain()
	call.resp["run status"] = ok(`{"current":null,"recent":[{"id":"j7","kind":"hajime","state":"failed","summary":"初 · 月村手毬","started_at":1}]}`)
	call.resp["run events"] = ok(`{"state":"failed","events":[]}`)
	for i := 0; i < 3; i++ {
		a.PollJobs()
		run.Drain()
	}
	n := 0
	for _, m := range a.Current().Messages {
		if strings.Contains(m.Text, "出错停下") {
			n++
		}
	}
	if n != 1 {
		t.Errorf("出错消息 %d 条", n)
	}
}

// I1：算上下文用的是界面线程上拍下的快照，后台读不到之后的修改。
func TestContextHostIsSnapshot(t *testing.T) {
	a, run := newTestApp(newMem(), liveCall("running"), nil, nil)
	a.PollJobs()
	run.Drain()
	h := a.snapshotHost()
	a.jobs["j7"].Events = nil
	a.live = ""
	if h.LiveJob() != "j7" || len(h.Job("j7").Steps()) != 1 {
		t.Error("快照跟着变了")
	}
}
