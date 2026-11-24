package main

import (
	"context"
	"encoding/json"
	"errors"
	"os/exec"

	"github.com/matto49/hiro-gakumas-hero/app/hiroapi"
	"github.com/matto49/hiro-gakumas-hero/app/plugin"
	"github.com/matto49/hiro-gakumas-hero/app/plugins/cockpit"
	"github.com/matto49/hiro-gakumas-hero/app/plugins/library"
	"github.com/matto49/hiro-gakumas-hero/app/plugins/plan"
	"github.com/matto49/hiro-gakumas-hero/app/plugins/settings"
	"github.com/matto49/hiro-gakumas-hero/app/plugins/start"
	"github.com/matto49/hiro-gakumas-hero/app/shell"
)

// appDeps 是搭原生界面要的东西；测试里换掉 Call / Run / Ready。
type appDeps struct {
	Home      string
	Call      hiroapi.Caller
	Hiro      *Hiro
	Assistant *Assistant
	Bootstrap *Bootstrap
	Run       shell.Runner
	// Ready 盖掉 Bootstrap 的「环境装好没」（测试用）；nil 时用 Bootstrap.Status。
	Ready func(ctx context.Context) bool
}

// buildApp 注册内置插件，搭出主界面。
func buildApp(d appDeps) *shell.App {
	reg := &plugin.Registry{}
	set := settings.New(settingsDeps(d))
	reg.Add(start.New())
	reg.Add(plan.New())
	reg.Add(library.New())
	reg.Add(cockpit.New())
	reg.Add(set.Plugin())
	a := d.Assistant
	return shell.New(shell.Deps{
		Call:    d.Call,
		Threads: &Threads{Home: d.Home},
		Run:     d.Run,
		Home:    d.Home,
		Ask: func(ctx context.Context, history []shell.Turn, text, extra string, onTool func(string, string)) (shell.Reply, error) {
			h := make([]Turn, len(history))
			for i, t := range history {
				h[i] = Turn{Role: t.Role, Content: t.Content}
			}
			r, err := a.AskWith(ctx, h, text, extra, onTool)
			cards := make([]plugin.Card, len(r.Cards))
			for i, c := range r.Cards {
				cards[i] = c
			}
			return shell.Reply{Text: r.Text, Cards: cards}, err
		},
		HasModel: func() bool { return hasModel(a.Settings()) },
		Gate:     set.Gate,
	}, reg)
}

// hasModel 是现在能不能直接和 agent 说话。
func hasModel(s Settings) bool {
	switch s.Provider {
	case "none":
		return false
	case "codex", "claude":
		_, err := exec.LookPath(s.Provider)
		return err == nil
	}
	return s.HasKey
}

func convert(from, to any) {
	b, _ := json.Marshal(from)
	_ = json.Unmarshal(b, to)
}

func settingsDeps(d appDeps) settings.Deps {
	a, boot := d.Assistant, d.Bootstrap
	return settings.Deps{
		Settings: func() settings.Settings {
			var s settings.Settings
			convert(a.Settings(), &s)
			return s
		},
		Save: func(s settings.Settings, key string) error {
			var m Settings
			convert(s, &m)
			return a.Save(m, key)
		},
		Providers: func() []settings.Preset {
			out := make([]settings.Preset, len(Presets))
			for i, p := range Presets {
				out[i] = settings.Preset{ID: p.ID, BaseURL: p.BaseURL, DefaultModel: p.DefaultModel, KeyURL: p.KeyURL}
			}
			return out
		},
		Models: a.Models,
		Test: func(ctx context.Context) (bool, string) {
			r := a.Test(ctx)
			return r.OK, r.Message
		},
		BootStatus: func(ctx context.Context) settings.BootStatus {
			st := boot.Status(ctx)
			out := settings.BootStatus{Ready: st.Ready}
			if d.Ready != nil {
				out.Ready = d.Ready(ctx)
			}
			for _, s := range st.Steps {
				out.Steps = append(out.Steps, s.Title)
			}
			if st.Error != nil {
				out.Err = st.Error.Message + "。" + st.Error.Hint
			}
			return out
		},
		BootRun: func(ctx context.Context, onLine func(string)) error {
			return boot.RunLines(ctx, func(p Progress) { onLine(p.Line) })
		},
		BootReset: boot.Reset,
		SetSecret: func(ctx context.Context, name, value string) hiroapi.Result {
			if d.Hiro == nil {
				return hiroapi.Result{Error: &hiroapi.CliError{Code: "error", Message: errors.New("工具层不可用").Error()}}
			}
			return d.Hiro.SetSecret(ctx, name, value)
		},
	}
}
