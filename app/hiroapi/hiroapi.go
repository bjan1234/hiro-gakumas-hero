// Package hiroapi 是工具层（hiro 命令行）信封的类型：界面的子包和 main 都用它。
package hiroapi

import (
	"context"
	"encoding/json"
)

// CliError 是命令失败时信封里的 error：code 给程序判断，message / hint 是写给人看的白话。
type CliError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Hint    string `json:"hint,omitempty"`
}

// Pending 是会动游戏的命令返回的待确认：用户点了确认卡才 confirm。
type Pending struct {
	ID        string  `json:"id"`
	Command   string  `json:"command"`
	Summary   string  `json:"summary"`
	ExpiresAt float64 `json:"expires_at"`
}

// Result 是一次命令的结果：信封原样带回，再加上退出码和解析出的待确认。
type Result struct {
	OK      bool            `json:"ok"`
	Data    json.RawMessage `json:"data,omitempty"`
	Error   *CliError       `json:"error,omitempty"`
	Pending *Pending        `json:"pending,omitempty"`
	Exit    int             `json:"exit"`
}

// PendingExit 是待确认的退出码（hiro.cli.main.PENDING_EXIT）。
const PendingExit = 3

// Caller 调一条 hiro 命令（Hiro.Call 的形状），测试里换成假的。
type Caller func(ctx context.Context, args []string) Result

// Decode 把成功结果的 data 解到 v；失败时返回信封里的错误。
func (r Result) Decode(v any) error {
	if !r.OK {
		if r.Error != nil {
			return r.Error
		}
		return &CliError{Code: "error", Message: "出错了"}
	}
	if len(r.Data) == 0 {
		return nil
	}
	return json.Unmarshal(r.Data, v)
}

func (e *CliError) Error() string { return e.Message }
