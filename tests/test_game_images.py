"""去 KAA 第 4 批：识别要用的原图（技能卡 skill_cards、偶像卡 idol_cards、饮料 drinks）不再经 KAA 的更新器下载，
由 tools/assets/game_images.py 直接从 kaa-game-data 的固定 Release（data-<gakumasu-diff 提交>）取，校验 SHA256 后解压。"""

import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.synthetic, pytest.mark.play_free]

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("game_images", ROOT / "tools/assets/game_images.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _zip(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, b"png:" + n.encode())
    return buf.getvalue()


def test_pinned_release_and_categories():
    tool = _tool()
    assert tool.TAG.startswith("data-") and set(tool.FILES) == {"skill_cards", "idol_cards", "drinks"}
    assert all(len(sha) == 64 for sha in tool.FILES.values())
    assert tool.url("drinks").startswith("https://github.com/kotonebot/kaa-game-data/releases/download/data-")


def test_fetch_extracts_checks_sha_and_skips_when_current(tmp_path, monkeypatch):
    tool = _tool()
    blobs = {c: _zip([f"{c}_a.png", f"{c}_b.png"]) for c in tool.FILES}
    monkeypatch.setattr(tool, "FILES", {c: hashlib.sha256(b).hexdigest() for c, b in blobs.items()})
    calls = []

    def urlopen(url, timeout=0):
        calls.append(url)
        return io.BytesIO(blobs[url.rsplit("/", 1)[-1].removesuffix(".zip")])

    monkeypatch.setattr(tool.urllib.request, "urlopen", urlopen)
    assert sorted(tool.fetch(tmp_path)) == sorted(tool.FILES)
    assert (tmp_path / "drinks" / "drinks_a.png").read_bytes() == b"png:drinks_a.png"
    assert (tmp_path / "images-version.txt").read_text().strip() == tool.TAG
    n = len(calls)
    assert tool.fetch(tmp_path) == [] and len(calls) == n  # 版本对、目录都在：不重复下载

    (tmp_path / "images-version.txt").unlink()
    monkeypatch.setattr(tool.urllib.request, "urlopen", lambda url, timeout=0: io.BytesIO(b"tampered"))
    with pytest.raises(SystemExit, match="校验不对"):
        tool.fetch(tmp_path)
    assert (tmp_path / "drinks" / "drinks_a.png").exists()  # 校验不对时不动已有的图
