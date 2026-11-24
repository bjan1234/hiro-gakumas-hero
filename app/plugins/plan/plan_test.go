package plan

import (
	"context"
	"strings"
	"testing"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/plugin"
	"github.com/matto49/hiro-gakumas-hero/app/plugins/plugintest"
)

const planJSON = `{"created":"2026-11-23 20:00","idol":{"id":"i_card-skin-ttmr-3-0012","name":"月村手毬"},"main_attr":"Vo",
 "support":{"set":2,"own":[{"id":"s_card-2-0001","name":"一緒に行こう！","attr":"Vo","level":50,"why":["Vo 主力"]}],"rental":{"id":"s_card-3-0070","name":"光に向かって","attr":"Vo"}},
 "memory":{"set":1,"chosen":[{"card_id":"p_card-1","name":"アイドル宣言","upgrade":1,"timing":"start"}]},"notes":["主属性按初定 Vo"]}`

func host() *plugintest.Host {
	return plugintest.New(map[string]string{
		"plan show":      planJSON,
		"catalog lookup": `{"items":{"s_card-2-0001":{"name":"一起去吧！"}}}`,
		"catalog sprite": `{"path":""}`,
	})
}

func TestFormationCardShowsSupportsAndMemories(t *testing.T) {
	h, p := host(), New()
	var card map[string]any
	_ = decode(planJSON, &card)
	v := p.Cards["formation"]
	tt := ui.NewTester(func(c *ui.Context) {
		ui.Column(c).Fill().Children(func() { v(c, h, plugin.Card{"type": "formation", "plan": card}) })
	}, 760, 600)
	for _, s := range []string{"开局编成方案", "月村手毬", "一起去吧！", "租借", "アイドル宣言", "开局"} {
		if !tt.HasText(s) {
			t.Errorf("编成卡没有 %q：%q", s, tt.Texts())
		}
	}
}

func TestWriteFormationAsksConfirm(t *testing.T) {
	h, p := host(), New()
	tt := ui.NewTester(plugintest.PanelView(func(c *ui.Context) { p.Panel(c, h, "") }), 520, 900)
	if err := plugintest.ClickButton(tt, "写进游戏"); err != nil {
		t.Fatalf("%v %q", err, tt.Texts())
	}
	if len(h.RunArgs_) != 1 || strings.Join(h.RunArgs_[0][1:], " ") != "run start write-formation --scenario hajime" {
		t.Errorf("写编成：%v", h.RunArgs_)
	}
}

func TestContextSummarizesPlan(t *testing.T) {
	h, p := host(), New()
	out := p.Context(context.Background(), h)
	for _, s := range []string{"月村手毬", "主属性 声乐", "支援卡编成 2", "回忆编成 1", "11-23"} {
		if !strings.Contains(out, s) {
			t.Errorf("上下文没有 %q：\n%s", s, out)
		}
	}
}
