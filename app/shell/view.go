package shell

// viewState 是界面上的临时状态（不存盘）。
type viewState struct {
	panelOpen   bool
	panelPlugin string
	panelRoute  string
}
