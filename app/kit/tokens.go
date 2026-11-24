// Package kit 是初星助手原生界面的设计 token 和公用件（设计稿 §4，画板 A「安静工具」）。
package kit

import "github.com/egoist/mygo/ui"

// 颜色（§4 的表）。
var (
	Bg       = ui.Hex("#FFFFFF") // 主区底、卡片底
	Side     = ui.Hex("#F7F7F5") // 侧栏、侧边面板底
	Surface2 = ui.Hex("#F4F4F2") // 用户气泡、代码块、选中行
	Line     = ui.Hex("#E7E7E4")
	LineStr  = ui.Hex("#D4D4D0")
	Ink      = ui.Hex("#18181B")
	Ink2     = ui.Hex("#55555C")
	Ink3     = ui.Hex("#8C8C93")
	Primary_ = ui.Hex("#18181B") // 主按钮底
	OnPrim   = ui.Hex("#FFFFFF")
	Brand    = ui.Hex("#EE6A1F") // 运行中、「现在」、算法
	BrandT   = ui.Hex("#FFF1E8")
	Warn     = ui.Hex("#E0A040") // 确认卡描边
	WarnT    = ui.Hex("#FFF8EB")
	WarnInk  = ui.Hex("#8A5A12")
	Good     = ui.Hex("#2E9E5B")
	Bad      = ui.Hex("#D23B3B")
	BadT     = ui.Hex("#FDECEC")
	Blue     = ui.Hex("#3C82F0")
	BlueT    = ui.RGBA(60, 130, 240, 0.12)
	Vo       = ui.Hex("#F0508C")
	Da       = ui.Hex("#3C82F0")
	Vi       = ui.Hex("#E8B400")
)

// 圆角。
const (
	R8  float32 = 8
	R12 float32 = 12
	R16 float32 = 16
	R20 float32 = 20
)

// 字号。
const (
	FBody  float32 = 14
	FSmall float32 = 13
	FNote  float32 = 12
	FTag   float32 = 11
)

// Hair 是 0.5 px 的线宽。
const Hair float32 = 0.5

// Mono 是等宽字体族（系统等宽）。
const Mono = "monospace"

// Theme 把 mygo 的主题换成初星助手的颜色（控件默认色跟着走）。
func Theme(t ui.Theme) ui.Theme {
	t.Background, t.Surface, t.Border = Bg, Surface2, Line
	t.SurfaceHover, t.SurfacePressed = ui.Hex("#EDEDEA"), ui.Hex("#E4E4E0")
	t.Text, t.TextMuted = Ink, Ink3
	t.Accent, t.AccentHover, t.AccentPressed, t.AccentText = Ink, ui.Hex("#2C2C31"), ui.Hex("#000000"), OnPrim
	t.Selection = ui.RGBA(238, 106, 31, 0.22)
	t.Danger, t.Warning, t.Success = Bad, Warn, Good
	return t
}
