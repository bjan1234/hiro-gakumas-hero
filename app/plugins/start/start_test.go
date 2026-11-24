package start

import (
	"context"
	"strings"
	"testing"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/hiroapi"
	"github.com/matto49/hiro-gakumas-hero/app/plugins/plugintest"
)

func host() *plugintest.Host {
	return plugintest.New(map[string]string{
		"catalog lookup": `{"items":{"i_card-skin-ttmr-3-0012":{"kind":"idols","name":"【Luna say maybe】月村手毬","rarity":"SSR","asset":"idol-i_card-ttmr-3-0012","attr":"Vo"}}}`,
		"catalog sprite": `{"path":"/tmp/none.webp"}`,
		"plan show":      `{"idol":{"name":"月村手毬"},"support":{"set":2,"own":[{"id":"s_card-2-0001","name":"A"},{"id":"s_card-3-0012","name":"B"}]},"memory":{"set":1,"chosen":[]},"notes":[]}`,
		"info idols":     `{"items":[{"id":"i_card-skin-ttmr-3-0012","name":"【Luna say maybe】月村手毬","rarity":"SSR"},{"id":"i_card-skin-hski-3-0001","name":"篠澤広","rarity":"SSR"}]}`,
		"run status": `{"current":null,"recent":[
			{"id":"j1","kind":"hajime","state":"done","summary":"初","started_at":1763900000,"params":{"idol":"i_card-skin-ttmr-3-0012"}},
			{"id":"j2","kind":"hajime","state":"done","summary":"初","started_at":1763910000,"params":{"idol":"i_card-skin-ttmr-3-0012"}},
			{"id":"j3","kind":"nia","state":"failed","summary":"N.I.A","started_at":1763920000,"params":{"idol":"i_card-skin-hski-3-0001"}}]}`,
	})
}

func TestExplainHajime(t *testing.T) {
	h := host()
	p := New()
	// 第一次问：资料库在后台查（假宿主同步完成），第二次就有名字
	p.Explain(h, hiroapi.Pending{Command: "hiro run start hajime --idol i_card-skin-ttmr-3-0012", Summary: "初"})
	e, ok := p.Explain(h, hiroapi.Pending{Command: "hiro run start hajime --idol i_card-skin-ttmr-3-0012", Summary: "初"})
	if !ok {
		t.Fatal("认不出 run start")
	}
	if e.Title != "开一局 初" || !strings.Contains(e.Subtitle, "月村手毬") || !strings.Contains(e.Subtitle, "REGULAR") || e.Attr != "Vo" {
		t.Errorf("解读 %+v", e)
	}
	if e.Art != "/tmp/none.webp" {
		t.Errorf("卡面 %q", e.Art)
	}
	if len(e.Rows) == 0 || !strings.Contains(e.Rows[0][1], "沿用编成方案") || len(e.Thumbs) != 2 {
		t.Errorf("编成行 %+v 小图 %v", e.Rows, e.Thumbs)
	}
	if !strings.Contains(e.Cost, "会操作游戏") {
		t.Errorf("代价 %q", e.Cost)
	}
}

func TestExplainOtherKinds(t *testing.T) {
	h, p := host(), New()
	if e, ok := p.Explain(h, hiroapi.Pending{Command: "hiro run start hif --command resume"}); !ok || e.Title != "接着打 H.I.F" {
		t.Errorf("续打 %+v", e)
	}
	if e, ok := p.Explain(h, hiroapi.Pending{Command: "hiro run start daily"}); !ok || e.Title != "领日常奖励" {
		t.Errorf("日常 %+v", e)
	}
	if _, ok := p.Explain(h, hiroapi.Pending{Command: "hiro write-formation --scenario x"}); ok {
		t.Error("不是 run start 不该认")
	}
}

func TestPanelStartsWithChosenIdol(t *testing.T) {
	h, p := host(), New()
	tt := ui.NewTester(plugintest.PanelView(func(c *ui.Context) { p.Panel(c, h, "") }), 560, 760)
	if err := tt.Click("初"); err != nil {
		t.Fatal(err)
	}
	if err := tt.Click("篠澤広"); err != nil {
		t.Fatalf("偶像列表：%v %q", err, tt.Texts())
	}
	if err := tt.Click("PRO"); err != nil {
		t.Fatal(err)
	}
	if err := tt.Click("发起"); err != nil {
		t.Fatal(err)
	}
	if len(h.RunArgs_) != 1 {
		t.Fatalf("没发起：%v", h.RunArgs_)
	}
	got := strings.Join(h.RunArgs_[0], " ")
	if !strings.Contains(got, "run start hajime --command new --idol i_card-skin-hski-3-0001 --difficulty pro") {
		t.Errorf("参数 %q", got)
	}
}

func TestContextCountsRecentAndFrequent(t *testing.T) {
	h, p := host(), New()
	p.Context(context.Background(), h) // 让资料库名字进缓存
	out := p.Context(context.Background(), h)
	for _, s := range []string{"初", "完成", "月村手毬（2 局）", "N.I.A（1 局）"} {
		if !strings.Contains(out, s) {
			t.Errorf("上下文里没有 %q：\n%s", s, out)
		}
	}
}
