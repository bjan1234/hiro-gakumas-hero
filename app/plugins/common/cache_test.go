package common

import (
	"strings"
	"testing"

	"github.com/matto49/hiro-gakumas-hero/app/plugins/plugintest"
)

func TestSplitIdolName(t *testing.T) {
	for in, want := range map[string][2]string{
		"【Campus mode!!】筱泽广": {"Campus mode!!", "筱泽广"},
		"【学園生活】 篠澤広":         {"学園生活", "篠澤広"},
		"篠澤広":                {"", ""},
		"【只有卡名】":             {"", ""},
	} {
		if t1, c1 := SplitIdolName(in); t1 != want[0] || c1 != want[1] {
			t.Errorf("%q → %q %q", in, t1, c1)
		}
	}
}

func TestSetLangRequeriesInChosenLanguage(t *testing.T) {
	// 11-26：设置里切「游戏内容语言」后，名字按新语言重查（catalog lookup --lang ja / zh）
	h := plugintest.New(map[string]string{"catalog lookup": `{"items":{"i_card-x":{"kind":"idols","name":"名字"}}}`})
	c := &Catalog{}
	if got := c.Name(h, "i_card-x", "fallback"); got != "名字" {
		t.Fatalf("查到的名字 %q", got)
	}
	c.SetLang("ja")
	if c.Lang() != "ja" {
		t.Fatal("没换成 ja")
	}
	c.Name(h, "i_card-x", "")
	last := strings.Join(h.Calls[len(h.Calls)-1], " ")
	if !strings.Contains(last, "--lang ja") {
		t.Errorf("换语言后没按 ja 重查：%q", last)
	}
	n := len(h.Calls)
	c.SetLang("ja") // 没变：不清缓存
	c.Name(h, "i_card-x", "")
	if len(h.Calls) != n {
		t.Errorf("语言没变也重查了")
	}
	if c.Name(h, "", "扫描的日文") != "扫描的日文" {
		t.Error("没编号时用 fallback")
	}
}
