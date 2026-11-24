// Package plugin 是初星助手的插件接口（设计稿 §5）：内置插件和外部插件都包成 Plugin，宿主只认它。
package plugin

import (
	"context"
	"time"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/hiroapi"
)

// Card 是对话里的一张卡片（存进 threads/<id>.json，形状和旧版 src/lib/chat.ts 一致）。
type Card = map[string]any

// Host 是插件能碰的全部宿主能力。插件拿不到 Hiro 本身、Bootstrap、Key 存储。
type Host interface {
	// Call 调工具层命令（同步，别在界面线程的 view 里直接调，用 Go）。
	Call(ctx context.Context, args []string) hiroapi.Result
	// Go 在后台跑 work；work 返回的函数回到界面线程执行（可以是 nil）。
	Go(work func() func())
	// Ask 以用户身份往当前对话发一句话。
	Ask(text string)
	// Post 往当前对话加一张卡（以初星助手的身份）。
	Post(text string, card Card)
	// OpenPanel 在右侧边面板打开某插件的某页。
	OpenPanel(pluginID, route string)
	// Home 是 HIRO_HOME（读本机图片用）。
	Home() string
	// Now 是现在（测试可换）。
	Now() time.Time
}

// Command 是输入框里的 "/" 命令。Run 为空时打开插件面板的 Route。
type Command struct {
	Name  string
	Hint  string
	Route string
	Run   func(h Host)
}

// Chip 是输入框上面的快捷按钮：Say 是代用户说的话；Run 非空时直接执行（不经模型）。
type Chip struct {
	Label string
	Say   string
	Run   func(h Host)
}

// NavItem 是侧栏插件列表里的一项（打开面板的 Route）。
type NavItem struct {
	Label string
	Icon  *ui.SVG
	Route string
}

// CardView 画一张卡。
type CardView func(c *ui.Context, h Host, card Card)

// Explained 是确认卡的解读：几行「键 值」和代价（「会操作游戏 · 用掉 1 次培育」）。
type Explained struct {
	Title string
	Rows  [][2]string
	Cost  string
}

// Plugin 是一个插件给的全部东西（§5.1 的七类），哪项没有就留空。
type Plugin struct {
	ID   string
	Name string
	Icon *ui.SVG
	// Nav 是侧栏里的入口；空的话用 Name / Icon 打开面板首页（有 Panel 时）。
	Nav []NavItem
	// Tools 是认领的工具层命令名（ToolSpec.Name，如 "run start"）。
	Tools    []string
	Commands []Command
	Chips    []Chip
	Cards    map[string]CardView
	// Panel 画侧边面板的一页；route 是插件自己的子页（"" 为首页）。
	Panel    func(c *ui.Context, h Host, route string)
	Settings func(c *ui.Context, h Host)
	// Context 是给 agent 的「现在的情况」里的一段；ContextTitle 是小标题（空则用 Name）。
	Context      func(ctx context.Context, h Host) string
	ContextTitle string
	// Explain 解读一条待确认；认不出返回 ok=false。
	Explain func(h Host, p hiroapi.Pending) (Explained, bool)
}

// Navs 是插件在侧栏里的入口。
func (p *Plugin) Navs() []NavItem {
	if len(p.Nav) > 0 {
		return p.Nav
	}
	if p.Panel == nil {
		return nil
	}
	return []NavItem{{Label: p.Name, Icon: p.Icon}}
}
