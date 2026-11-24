package shell

import "github.com/egoist/mygo/ui"

// MinChatWidth 是中间对话最少留多宽（§4）。
const MinChatWidth float32 = 400

// ClosePanel 关掉侧边面板。
func (a *App) ClosePanel() { a.ui.panelOpen = false }

// pinned 是钉在对话顶上的东西（对局卡，见 job.go）。
func (a *App) pinned(c *ui.Context) {}

func (a *App) jobLive() bool { return false }

// onJobStarted 在确认开局后被调用（见 job.go）。
func (a *App) onJobStarted(card map[string]any) {}
