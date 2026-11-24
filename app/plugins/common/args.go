package common

import "strings"

// RunArgs 是一条「hiro run start <kind> …」解析出来的东西。
type RunArgs struct {
	Kind  string
	Flags map[string]string
}

// ParseRunStart 解析待确认里的命令文字；不是 run start 就 ok=false。
func ParseRunStart(command string) (RunArgs, bool) {
	f := strings.Fields(command)
	i := 0
	for i+1 < len(f) && !(f[i] == "run" && f[i+1] == "start") {
		i++
	}
	if i+2 >= len(f) {
		return RunArgs{}, false
	}
	r := RunArgs{Kind: f[i+2], Flags: map[string]string{}}
	for j := i + 3; j < len(f); j++ {
		if strings.HasPrefix(f[j], "--") {
			k := strings.TrimPrefix(f[j], "--")
			if j+1 < len(f) && !strings.HasPrefix(f[j+1], "--") {
				r.Flags[k] = f[j+1]
				j++
			} else {
				r.Flags[k] = "true"
			}
		}
	}
	return r, true
}
