package shell

import (
	"strings"
	"testing"
	"time"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/hiroapi"
	"github.com/matto49/hiro-gakumas-hero/app/plugin"
)

func newPagesApp(call *fakeCall, reg *plugin.Registry) (*App, *SyncRunner) {
	if reg == nil {
		reg = viewReg()
	}
	run := &SyncRunner{}
	a := New(Deps{Call: call.Call, Threads: newMem(), Run: run, Home: "/tmp/hiro-test", Now: func() time.Time { return fixedNow },
		OpenIn: func() string { return "" }}, reg)
	return a, run
}

// 11-26：缺省进页面模式（首页），侧栏是各页 + 「问 AI」；对话界面原样保留，点「问 AI」进去、「回到页面」回来。
func TestPagesModeIsDefaultAndSwitchesToChat(t *testing.T) {
	a, _ := newPagesApp(&fakeCall{}, nil)
	if a.Mode() != ModePages {
		t.Fatalf("缺省模式 %q", a.Mode())
	}
	tt := ui.NewTester(a.View, 1280, 800)
	for _, s := range []string{"首页", "开局", "资料库", "问 AI", WelcomeTitle} {
		if !tt.HasText(s) {
			t.Errorf("页面模式没有 %q：%q", s, tt.Texts())
		}
	}
	if tt.HasText("新对话") {
		t.Errorf("页面模式不该有对话列表：%q", tt.Texts())
	}
	if err := tt.Click("问 AI"); err != nil {
		t.Fatal(err)
	}
	tt.Frame()
	if a.Mode() != ModeChat || !tt.HasText("新对话") || !tt.HasText("回到页面") {
		t.Fatalf("点「问 AI」没进对话界面：%s %q", a.Mode(), tt.Texts())
	}
	if err := tt.Click("回到页面"); err != nil {
		t.Fatal(err)
	}
	tt.Frame()
	if a.Mode() != ModePages {
		t.Errorf("没回到页面：%s", a.Mode())
	}
}

func TestOpenInChatStartsInChat(t *testing.T) {
	run := &SyncRunner{}
	a := New(Deps{Call: (&fakeCall{}).Call, Threads: newMem(), Run: run, Now: func() time.Time { return fixedNow },
		OpenIn: func() string { return ModeChat }}, viewReg())
	if a.Mode() != ModeChat {
		t.Errorf("设置成问 AI 时打开就是对话：%s", a.Mode())
	}
}

func TestPagesNavOpensPluginPage(t *testing.T) {
	a, _ := newPagesApp(&fakeCall{}, nil)
	tt := ui.NewTester(a.View, 1280, 800)
	if err := tt.Click("资料库"); err != nil {
		t.Fatal(err)
	}
	tt.Frame()
	if !tt.HasText("资料库面板") {
		t.Errorf("没画资料库：%q", tt.Texts())
	}
	// 插件 OpenPanel 在页面模式里是切页
	a.OpenPanel("start", "x")
	tt.Frame()
	if !tt.HasText("开局面板x") || a.ui.panelOpen {
		t.Errorf("OpenPanel 没切页：%q", tt.Texts())
	}
}

// 页面上「发起」：不写对话，弹出确认框；点「开始」才 confirm，任务开起来后切到游戏运行现状。
func TestPagesRunArgsConfirmsInModal(t *testing.T) {
	call := &fakeCall{resp: map[string]hiroapiResult{
		"run start daily": pendingResult("p1", "领日常奖励"),
		"confirm p1":      ok(`{"job":{"id":"j1"}}`),
	}}
	reg := viewReg()
	reg.Add(&plugin.Plugin{ID: "cockpit", Name: "游戏运行现状", Panel: func(c *ui.Context, _ plugin.Host, route string) { ui.Text(c, "现状"+route) }})
	a, run := newPagesApp(call, reg)
	tt := ui.NewTester(a.View, 1280, 800)
	a.RunArgs("帮我领日常奖励", []string{"run", "start", "daily"})
	run.Drain()
	tt.Frame()
	if len(a.Threads()) != 0 {
		t.Errorf("页面模式不该写进对话：%d 个对话", len(a.Threads()))
	}
	if !tt.HasText("领日常奖励") || !tt.HasText("开始") {
		t.Fatalf("没弹确认框：%q", tt.Texts())
	}
	if call.called("confirm") {
		t.Fatal("没点就 confirm 了")
	}
	if err := tt.Click("开始"); err != nil {
		t.Fatal(err)
	}
	run.Drain()
	tt.Frame()
	if !call.called("confirm p1") {
		t.Fatal("点了开始没 confirm")
	}
	if a.ui.pagePlugin != "cockpit" || a.ui.pageRoute != "job:j1" {
		t.Errorf("开起来后没切到游戏运行现状：%s %s", a.ui.pagePlugin, a.ui.pageRoute)
	}
	if m, c := a.pageWaiting(); c != nil {
		t.Errorf("确认过还在等：%+v %+v", m, c)
	}
}

func TestPagesModalDismissCancels(t *testing.T) {
	call := &fakeCall{resp: map[string]hiroapiResult{"run start daily": pendingResult("p2", "领日常奖励")}}
	a, run := newPagesApp(call, nil)
	tt := ui.NewTester(a.View, 1280, 800)
	a.RunArgs("帮我领日常奖励", []string{"run", "start", "daily"})
	run.Drain()
	tt.Frame()
	if err := tt.Click("先不"); err != nil {
		t.Fatal(err)
	}
	run.Drain()
	if !call.called("cancel p2") {
		t.Error("点「先不」没 cancel")
	}
}

// 出错变成提示条（页面模式没有对话）。
func TestPagesErrorBecomesToast(t *testing.T) {
	call := &fakeCall{resp: map[string]hiroapiResult{"run start daily": {Error: &hiroapi.CliError{Code: "busy", Message: "已经有任务在跑"}}}}
	a, run := newPagesApp(call, nil)
	a.RunArgs("帮我领日常奖励", []string{"run", "start", "daily"})
	run.Drain()
	if len(a.toasts) != 1 || !strings.Contains(a.toasts[0].Title, "已经有任务在跑") || a.toasts[0].Type != "error" {
		t.Errorf("提示条 %+v", a.toasts)
	}
}

// 任务结束：页面上开的、对话里开的都出提示条（两边都显示）。
func TestJobEndToastsInBothModes(t *testing.T) {
	a, _ := newPagesApp(&fakeCall{}, nil)
	a.pages.Messages = append(a.pages.Messages, &Message{ID: "m1", Role: "agent", Cards: []plugin.Card{{"type": "run", "jobId": "j1"}}})
	v := a.Job("j1")
	v.Job = &plugin.Job{ID: "j1", Kind: "daily", Summary: "领日常奖励"}
	v.State = "done"
	a.notify("j1", "running", v)
	if len(a.toasts) != 1 || !strings.Contains(a.toasts[0].Title, "领日常奖励") {
		t.Fatalf("页面上开的局结束没提示：%+v", a.toasts)
	}
	a.toasts = nil
	a.SetMode(ModeChat)
	th := a.NewThread()
	th.Messages = append(th.Messages, &Message{ID: "m2", Role: "agent", Cards: []plugin.Card{{"type": "run", "jobId": "j2"}}})
	v2 := a.Job("j2")
	v2.Job = &plugin.Job{ID: "j2", Kind: "scan-idols", Summary: "扫描偶像卡"}
	v2.State = "failed"
	a.notify("j2", "running", v2)
	if len(a.toasts) != 1 || a.toasts[0].Action != "再试一次" {
		t.Errorf("对话里开的局出错也要提示条（带再试一次）：%+v", a.toasts)
	}
	if n := len(th.Messages); n != 2 {
		t.Errorf("对话里照样有通知：%d 条", n)
	}
}

func TestHomeActionsUsePageThenRun(t *testing.T) {
	ran := ""
	reg := &plugin.Registry{}
	reg.Add(&plugin.Plugin{ID: "start", Name: "开局",
		Starters: func(plugin.Host) []plugin.Starter {
			return []plugin.Starter{
				{Label: "用广再打一把初", Say: "帮我用广打一把初", Page: func(plugin.Host) { ran = "replay" }},
				{Label: "选个偶像开一局", Say: "/开局"},
				{Label: "领日常奖励", Run: func(plugin.Host) { ran = "daily" }},
			}
		},
		Chips: []plugin.Chip{{Label: "领日常奖励", Run: func(plugin.Host) {}}, {Label: "接着打", Run: func(plugin.Host) { ran = "resume" }}}})
	a, _ := newPagesApp(&fakeCall{}, reg)
	acts := a.HomeActions()
	var labels []string
	for _, x := range acts {
		labels = append(labels, x.Label)
	}
	if strings.Join(labels, "|") != "用广再打一把初|领日常奖励|接着打" {
		t.Fatalf("首页按钮 %q", labels)
	}
	acts[0].Run(a)
	if ran != "replay" {
		t.Errorf("再打一把走 Page：%q", ran)
	}
}

// CodeRabbit #138：页面上点「开始」失败（确认框关了），提示条写出原因。
func TestPagesConfirmFailureToasts(t *testing.T) {
	call := &fakeCall{resp: map[string]hiroapiResult{
		"run start daily": pendingResult("p3", "领日常奖励"),
		"confirm p3":      {Error: &hiroapi.CliError{Code: "busy", Message: "已经有任务在跑"}},
	}}
	a, run := newPagesApp(call, nil)
	tt := ui.NewTester(a.View, 1280, 800)
	a.RunArgs("帮我领日常奖励", []string{"run", "start", "daily"})
	run.Drain()
	tt.Frame()
	if err := tt.Click("开始"); err != nil {
		t.Fatal(err)
	}
	run.Drain()
	if len(a.toasts) != 1 || !strings.Contains(a.toasts[0].Title, "没能开始") || !strings.Contains(a.toasts[0].Description, "已经有任务在跑") {
		t.Errorf("提示条 %+v", a.toasts)
	}
}

// 扫描做完的「下一步」按钮在页面模式里变成提示条上的按钮，点了去问 AI。
func TestNextCardBecomesToastAction(t *testing.T) {
	a, _ := newPagesApp(&fakeCall{}, nil)
	a.toastFor("扫描都做完了", []plugin.Card{{"type": "next", "label": "打一把初", "say": "打一把初"}})
	if len(a.toasts) != 1 || a.toasts[0].Action != "打一把初" {
		t.Fatalf("提示条 %+v", a.toasts)
	}
	a.toasts[0].OnAction()
	if a.Mode() != ModeChat {
		t.Error("点了应该去问 AI")
	}
}
