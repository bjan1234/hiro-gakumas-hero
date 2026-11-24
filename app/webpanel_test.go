package main

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestPluginFilesServeInsideDirWithCSP(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "report.html"), []byte("<p>hi</p>"), 0o644); err != nil {
		t.Fatal(err)
	}
	h := pluginFiles(func(id string) string {
		if id == "demo" {
			return dir
		}
		return ""
	})
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "hiroplug://localhost/demo/report.html", nil))
	if rec.Code != 200 || rec.Body.String() != "<p>hi</p>" {
		t.Fatalf("插件页：%d %q", rec.Code, rec.Body.String())
	}
	if csp := rec.Header().Get("Content-Security-Policy"); csp != PluginCSP {
		t.Errorf("CSP %q", csp)
	}
	for _, p := range []string{"/demo/../../etc/passwd", "/other/report.html", "/demo/missing.html", "/demo/%2e%2e/x"} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("GET", "hiroplug://localhost"+p, nil))
		if rec.Code != 404 {
			t.Errorf("%s 应 404，得到 %d", p, rec.Code)
		}
	}
}

func TestWebURL(t *testing.T) {
	if got := webURL("hiro", "review/j7.html", "darwin"); got != "hiro://localhost/review/j7.html" {
		t.Errorf("mac：%q", got)
	}
	if got := webURL("hiroplug", "demo/report.html", "windows"); got != "http://hiroplug.localhost/demo/report.html" {
		t.Errorf("windows：%q", got)
	}
}

func TestPluginFileURLFindsPluginDir(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "plugins", "demo")
	dirOf := func(id string) string {
		if id == "demo" {
			return dir
		}
		return ""
	}
	got := pluginFileURL(dirOf, filepath.Join(dir, "web", "report.html"))
	if got != webURL("hiroplug", "demo/web/report.html", runtimeGOOS()) {
		t.Errorf("地址 %q", got)
	}
	if pluginFileURL(dirOf, "/etc/passwd") != "" {
		t.Error("插件目录外的文件不给地址")
	}
}
