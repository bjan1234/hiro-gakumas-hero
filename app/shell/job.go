package shell

import (
	"strconv"
	"time"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/kit"
	"github.com/matto49/hiro-gakumas-hero/app/labels"
	"github.com/matto49/hiro-gakumas-hero/app/plugin"
)

// 任务轮询（§6.3）：每秒 run status + 活着的 / 被看的任务 run events --since；窗口隐藏时 5 秒；任务结束就不再读事件。

// Job 是盯着的某个任务（第一次问就开始盯）。
func (a *App) Job(id string) *plugin.JobView {
	if id == "" {
		return nil
	}
	if a.jobs == nil {
		a.jobs = map[string]*plugin.JobView{}
	}
	v, ok := a.jobs[id]
	if !ok {
		v = &plugin.JobView{}
		a.jobs[id] = v
	}
	return v
}

// LiveJob 是现在活着的任务编号。
func (a *App) LiveJob() string { return a.live }

func (a *App) jobLive() bool { return a.live != "" }

type statusData struct {
	Current *plugin.Job  `json:"current"`
	Recent  []plugin.Job `json:"recent"`
}

type eventsData struct {
	State  string            `json:"state"`
	Events []plugin.JobEvent `json:"events"`
}

// PollJobs 读一轮任务状态（后台读，回界面线程改）。上一轮没回来时不重叠。
func (a *App) PollJobs() {
	if a.polling {
		return
	}
	a.polling = true
	// 要读事件的：活着的那个 + 被看但还没读过或还活着的
	type want struct {
		id   string
		next int
	}
	var wants []want
	for id, v := range a.jobs {
		if v.Job == nil || len(v.Events) == 0 || v.Live() || id == a.live {
			wants = append(wants, want{id, v.Next})
		}
	}
	call := a.d.Call
	a.d.Run.Go(func() func() {
		var st statusData
		_ = call(a.ctx, []string{"run", "status"}).Decode(&st)
		got := map[string]eventsData{}
		seen := map[string]bool{}
		read := func(id string, next int) {
			if seen[id] {
				return
			}
			seen[id] = true
			var ev eventsData
			if call(a.ctx, []string{"run", "events", "--job", id, "--since", strconv.Itoa(next)}).Decode(&ev) == nil {
				got[id] = ev
			}
		}
		for _, w := range wants {
			read(w.id, w.next)
		}
		if st.Current != nil && plugin.LiveStates[st.Current.State] {
			next := 0
			for _, w := range wants {
				if w.id == st.Current.ID {
					next = w.next
				}
			}
			read(st.Current.ID, next)
		}
		return func() {
			a.polling = false
			a.live = ""
			jobs := append([]plugin.Job{}, st.Recent...)
			if st.Current != nil {
				jobs = append(jobs, *st.Current)
				if plugin.LiveStates[st.Current.State] {
					a.live = st.Current.ID
				}
			}
			for i := range jobs {
				j := jobs[i]
				if v, ok := a.jobs[j.ID]; ok || j.ID == a.live {
					if !ok {
						v = a.Job(j.ID)
					}
					v.Job = &j
					if v.State == "" || j.State != "" {
						v.State = j.State
					}
				}
			}
			for id, ev := range got {
				v := a.Job(id)
				last := -1
				if n := len(v.Events); n > 0 {
					last = v.Events[n-1].Seq
				}
				for _, e := range ev.Events {
					if e.Seq > last {
						v.Events = append(v.Events, e)
						last = e.Seq
					}
				}
				v.Next = last + 1
				if ev.State != "" {
					v.State = ev.State
				}
			}
		}
	})
}

// StartPolling 在后台一直轮询，直到 stop 关上。
func (a *App) StartPolling(stop <-chan struct{}) {
	go func() {
		for {
			a.d.Run.Post(a.PollJobs)
			d := time.Second
			if a.hidden.Load() {
				d = 5 * time.Second
			}
			select {
			case <-stop:
				return
			case <-time.After(d):
			}
		}
	}()
}

// onJobStarted 在确认开局后被调用：开始盯这局，第一次自动打开游戏运行现状。
func (a *App) onJobStarted(card map[string]any) {
	id, _ := card["jobId"].(string)
	if id == "" {
		return
	}
	a.Job(id)
	if a.ui.autoOpened == nil {
		a.ui.autoOpened = map[string]bool{}
	}
	if a.ui.autoOpened[id] {
		return
	}
	a.ui.autoOpened[id] = true
	if a.reg.ByID("cockpit") != nil {
		a.OpenPanel("cockpit", "")
	}
}

// pinned 是钉在对话顶上的对局卡（有活着的任务时，每个对话都有）。
func (a *App) pinned(c *ui.Context) {
	if a.live == "" {
		return
	}
	card := plugin.Card{"type": "run-pinned", "jobId": a.live}
	ui.Column(c).Shrink(0).Padding(14, a.chatPad(), 0, a.chatPad()).Children(func() {
		if _, v := a.reg.CardView("run-pinned"); v != nil {
			v(c, a, card)
			return
		}
		v := a.Job(a.live)
		title := a.live
		if v.Job != nil {
			title = v.Job.Summary
			if title == "" {
				title = labels.Kind(v.Job.Kind)
			}
		}
		if kit.RowButton(c, "pinned-"+a.live, title, false).Padding(10, 12).Radius(kit.R16-2).Background(kit.CardBg).Border(kit.Hair, kit.LineStr).Children(func() {
			ui.Box(c).Size(7, 7).Radius(4).Background(kit.Brand)
			ui.Text(c, title).FontSize(kit.FSmall).FontWeight(600).TextColor(kit.Ink)
			ui.Text(c, labels.State(v.State)).FontSize(kit.FNote).TextColor(kit.Ink3)
		}).Clicked() {
			a.OpenPanel("cockpit", "")
		}
	})
}

