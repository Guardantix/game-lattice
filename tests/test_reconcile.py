"""Tests for reconcile."""

from pathlib import Path

import pytest

from game_lattice.check import check_lattice
from game_lattice.config import load_config
from game_lattice.error_types import (
    BrokenRefError,
    ProjectError,
    UnreadableDocError,
    ValidationError,
)
from game_lattice.orchestrate import load_lattice
from game_lattice.reconcile import apply_reconcile, reconcile


def test_apply_reconcile_sets_seen_and_preserves_body():
    text = "---\nid: d\nderives_from:\n  - ref: a#x\n    seen: old\n---\n# Body\nkeep me\n"
    out, applied = apply_reconcile(text, {"a#x": "newhash"})
    assert "seen: newhash" in out
    assert "old" not in out
    assert out.endswith("# Body\nkeep me\n")
    assert applied == {"a#x"}


def test_apply_reconcile_adds_missing_seen():
    text = "---\nid: d\nderives_from:\n  - ref: a#x\n---\nbody\n"
    out, applied = apply_reconcile(text, {"a#x": "h"})
    assert "seen: h" in out
    assert applied == {"a#x"}


def test_apply_reconcile_no_match_leaves_text_and_reports_nothing():
    # A ref edited away between load and write no longer matches the plan key.
    text = "---\nid: d\nderives_from:\n  - ref: a#x\n    seen: old\n---\nbody\n"
    out, applied = apply_reconcile(text, {"a#gone": "newhash"})
    assert applied == set()
    assert out == text


def test_apply_reconcile_null_derives_from_is_safe():
    text = "---\nid: d\nderives_from:\n---\nbody\n"
    out, applied = apply_reconcile(text, {"a#x": "h"})
    assert applied == set()
    assert out == text


def test_apply_reconcile_unparseable_frontmatter_raises():
    text = "---\nfoo: [1, 2\n---\nbody\n"
    with pytest.raises(UnreadableDocError):
        apply_reconcile(text, {"a#x": "h"})


def test_apply_reconcile_non_mapping_frontmatter_raises():
    text = "---\n- just\n- a list\n---\nbody\n"
    with pytest.raises(UnreadableDocError):
        apply_reconcile(text, {"a#x": "h"})


def test_apply_reconcile_non_mapping_entry_raises():
    text = "---\nid: d\nderives_from:\n  - plainstring\n---\nbody\n"
    with pytest.raises(UnreadableDocError):
        apply_reconcile(text, {"a#x": "h"})


def test_reconcile_clears_drift_for_node(lattice_dir: Path):
    project = load_config(None, lattice_dir)
    lat = load_lattice(project)
    writes = reconcile(lat, "pc-design", ref=None, reconcile_all=False)
    # Apply the planned writes to disk.
    for path, updates in writes.items():
        new_text, _ = apply_reconcile(path.read_text(encoding="utf-8"), updates)
        path.write_text(new_text, encoding="utf-8")
    # Reload and confirm pc-design no longer drifts.
    relat = load_lattice(load_config(None, lattice_dir))
    pc_states = [s.state for s in check_lattice(relat) if s.source_id == "pc-design"]
    assert pc_states == ["OK", "OK"]


def test_reconcile_preserves_concurrent_body_edit():
    text_initial = "---\nid: d\nderives_from:\n  - ref: a#x\n    seen: old\n---\nORIGINAL\n"
    # Simulate a concurrent body edit before the in-place write.
    text_fresh = text_initial.replace("ORIGINAL", "EDITED LATER")
    out, applied = apply_reconcile(text_fresh, {"a#x": "newhash"})
    assert "EDITED LATER" in out
    assert "seen: newhash" in out
    assert applied == {"a#x"}


def test_reconcile_node_skips_broken_edge(lattice_dir: Path):
    # gdd's only edge is broken; a node-level reconcile skips it without raising.
    lat = load_lattice(load_config(None, lattice_dir))
    assert reconcile(lat, "gdd", ref=None, reconcile_all=False) == {}


def test_reconcile_ref_targeting_broken_raises(lattice_dir: Path):
    # Aiming --ref directly at a broken edge is still refused.
    lat = load_lattice(load_config(None, lattice_dir))
    with pytest.raises(BrokenRefError):
        reconcile(lat, "gdd", ref="ghost", reconcile_all=False)


def test_reconcile_node_with_stale_and_broken_reconciles_stale(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "up.md").write_text("---\nid: up\n---\n# Up {#sec}\nsec body\n", encoding="utf-8")
    (docs / "d.md").write_text(
        "---\nid: d\nderives_from:\n"
        "  - ref: up#sec\n    seen: stalestalestalestalestalestale00\n"
        "  - ref: ghost\n---\n# D\nbody\n",
        encoding="utf-8",
    )
    lat = load_lattice(load_config(None, tmp_path))
    plan = reconcile(lat, "d", ref=None, reconcile_all=False)
    all_refs = {ref for updates in plan.values() for ref in updates}
    assert "up#sec" in all_refs  # the stale edge is reconciled
    assert "ghost" not in all_refs  # the unrelated broken edge is skipped, not raised


def test_reconcile_unknown_id_raises(lattice_dir: Path):
    lat = load_lattice(load_config(None, lattice_dir))
    with pytest.raises(ValidationError) as exc_info:
        reconcile(lat, "does-not-exist", ref=None, reconcile_all=False)
    assert isinstance(exc_info.value, ProjectError)


def test_reconcile_ref_bare_matches_namespaced(lattice_dir: Path):
    lat = load_lattice(load_config(None, lattice_dir))
    # "accent" (bare) should match the stored ref "art-direction#accent" (namespaced)
    plan = reconcile(lat, "pc-design", ref="accent", reconcile_all=False)
    assert plan, "plan must be non-empty"
    # The plan is keyed by path; collect all target_refs across all files
    all_refs = {ref for updates in plan.values() for ref in updates}
    assert "art-direction#accent" in all_refs


def test_reconcile_all_skips_broken_and_ok(lattice_dir: Path):
    lat = load_lattice(load_config(None, lattice_dir))
    # Must not raise despite gdd's BROKEN edge
    plan = reconcile(lat, "", ref=None, reconcile_all=True)
    # Collect all target_refs across all files in the plan
    all_refs = {ref for updates in plan.values() for ref in updates}
    # pc-design's two drifting edges should be in the plan
    assert "art-direction#accent" in all_refs
    assert "art-direction#motion" in all_refs
    # gdd's broken ghost ref must NOT be in the plan
    assert "ghost" not in all_refs
