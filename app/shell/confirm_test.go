package shell

import (
	"context"
	"testing"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/hiroapi"
	"github.com/matto49/hiro-gakumas-hero/app/plugin"
)

func confirmApp(t *testing.T, expires float64) (*App, *SyncRunner, *fakeCall, *ui.Tester) {
	t.Helper()
	call := &fakeCall{resp: map[string]hiroapi.Result{
		"confirm p1": ok(`{"job":{"id":"j7","kind":"hajime"}}`),
		"cancel p1":  ok(`{"cancelled":true}`),
	}}
	ask := func(context.Context, []Turn, string, string, func(string, string)) (Reply, error) {
		return Reply{Text: "要开这一局吗？", Cards: []plugin.Card{ConfirmCard(hiroapi.Pending{ID: "p1", Command: "hiro run start hajime --idol i_card-x", Summary: "初", ExpiresAt: expires})}}, nil
	}
	reg := viewReg()
	reg.Add(&plugin.Plugin{ID: "explain", Explain: func(_ plugin.Host, p hiroapi.Pending) (plugin.Explained, bool) {
		return plugin.Explained{Title: "开一局 初", Subtitle: "月村手毬 · 普通", Rows: [][2]string{{"编成", "沿用编成方案"}}, Cost: "会操作游戏 · 用掉 1 次培育"}, true
	}})
	a, run := newTestApp(newMem(), call, ask, reg)
	tt := ui.NewTester(a.View, 1280, 800)
	a.Send("帮我用月村手毬打一把初")
	run.Drain()
	tt.Frame()
	return a, run, call, tt
}

func lastCards(a *App) []plugin.Card {
	ms := a.Current().Messages
	return ms[len(ms)-1].Cards
}

func TestConfirmCardShowsExplanationAndStarts(t *testing.T) {
	a, run, call, tt := confirmApp(t, 4102444800)
	for _, s := range []string{"开一局 初", "月村手毬 · 普通", "沿用编成方案", "会操作游戏 · 用掉 1 次培育", "等你确认", "先不"} {
		if !tt.HasText(s) {
			t.Errorf("确认卡没有 %q：%q", s, tt.Texts())
		}
	}
	snap(t, tt, "confirm-waiting")
	if err := tt.Click("开始"); err != nil {
		t.Fatal(err)
	}
	run.Drain()
	tt.Frame()
	if !call.called("confirm p1") {
		t.Fatal("没调 confirm")
	}
	card := a.Current().Messages[1].Cards[0]
	if card["status"] != "confirmed" {
		t.Errorf("卡状态 %v", card["status"])
	}
	cards := lastCards(a)
	if cards[len(cards)-1]["type"] != "run" || cards[len(cards)-1]["jobId"] != "j7" {
		t.Errorf("没加对局卡：%+v", cards)
	}
	if tt.HasText("先不") {
		t.Error("确认过的卡不该还有按钮")
	}
	// 再按 Enter 不会再确认一次
	n := len(call.calls)
	tt.Key(0, ui.KeyEnter)
	run.Drain()
	if len(call.calls) != n {
		t.Errorf("重复确认：%v", call.calls[n:])
	}
}

func TestEnterOnEmptyInputConfirmsLatest(t *testing.T) {
	_, run, call, tt := confirmApp(t, 4102444800)
	tt.Key(0, ui.KeyEnter)
	run.Drain()
	if !call.called("confirm p1") {
		t.Error("输入框空时 Enter 应确认最新那张")
	}
}

func TestEscCancels(t *testing.T) {
	a, run, call, tt := confirmApp(t, 4102444800)
	tt.Key(0, ui.KeyEscape)
	run.Drain()
	tt.Frame()
	if !call.called("cancel p1") || a.Current().Messages[1].Cards[0]["status"] != "cancelled" {
		t.Errorf("Esc 没取消：%v", call.calls)
	}
}

func TestEnterWithTextSendsInsteadOfConfirming(t *testing.T) {
	_, run, call, tt := confirmApp(t, 4102444800)
	tt.Type("等一下")
	tt.Key(0, ui.KeyEnter)
	run.Drain()
	if call.called("confirm") {
		t.Error("输入框有字时 Enter 不该确认")
	}
}

func TestExpiredConfirmShowsExpired(t *testing.T) {
	_, run, call, tt := confirmApp(t, float64(fixedNow.Unix()-10))
	if !tt.HasText("「初」的确认过期了，再说一次就行") || tt.HasText("先不") {
		t.Errorf("过期显示：%q", tt.Texts())
	}
	tt.Key(0, ui.KeyEnter)
	run.Drain()
	if call.called("confirm") {
		t.Error("过期的不该确认")
	}
}
