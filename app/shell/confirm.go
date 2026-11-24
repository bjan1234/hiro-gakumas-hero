package shell

import (
	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/hiroapi"
	"github.com/matto49/hiro-gakumas-hero/app/kit"
	"github.com/matto49/hiro-gakumas-hero/app/plugin"
)

// 确认卡（§6.2，方向 B）：等待中的卡画在对话里；点「开始」才 confirm，「先不」cancel。
// 确认只能从这里发起：agent 和插件都没有调 confirm 的路径。

func pendingOf(card plugin.Card) (hiroapi.Pending, bool) {
	m, _ := card["pending"].(map[string]any)
	if m == nil {
		return hiroapi.Pending{}, false
	}
	p := hiroapi.Pending{}
	p.ID, _ = m["id"].(string)
	p.Command, _ = m["command"].(string)
	p.Summary, _ = m["summary"].(string)
	switch v := m["expires_at"].(type) {
	case float64:
		p.ExpiresAt = v
	case int:
		p.ExpiresAt = float64(v)
	case int64:
		p.ExpiresAt = float64(v)
	}
	return p, p.ID != ""
}

// waiting 是这张卡是不是还在等确认（没点过、没过期）。
func (a *App) waiting(card plugin.Card) bool {
	if t, _ := card["type"].(string); t != "confirm" {
		return false
	}
	if s, _ := card["status"].(string); s != "waiting" {
		return false
	}
	p, ok := pendingOf(card)
	if !ok {
		return false
	}
	if p.ExpiresAt > 0 && float64(a.d.Now().Unix()) >= p.ExpiresAt {
		return false
	}
	return true
}

// latestWaiting 是当前对话里最新一张在等的确认卡和它所在的消息。
func (a *App) latestWaiting() (*Message, plugin.Card) {
	if a.cur == nil {
		return nil, nil
	}
	for i := len(a.cur.Messages) - 1; i >= 0; i-- {
		m := a.cur.Messages[i]
		for j := len(m.Cards) - 1; j >= 0; j-- {
			if a.waiting(m.Cards[j]) {
				return m, m.Cards[j]
			}
		}
	}
	return nil, nil
}

// resolve 执行「开始」或「先不」。同一张卡只会发一次。
func (a *App) resolve(m *Message, card plugin.Card, action string) {
	p, ok := pendingOf(card)
	if !ok || !a.waiting(card) {
		return
	}
	if a.ui.resolving == nil {
		a.ui.resolving = map[string]bool{}
	}
	if a.ui.resolving[p.ID] {
		return
	}
	a.ui.resolving[p.ID] = true
	t, call := a.cur, a.d.Call
	a.d.Run.Go(func() func() {
		r := call(a.ctx, []string{action, p.ID})
		return func() {
			delete(a.ui.resolving, p.ID)
			switch {
			case !r.OK:
				card["status"] = "failed"
				if r.Error != nil {
					card["message"] = r.Error.Message
				}
			case action == "cancel":
				card["status"] = "cancelled"
			default:
				card["status"] = "confirmed"
				for _, c := range CardsFor(r) {
					if c["type"] == "run" {
						m.Cards = append(m.Cards, c)
						a.onJobStarted(c)
					}
				}
			}
			a.save(t)
		}
	})
}

// keyOnEmptyInput 处理输入框空时的 Enter / Esc：作用于最新等待的确认卡。返回是否用掉了这个键。
func (a *App) keyOnEmptyInput(key ui.Key) bool {
	m, card := a.latestWaiting()
	if card == nil {
		return false
	}
	switch key {
	case ui.KeyEnter:
		a.resolve(m, card, "confirm")
		return true
	case ui.KeyEscape:
		a.resolve(m, card, "cancel")
		return true
	}
	return false
}

func (a *App) confirmCard(c *ui.Context, m *Message, card plugin.Card) {
	p, _ := pendingOf(card)
	e, ok := a.reg.Explain(a, p)
	if !ok {
		e = plugin.Explained{Title: p.Summary, Rows: [][2]string{{"命令", p.Command}}, Cost: "会操作游戏"}
	}
	busy := a.ui.resolving[p.ID]
	ui.Column(c).MaxWidth(560).Radius(kit.R20).Background(kit.CardBg).Border(1, kit.Warn).Clip().
		Shadow(0, 8, 28, 0, ui.RGBA(120, 60, 10, 0.08)).Children(func() {
		ui.Row(c).Gap(14).Padding(16).AlignItems(ui.Center).Gradient(kit.ConfirmHeadFrom, kit.ConfirmHeadTo, 90).Children(func() {
			if e.Art != "" {
				kit.Thumb(c, e.Art, 72, 72, 14)
			}
			ui.Column(c).Gap(4).Shrink(1).Children(func() {
				ui.Text(c, e.Title).FontSize(17).FontWeight(700).TextColor(kit.Ink).Wrap()
				if e.Subtitle != "" {
					ui.Text(c, e.Subtitle).FontSize(12.5).TextColor(kit.Ink2).Wrap()
				}
				ui.Row(c).Gap(6).Padding(4, 0, 0, 0).AlignItems(ui.Center).Children(func() {
					kit.AttrTag(c, e.Attr)
					ui.Text(c, "等你确认").FontSize(11.5).FontWeight(600).TextColor(kit.WarnInk).Padding(3, 8).Radius(99).Background(kit.WarnT)
				})
			})
		})
		ui.Column(c).Gap(8).Padding(14).Children(func() {
			for _, r := range e.Rows {
				kit.KV(c, r[0], r[1])
			}
			if len(e.Thumbs) > 0 {
				ui.Row(c).Gap(6).Padding(2, 0, 2, 56).Children(func() {
					for _, th := range e.Thumbs {
						kit.Thumb(c, th, 34, 34, 7)
					}
				})
			}
			ui.Box(c).Height(4)
			ui.Row(c).Gap(8).AlignItems(ui.Center).Children(func() {
				ui.Text(c, e.Cost).FontSize(kit.FNote).TextColor(kit.Ink3).Shrink(1)
				ui.Spacer(c)
				if kit.Secondary(c, "先不").Key("cancel-" + p.ID).Disabled(busy).Clicked() {
					a.resolve(m, card, "cancel")
				}
				ui.Text(c, "Esc").FontSize(10.5).TextColor(kit.Ink3)
				if kit.Primary(c, "开始").Key("confirm-" + p.ID).Disabled(busy).Clicked() {
					a.resolve(m, card, "confirm")
				}
				ui.Text(c, "↵").FontSize(12).TextColor(kit.Ink3)
			})
		})
	})
}
