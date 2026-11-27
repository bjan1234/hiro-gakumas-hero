package start

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/plugins/common"
	"github.com/matto49/hiro-gakumas-hero/app/plugins/plugintest"
)

func modeIndex(id string) int {
	for i, m := range modes {
		if m.id == id {
			return i
		}
	}
	return -1
}

// 11-27：开局页按场次选快速 / 搜索；缺省照工具层原来的缺省，发起时总带 --exam-search。
func TestExamSearchDefaultsAndArgs(t *testing.T) {
	s := &state{mode: modeIndex("hajime")}
	s.pick.Chosen = common.IdolItem{ID: "i_card-x", Name: "某某"}
	a, _ := s.args()
	if got := strings.Join(a, " "); !strings.Contains(got, "--exam-search mid1,final,lesson") {
		t.Errorf("初缺省全搜：%q", got)
	}
	s.mode = modeIndex("nia")
	if a, _ := s.args(); !strings.Contains(strings.Join(a, " "), "--exam-search none") {
		t.Errorf("N.I.A 缺省都快速：%q", a)
	}
	s.mode, s.hifMain = modeIndex("hif"), 1
	s.search.set("hif-m", "r1", false)
	if a, _ := s.args(); !strings.Contains(strings.Join(a, " "), "--mode main --exam-search r2") {
		t.Errorf("本战只 R2 搜：%q", a)
	}
	s.mode, s.resume = modeIndex("hajime"), true
	if a, _ := s.args(); !strings.Contains(strings.Join(a, " "), "--command resume --exam-search") {
		t.Errorf("接着打也带：%q", a)
	}
	s.mode = modeIndex("daily")
	if a, _ := s.args(); strings.Contains(strings.Join(a, " "), "exam-search") {
		t.Errorf("日常不带：%q", a)
	}
}

func TestExamSearchRow(t *testing.T) {
	row, ok := examSearchRow("hajime", map[string]string{"exam-search": "final"})
	if !ok || row[1] != "搜索：最終試験；快速：中間試験、练习课" {
		t.Errorf("%v %q", ok, row)
	}
	row, _ = examSearchRow("hif", map[string]string{"exam-search": "none", "mode": "main"})
	if row[1] != "快速：本战 R1、本战 R2" {
		t.Errorf("%q", row)
	}
	if _, ok := examSearchRow("hajime", map[string]string{}); ok {
		t.Error("没带参数不写")
	}
}

// 点「搜索 / 快速」存进 HIRO_HOME/start-prefs.json，下次打开照旧。
func TestExamSearchRemembered(t *testing.T) {
	home := t.TempDir()
	h := plugintest.New(map[string]string{})
	h.HomeDir = home
	s := &state{mode: modeIndex("nia")}
	tt := ui.NewTester(func(c *ui.Context) { s.search.draw(c, h, "nia") }, 600, 400)
	tt.Frame()
	if !tt.HasText("第 2 场试镜") {
		t.Fatalf("%q", tt.Texts())
	}
	s.search.set("nia", "final", true)
	s.search.save()
	b, err := os.ReadFile(filepath.Join(home, "start-prefs.json"))
	if err != nil || !strings.Contains(string(b), `"final": true`) {
		t.Fatalf("没存上：%v %s", err, b)
	}
	s2 := &state{}
	s2.search.load(h)
	if a := s2.search.args("nia"); strings.Join(a, " ") != "--exam-search final" {
		t.Errorf("读回来 %q", a)
	}
}
