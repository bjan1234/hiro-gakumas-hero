"""初 / N.I.A 社区规则文件：结构完整、出处都登记了、摘录能在原文里找到（本机有原文时才核）。"""

from pathlib import Path

import pytest

from hiro.brain import hajime_nia_rules as hr

SOURCES_DIR = Path.home() / "github/digital-hiro/.temp/plans-20261112/hajime-nia-sources"


def test_rules_well_formed():
    doc = hr.load()
    ids = [r["id"] for r in doc["rules"]]
    assert len(ids) == len(set(ids))
    for r in doc["rules"]:
        assert r["source"] in doc["sources"], r["id"]
        assert r["quote"] and r["rule"], r["id"]
        assert set(r["families"]) <= {"hajime", "nia"} and r["id"].split(".")[0] in r["families"]
        assert r["difficulties"] is None or set(r["difficulties"]) <= {"regular", "pro", "master", "legend"}


def test_cite_and_applies():
    assert hr.cite("nia.lesson_sp").endswith("[g8-NIA]")
    assert hr.applies("nia.outing_order", "nia", "master") and not hr.applies("nia.outing_order", "nia", "pro")
    assert not hr.applies("nia.lesson_sp", "hajime", "pro")


@pytest.mark.skipif(not SOURCES_DIR.is_dir(), reason="本机没有攻略原文目录")
def test_quotes_found_in_saved_pages():
    texts = {p.name: p.read_text(encoding="utf-8") for p in SOURCES_DIR.glob("*.txt")}
    by_url = {t.split("\n", 1)[0].strip(): t for t in texts.values()}
    for r in hr.load()["rules"]:
        url = hr.load()["sources"][r["source"]]["url"]
        assert url in by_url, f"{r['source']} 原文没存：{url}"
        assert r["quote"] in by_url[url], r["id"]
