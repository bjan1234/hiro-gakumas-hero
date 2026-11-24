package main

import (
	"context"
	"encoding/json"
	"errors"
	"os/exec"
	"strings"
	"sync"

	"github.com/matto49/hiro-gakumas-hero/app/extplugin"
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
	// Web 是侧边面板的网页视图（nil：测试里不接）。
	Web *webPanels
}

// buildApp 注册内置插件，搭出主界面。
func buildApp(d appDeps) *shell.App {
	reg := &plugin.Registry{}
	mgr := &extplugin.Manager{Home: d.Home, Reg: reg, IsRead: readOnly(d.Call)}
	sd := settingsDeps(d)
	sd.PluginsPanel = mgr.Panel
	set := settings.New(sd)
	reg.Add(start.New())
	reg.Add(plan.New())
	reg.Add(library.New())
	reg.Add(cockpit.New())
	reg.Add(set.Plugin())
	mgr.Load() // 同意过的外部插件排在内置插件后面
	plugins = mgr
	if d.Web != nil {
		d.Web.hook(mgr.Dir)
	}
	a := d.Assistant
	var app *shell.App
	a.ExtTools = func() []ExtTool {
		var out []ExtTool
		for _, t := range mgr.AgentTools() {
			spec := ToolSpec{Name: t.Name, ToolName: t.Name, Risk: "read", Help: "（插件「" + t.Plugin + "」）" + t.Tool.Help, Agent: true}
			for _, arg := range t.Tool.Args {
				spec.Args = append(spec.Args, ToolArg{Name: arg.Name, Help: arg.Help, Type: arg.Type, Required: arg.Required, Choices: arg.Choices})
			}
			run := t.Run
			out = append(out, ExtTool{Spec: spec, Run: func(ctx context.Context, args map[string]any) Result { return run(ctx, app, args) }})
		}
		return out
	}
	app = shell.New(shell.Deps{
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
	return app
}

// readOnly 是「这条工具层命令只读吗」：按 hiro tools 的风险等级（第一次用时读一次）。外部插件调只读命令不用写进 acts。
func readOnly(call hiroapi.Caller) func(args []string) bool {
	var (
		once sync.Once
		risk map[string]string
	)
	return func(args []string) bool {
		once.Do(func() {
			risk = map[string]string{}
			var d struct {
				Tools []ToolSpec `json:"tools"`
			}
			if call(context.Background(), []string{"tools"}).Decode(&d) == nil {
				for _, t := range d.Tools {
					risk[t.Name] = t.Risk
				}
			}
		})
		for n := min(len(args), 3); n > 0; n-- {
			if r, ok := risk[strings.Join(args[:n], " ")]; ok {
				return r == "read" && !strings.HasPrefix(args[0], "secret") && args[0] != "confirm" && args[0] != "cancel"
			}
		}
		return false
	}
}

// plugins 是外部插件管理（hiroplug:// 协议找插件目录用）。
var plugins *extplugin.Manager

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
