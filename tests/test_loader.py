"""Tests for build_lattice."""

from pathlib import Path

import pytest

from game_lattice.error_types import DuplicateIdError
from game_lattice.loader import build_lattice
from game_lattice.model import NodeMeta, ParsedDoc, RawEdge


def _doc(path: str, body: str, **meta) -> ParsedDoc:
    return ParsedDoc(path=Path(path), meta=NodeMeta(**meta), body=body)


def test_registers_file_and_anchor_ids():
    docs = [_doc("a.md", "# A {#sec}\nbody\n", id="a")]
    lat = build_lattice(docs)
    assert lat.index["a"].kind == "file"
    assert lat.index["sec"].kind == "section"
    assert lat.index["sec"].span == (1, 2)


def test_resolves_edges_and_builds_dependents():
    docs = [
        _doc("up.md", "# Up {#accent}\nx\n", id="up"),
        _doc("down.md", "body\n", id="down", derives_from=[RawEdge(ref="up#accent", seen="h")]),
    ]
    lat = build_lattice(docs)
    edge = lat.nodes_by_id["down"].derives_from[0]
    assert edge.target_id == "accent"
    assert lat.dependents["accent"] == frozenset({"down"})


def test_broken_ref_is_none_not_error():
    docs = [_doc("d.md", "b\n", id="d", derives_from=[RawEdge(ref="ghost")])]
    lat = build_lattice(docs)
    assert lat.nodes_by_id["d"].derives_from[0].target_id is None
    assert "ghost" not in lat.dependents


def test_duplicate_id_raises():
    docs = [_doc("a.md", "b\n", id="dup"), _doc("b.md", "c\n", id="dup")]
    with pytest.raises(DuplicateIdError):
        build_lattice(docs)


def test_anchor_collides_with_file_id_raises():
    docs = [_doc("a.md", "# A {#b}\n", id="a"), _doc("b.md", "x\n", id="b")]
    with pytest.raises(DuplicateIdError):
        build_lattice(docs)


def test_ancestors_computed_for_nested_anchor():
    body = "# Parent {#parent}\n\n## Child {#child}\nx\n"
    lat = build_lattice([_doc("a.md", body, id="a")])
    assert lat.ancestors["child"] == ("parent",)
    assert lat.ancestors["parent"] == ()
