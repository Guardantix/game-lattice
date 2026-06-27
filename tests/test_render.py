"""Tests for graph rendering."""

from pathlib import Path

from game_lattice.loader import build_lattice
from game_lattice.model import NodeMeta, ParsedDoc, RawEdge
from game_lattice.render import to_dot, to_mermaid


def _lattice():
    return build_lattice(
        [
            ParsedDoc(Path("up.md"), NodeMeta(id="up", title="Up"), "# Up {#u}\nx\n"),
            ParsedDoc(Path("down.md"), NodeMeta(id="down", derives_from=[RawEdge(ref="u")]), "x\n"),
        ]
    )


def test_mermaid_has_nodes_and_edges():
    out = to_mermaid(_lattice(), set())
    assert out.startswith("graph TD")
    assert "up" in out
    assert "down" in out
    assert "-->" in out


def test_mermaid_styles_stale_edges():
    out = to_mermaid(_lattice(), {("down", "u")})
    assert "-.->" in out  # dashed arrow for stale


def test_dot_is_digraph():
    out = to_dot(_lattice(), set())
    assert out.startswith("digraph lattice")
    assert "->" in out
