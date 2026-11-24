package labels

import "testing"

func TestLogTextStripsPrefix(t *testing.T) {
	cases := map[string]string{
		"[2026-11-23 19:52:24,843] [INFO] [hiro.runtime.finish] 结算画面已点完，回到首页": "结算画面已点完，回到首页",
		"[2026-11-23 19:55:35,905] [ERROR] [__main__] 租借格挑不到合适的卡，停下":          "租借格挑不到合适的卡，停下",
		"已开始": "已开始",
		"":    "",
	}
	for in, want := range cases {
		if got := LogText(in); got != want {
			t.Errorf("LogText(%q) = %q，要 %q", in, got, want)
		}
	}
}

func TestElapsed(t *testing.T) {
	for _, c := range []struct {
		d    float64
		want string
	}{{40, "不到 1 分钟"}, {12*60 + 5, "12 分钟"}, {75 * 60, "1 小时 15 分"}} {
		if got := Elapsed(1000, 1000+c.d); got != c.want {
			t.Errorf("Elapsed(+%v) = %q，要 %q", c.d, got, c.want)
		}
	}
}

func TestNames(t *testing.T) {
	if Page("HIF_EXAM") != "考试中" || Page("NEW_THING") != "NEW_THING" || Page("") != "—" {
		t.Error("页面名")
	}
	if Action("PlayCard") != "出牌" || Kind("hajime") != "初" || State("takeover") != "你在接手" {
		t.Error("动作 / 种类 / 状态")
	}
	for in, want := range map[string]string{"": "自动", "deepseek-flash": "LLM", "rescue": "兜底", "gnrpa": "算法", "community": "规则", "xyz": "xyz"} {
		if got := Source(in); got != want {
			t.Errorf("Source(%q) = %q，要 %q", in, got, want)
		}
	}
	if Attr("Vo") != "声乐" || Attr("vocal") != "声乐" || Attr("assist") != "辅助" {
		t.Error("属性")
	}
}

func TestToolNames(t *testing.T) {
	for in, want := range map[string]string{"info_idols": "查了偶像卡", "info_supports": "查了支援卡", "run_start": "发起开局", "plan_formation": "出了编成方案", "plugin_demo_echo": "用了插件工具", "weird_tool": "weird_tool"} {
		if got := Tool(in); got != want {
			t.Errorf("Tool(%q) = %q，要 %q", in, got, want)
		}
	}
}
