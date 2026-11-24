package plugin

// Job 是 `hiro run status` 里的一个任务。
type Job struct {
	ID        string         `json:"id"`
	Kind      string         `json:"kind"`
	Params    map[string]any `json:"params"`
	State     string         `json:"state"`
	Summary   string         `json:"summary"`
	StartedAt float64        `json:"started_at"`
	EndedAt   *float64       `json:"ended_at"`
	ExitCode  *int           `json:"exit_code"`
	Pausable  *bool          `json:"pausable,omitempty"`
}

// JobEvent 是 `hiro run events` 的一条事件。
type JobEvent struct {
	Seq    int      `json:"seq"`
	T      float64  `json:"t"`
	Type   string   `json:"type"`
	Text   string   `json:"text"`
	Step   *int     `json:"step,omitempty"`
	Page   string   `json:"page,omitempty"`
	Action string   `json:"action,omitempty"`
	Source string   `json:"source,omitempty"`
	Frame  string   `json:"frame,omitempty"`
	Notes  []string `json:"notes,omitempty"`
}

// LiveStates 是还活着的任务状态。
var LiveStates = map[string]bool{"running": true, "paused": true, "takeover": true, "stopping": true}

// JobView 是宿主盯着的一个任务：基本信息 + 到目前为止的事件。
type JobView struct {
	Job    *Job
	State  string
	Events []JobEvent
	// Next 是下次 run events 的 --since。
	Next int
}

// Live 是任务还在跑。
func (v *JobView) Live() bool { return v != nil && LiveStates[v.State] }

// Steps 是事件里的步骤（type=step）。
func (v *JobView) Steps() []JobEvent {
	var out []JobEvent
	for _, e := range v.Events {
		if e.Type == "step" {
			out = append(out, e)
		}
	}
	return out
}

// LastFrame 是最近一张画面（步骤或 frame 事件带的截图路径）。
func (v *JobView) LastFrame() string {
	for i := len(v.Events) - 1; i >= 0; i-- {
		if f := v.Events[i].Frame; f != "" {
			return f
		}
	}
	return ""
}
