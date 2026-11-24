package extplugin

import (
	"path/filepath"
	"strings"
)

// forbiddenAct 是插件永远不能发起的命令：确认 / 取消待确认（只能由界面发起）、账号密码。
func forbiddenAct(words []string) bool {
	if len(words) == 0 {
		return true
	}
	switch words[0] {
	case "confirm", "cancel", "secret", "pending":
		return true
	}
	return false
}

// ActAllowed 是 args 在不在清单的 acts 里：某条 act 的词（按空格切）和 args 开头几个词完全一样就算在内，后面的参数随意。
// 大小写不折叠；confirm / cancel / secret 永远不行。
func ActAllowed(acts []string, args []string) bool {
	if forbiddenAct(args) {
		return false
	}
	for _, a := range acts {
		w := strings.Fields(a)
		if len(w) == 0 || len(w) > len(args) || forbiddenAct(w) {
			continue
		}
		ok := true
		for i := range w {
			if w[i] != args[i] {
				ok = false
				break
			}
		}
		if ok {
			return true
		}
	}
	return false
}

// safePath 把插件给的相对路径解析到插件目录（或 HIRO_HOME）里；逃出去的返回 ""。
func safePath(dir, home, rel string) string {
	if rel == "" || filepath.IsAbs(rel) {
		return ""
	}
	for _, base := range []string{dir, home} {
		if base == "" {
			continue
		}
		p := filepath.Join(base, filepath.FromSlash(rel))
		r, err := filepath.Rel(base, p)
		if err == nil && r != ".." && !strings.HasPrefix(r, ".."+string(filepath.Separator)) {
			return p
		}
	}
	return ""
}
