package kit

import (
	"testing"

	"github.com/egoist/mygo/ui"
)

func TestSourceTagShowsChineseLabel(t *testing.T) {
	tt := ui.NewTester(func(c *ui.Context) {
		ui.Row(c).Children(func() {
			SourceTag(c, "gnrpa")
			SourceTag(c, "deepseek")
			StatePill(c, "running")
		})
	}, 400, 60)
	for _, s := range []string{"算法", "LLM", "游玩中"} {
		if !tt.HasText(s) {
			t.Errorf("没有 %q：%q", s, tt.Texts())
		}
	}
}

func TestPrimaryButtonClicks(t *testing.T) {
	n := 0
	tt := ui.NewTester(func(c *ui.Context) {
		if Primary(c, "开始").Clicked() {
			n++
		}
	}, 200, 60)
	if err := tt.Click("开始"); err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Errorf("点了 %d 次", n)
	}
}
