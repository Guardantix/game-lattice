"""Tests for discovery."""

from pathlib import Path

import pytest

from game_lattice.discovery import discover_doc_paths, read_doc
from game_lattice.error_types import UnreadableDocError


def test_discovers_markdown_sorted(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "b.md").write_text("b", encoding="utf-8")
    (root / "a.md").write_text("a", encoding="utf-8")
    (root / "note.txt").write_text("x", encoding="utf-8")
    found = discover_doc_paths([root], [])
    assert [p.name for p in found] == ["a.md", "b.md"]


def test_ignore_globs_exclude(tmp_path: Path):
    root = tmp_path / "docs"
    (root / "archive").mkdir(parents=True)
    (root / "keep.md").write_text("k", encoding="utf-8")
    (root / "archive" / "old.md").write_text("o", encoding="utf-8")
    found = discover_doc_paths([root], ["**/archive/**"])
    assert [p.name for p in found] == ["keep.md"]


def test_read_doc_returns_text(tmp_path: Path):
    p = tmp_path / "a.md"
    p.write_text("hello", encoding="utf-8")
    assert read_doc(p) == "hello"


def test_read_doc_non_utf8_raises(tmp_path: Path):
    p = tmp_path / "a.md"
    p.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(UnreadableDocError):
        read_doc(p)
