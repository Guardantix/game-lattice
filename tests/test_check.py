"""Tests for check."""

from pathlib import Path

from game_lattice.check import check_lattice, has_drift
from game_lattice.config import load_config
from game_lattice.hashing import content_hash
from game_lattice.loader import build_lattice
from game_lattice.model import NodeMeta, ParsedDoc, RawEdge
from game_lattice.orchestrate import load_lattice
from game_lattice.sections import build_toc, section_span, section_text


def test_check_classifies_each_state(lattice_dir: Path):
    project = load_config(None, lattice_dir)
    lat = load_lattice(project)
    by_pair = {(s.source_id, s.target_ref): s.state for s in check_lattice(lat)}
    assert by_pair[("pc-design", "art-direction#accent")] == "STALE"
    assert by_pair[("pc-design", "art-direction#motion")] == "UNRECONCILED"
    assert by_pair[("gdd", "ghost")] == "BROKEN"


def test_has_drift_true_when_any_non_ok(lattice_dir: Path):
    project = load_config(None, lattice_dir)
    lat = load_lattice(project)
    assert has_drift(check_lattice(lat)) is True


def test_has_drift_false_when_all_ok():
    up_body = "# Up {#accent}\naccent\n"
    span = section_span(build_toc(up_body), 0, len(up_body.splitlines()))
    seen = content_hash(section_text(up_body, span))
    docs = [
        ParsedDoc(Path("up.md"), NodeMeta(id="up"), up_body),
        ParsedDoc(
            Path("down.md"),
            NodeMeta(id="down", derives_from=[RawEdge(ref="accent", seen=seen)]),
            "x\n",
        ),
    ]
    statuses = check_lattice(build_lattice(docs))
    assert all(s.state == "OK" for s in statuses)
    assert has_drift(statuses) is False
