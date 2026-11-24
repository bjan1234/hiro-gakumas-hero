package shell

import (
	"github.com/egoist/mygo/ui"
	"github.com/egoist/mygo/ui/markdown"

	"github.com/matto49/hiro-gakumas-hero/app/kit"
)

// viewState 是界面上的临时状态（不存盘）。
type viewState struct {
	panelOpen   bool
	panelPlugin string
	panelRoute  string
	panelFrac   float32 // 面板占窗口宽的比例，0 = 默认 45%
	list        ui.ListState
	md          markdown.Options
}

// SidebarWidth 是左侧栏宽度（§4）。
const SidebarWidth float32 = 232

// View 是整个窗口。
func (a *App) View(c *ui.Context) {
	t := kit.Theme(*c.Theme())
	c.SetTheme(&t)
	if c.Shortcut(ui.Cmd, ui.KeyN) {
		a.NewThread()
	}
	ui.Row(c).Fill().Background(kit.Bg).AlignItems(ui.Stretch).Children(func() {
		a.sidebar(c)
		ui.Column(c).Grow(1).MinWidth(MinChatWidth).FillHeight().Children(func() {
			a.header(c)
			a.transcript(c)
			a.composer(c)
		})
	})
}

func (a *App) header(c *ui.Context) {
	title := "新对话"
	if a.cur != nil {
		title = a.cur.Title
	}
	ui.Row(c).Height(48).Shrink(0).AlignItems(ui.Center).Padding(0, 20).Gap(10).BorderColor(kit.Line).BorderWidth(0, 0, kit.Hair, 0).Children(func() {
		ui.Text(c, title).FontSize(13.5).FontWeight(600).TextColor(kit.Ink).MaxLines(1).Ellipsis("…")
		ui.Spacer(c)
	})
}
