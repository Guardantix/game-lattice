"""Tests for impact."""

from pathlib import Path

from game_lattice.impact import expand_targets, impact
from game_lattice.loader import build_lattice
from game_lattice.model import NodeMeta, ParsedDoc, RawEdge


def _doc(path: str, body: str, **meta) -> ParsedDoc:
    return ParsedDoc(Path(path), NodeMeta(**meta), body)


def test_section_token_expands_to_ancestors():
    body = "# Parent {#parent}\n\n## Child {#child}\nx\n"
    lat = build_lattice([_doc("a.md", body, id="a")])
    assert expand_targets(lat, "child") == {"child", "parent"}


def test_file_token_expands_to_its_anchors():
    body = "# A {#a-top}\n\n## Sec {#sec}\nx\n"
    lat = build_lattice([_doc("a.md", body, id="a")])
    assert expand_targets(lat, "a") == {"a", "a-top", "sec"}


def test_impact_includes_parent_dependents_for_nested_edit():
    parent = "# Parent {#parent}\n\n## Child {#child}\nx\n"
    lat = build_lattice(
        [
            _doc("up.md", parent, id="up"),
            _doc("d-parent.md", "x\n", id="d-parent", derives_from=[RawEdge(ref="parent")]),
            _doc("d-child.md", "x\n", id="d-child", derives_from=[RawEdge(ref="child")]),
        ]
    )
    affected = {n.id for n in impact(lat, "child")}
    assert affected == {"d-parent", "d-child"}


def test_impact_is_transitive():
    lat = build_lattice(
        [
            _doc("up.md", "# Up {#u}\nx\n", id="up"),
            _doc("mid.md", "x\n", id="mid", derives_from=[RawEdge(ref="u")]),
            _doc("low.md", "x\n", id="low", derives_from=[RawEdge(ref="mid")]),
        ]
    )
    assert {n.id for n in impact(lat, "u")} == {"mid", "low"}
