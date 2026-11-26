package common

import (
	"testing"
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
