package extplugin

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"github.com/egoist/mygo/ui"

	"github.com/matto49/hiro-gakumas-hero/app/hiroapi"
	"github.com/matto49/hiro-gakumas-hero/app/kit"
	"github.com/matto49/hiro-gakumas-hero/app/plugin"
)

// PluginTrustNote 是「管理插件」页上的说明：说实话，插件不是沙箱。
const PluginTrustNote = "外部插件是一个普通程序，以你本人的权限在这台电脑上运行，能读写你能读写的文件；只装你信得过的人做的插件。" +
	"清单里写的「动游戏」命令要你同意后才能经初星助手发起，每次真动游戏仍会出确认卡，没有「始终允许」。"

// Manager 管 HIRO_HOME/plugins 下装的外部插件：读清单、同意记录（approved.json）、启用 / 卸载、「管理插件」页。
type Manager struct {
	Home string
	Reg  *plugin.Registry

	mu        sync.Mutex
	installed map[string]*Manifest
	broken    map[string]string // 目录名 → 读不了的原因
	approvals map[string]Approval
	exts      map[string]*Ext

	// 「管理插件」页的表单
	src  string
	note string
}

func (m *Manager) dir() string           { return filepath.Join(m.Home, "plugins") }
func (m *Manager) approvalsPath() string { return filepath.Join(m.dir(), "approved.json") }

// Load 读出已装的插件，同意过（且清单没变出同意范围）的注册进注册表。
func (m *Manager) Load() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.installed, m.broken, m.approvals = map[string]*Manifest{}, map[string]string{}, map[string]Approval{}
	if m.exts == nil {
		m.exts = map[string]*Ext{}
	}
	if b, err := os.ReadFile(m.approvalsPath()); err == nil {
		_ = json.Unmarshal(b, &m.approvals)
	}
	entries, _ := os.ReadDir(m.dir())
	for _, en := range entries {
		if !en.IsDir() {
			continue
		}
		man, err := LoadManifest(filepath.Join(m.dir(), en.Name()))
		if err != nil {
			m.broken[en.Name()] = err.Error()
			continue
		}
		m.installed[man.ID] = man
		if ap, ok := m.approvals[man.ID]; ok && ap.Covers(man) {
			m.enableLocked(man, ap)
		}
	}
}

func (m *Manager) enableLocked(man *Manifest, ap Approval) {
	if old := m.exts[man.ID]; old != nil {
		old.Close()
	}
	e := New(man, ap, m.Home)
	m.exts[man.ID] = e
	m.Reg.Add(e.Plugin())
}

func (m *Manager) saveApprovals() error {
	if err := os.MkdirAll(m.dir(), 0o755); err != nil {
		return err
	}
	b, _ := json.MarshalIndent(m.approvals, "", "  ")
	return os.WriteFile(m.approvalsPath(), b, 0o600)
}

// Install 从本机文件夹装一个插件：校验清单、复制到 HIRO_HOME/plugins/<id>（覆盖旧版）。装上后要同意才启用。
func (m *Manager) Install(src string) (*Manifest, error) {
	man, err := LoadManifest(src)
	if err != nil {
		return nil, err
	}
	dst := filepath.Join(m.dir(), man.ID)
	m.mu.Lock()
	if e := m.exts[man.ID]; e != nil {
		e.Close()
		delete(m.exts, man.ID)
		m.Reg.Remove(man.ID)
	}
	m.mu.Unlock()
	if err := os.RemoveAll(dst); err != nil {
		return nil, err
	}
	if err := copyDir(man.Dir, dst); err != nil {
		return nil, fmt.Errorf("复制插件失败：%w", err)
	}
	m.Load()
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.installed[man.ID], nil
}

// copyDir 复制目录（跳过符号链接，免得把目录外的东西带进来）。
func copyDir(src, dst string) error {
	return filepath.WalkDir(src, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, p)
		target := filepath.Join(dst, rel)
		if d.Type()&fs.ModeSymlink != 0 {
			return nil
		}
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		in, err := os.Open(p)
		if err != nil {
			return err
		}
		defer in.Close()
		out, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, info.Mode().Perm())
		if err != nil {
			return err
		}
		if _, err := io.Copy(out, in); err != nil {
			out.Close()
			return err
		}
		return out.Close()
	})
}

// Approve 记下用户同意（按清单现在要的）并启用。
func (m *Manager) Approve(id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	man := m.installed[id]
	if man == nil {
		return fmt.Errorf("没装 %s", id)
	}
	ap := Approval{Version: man.Version, Acts: append([]string{}, man.Acts...), Tools: len(man.Contributes.Tools) > 0, Context: man.Contributes.Context}
	m.approvals[id] = ap
	if err := m.saveApprovals(); err != nil {
		return err
	}
	m.enableLocked(man, ap)
	return nil
}

// Remove 卸载：停掉、从注册表去掉、删目录和同意记录。
func (m *Manager) Remove(id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e := m.exts[id]; e != nil {
		e.Close()
		delete(m.exts, id)
	}
	m.Reg.Remove(id)
	delete(m.approvals, id)
	delete(m.installed, id)
	if err := m.saveApprovals(); err != nil {
		return err
	}
	return os.RemoveAll(filepath.Join(m.dir(), id))
}

// Dir 是已启用插件的目录（网页面板用）；没启用的为 ""。
func (m *Manager) Dir(id string) string {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e := m.exts[id]; e != nil {
		return e.m.Dir
	}
	return ""
}

// Close 关掉所有插件进程。
func (m *Manager) Close() {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, e := range m.exts {
		e.Close()
	}
}

// AgentTool 是一个插件给 agent 的工具。
type AgentTool struct {
	Name   string // 给模型的工具名：plugin_<id>_<name>
	Plugin string
	Tool   Tool
	Run    func(ctx context.Context, h plugin.Host, args map[string]any) hiroapi.Result
}

// AgentTools 是已启用插件给 agent 的全部工具（用户同意过「给 agent 工具」的）。
func (m *Manager) AgentTools() []AgentTool {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []AgentTool
	ids := make([]string, 0, len(m.exts))
	for id := range m.exts {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		e := m.exts[id]
		for _, t := range e.Tools() {
			name := t.Name
			out = append(out, AgentTool{
				Name:   "plugin_" + strings.ReplaceAll(id, "-", "_") + "_" + name,
				Plugin: e.m.Name,
				Tool:   t,
				Run: func(ctx context.Context, h plugin.Host, args map[string]any) hiroapi.Result {
					return e.CallTool(ctx, h, name, args)
				},
			})
		}
	}
	return out
}

// Panel 是「管理插件」页：已装的插件、要的权限、同意 / 卸载；从文件夹安装。
func (m *Manager) Panel(c *ui.Context, h plugin.Host) {
	m.mu.Lock()
	ids := make([]string, 0, len(m.installed))
	for id := range m.installed {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	m.mu.Unlock()
	ui.Text(c, "外部插件").FontSize(15).FontWeight(650).TextColor(kit.Ink)
	kit.Note(c, PluginTrustNote)
	if len(ids) == 0 {
		kit.Note(c, "还没装外部插件。")
	}
	for _, id := range ids {
		m.mu.Lock()
		man := m.installed[id]
		ap, approved := m.approvals[id]
		on := m.exts[id] != nil
		m.mu.Unlock()
		kit.Card(c).Key("ext-" + id).Children(func() {
			ui.Row(c).Gap(8).AlignItems(ui.Center).Children(func() {
				ui.Text(c, man.Name).FontSize(kit.FSmall).FontWeight(600).TextColor(kit.Ink)
				ui.Text(c, man.ID+" "+man.Version).FontSize(11).TextColor(kit.Ink3)
				ui.Spacer(c)
				switch {
				case on:
					kit.Tag(c, "已启用", kit.Good, ui.RGBA(46, 158, 91, 0.12))
				case approved && !ap.Covers(man):
					kit.Tag(c, "要的权限变了", kit.WarnInk, kit.WarnT)
				default:
					kit.Tag(c, "没同意", kit.Ink3, kit.Surface2)
				}
			})
			acts := "不动游戏"
			if len(man.Acts) > 0 {
				acts = strings.Join(man.Acts, "、")
			}
			kit.KV(c, "动游戏", acts)
			if n := len(man.Contributes.Tools); n > 0 {
				kit.KV(c, "工具", fmt.Sprintf("给 agent %d 个工具", n))
			}
			if man.Contributes.Context {
				kit.KV(c, "上下文", "每轮给 agent 一段情况说明")
			}
			ui.Row(c).Gap(8).Children(func() {
				if !on && kit.Primary(c, "同意并启用").Key("approve-"+id).Clicked() {
					if err := m.Approve(id); err != nil {
						m.note = err.Error()
					}
				}
				if kit.Secondary(c, "卸载").Key("remove-" + id).Clicked() {
					if err := m.Remove(id); err != nil {
						m.note = err.Error()
					}
				}
			})
		})
	}
	m.mu.Lock()
	broken := make([]string, 0, len(m.broken))
	for d, e := range m.broken {
		broken = append(broken, d+"："+e)
	}
	m.mu.Unlock()
	for _, b := range broken {
		ui.Text(c, b).FontSize(kit.FNote).TextColor(kit.Bad).Wrap()
	}
	kit.Section(c, "从文件夹安装")
	ui.Row(c).Gap(8).Children(func() {
		ui.TextInput(c, &m.src).Placeholder("插件文件夹的路径（里面有 plugin.json）").FontSize(kit.FSmall).Grow(1)
		if kit.Secondary(c, "安装").Disabled(strings.TrimSpace(m.src) == "").Clicked() {
			if man, err := m.Install(strings.TrimSpace(m.src)); err != nil {
				m.note = err.Error()
			} else {
				m.note = "装好了「" + man.Name + "」，看一下它要的权限，同意后启用。"
				m.src = ""
			}
		}
	})
	if m.note != "" {
		kit.Note(c, m.note)
	}
}
