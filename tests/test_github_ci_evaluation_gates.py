"""Predeclared evaluation gates for the issue #100 recognizer candidate (spec gates 1-6, 8, 9)."""

import json
from pathlib import Path

import pytest

from doc_lattice.github_ci.direct_marker_scanner import scan_execution_source

CHECKPOINT = Path("tests/fixtures/github_ci_checkpoint")

_LABELS = json.loads((CHECKPOINT / "acceptance_labels.json").read_text())["cases"]


def _acceptance_cases():
    from test_github_ci_shell_scanner import ACCEPTANCE_CASES  # noqa: PLC0415

    return ACCEPTANCE_CASES


@pytest.mark.parametrize("index", range(78), ids=[row["description"] for row in _LABELS])
def test_gate1_acceptance_label_conformance(index):
    row = _LABELS[index]
    description, script, _expected = _acceptance_cases()[index]
    assert row["description"] == description
    result = scan_execution_source(script)
    assert result.status == row["expected_status"], (description, result.reason)
    assert [list(i) for i in result.invocations] == row["expected_invocations"], description
    if row["expected_status"] == "uninspectable":
        assert result.reason_category == row["reason_category"], (
            description,
            result.offset,
            result.reason,
        )


def test_gate2_replay_divergences_stay_in_predeclared_categories():
    from github_ci_evaluation_harness import replay_records  # noqa: PLC0415

    records = replay_records()
    assert len(records) == 580 + 13 + 20
    allowed = {"identical", "intentional-exit-2", "outside-direct-marker"}
    unexplained = [r for r in records if r["category"] == "unexplained"]
    assert unexplained == [], unexplained[:5]
    category_d = [r["id"] for r in records if r["category"] == "old-incomplete-new-certified"]
    prelabeled = json.loads((CHECKPOINT / "category_d_exceptions.json").read_text())
    assert category_d == prelabeled == []
    assert {r["category"] for r in records} <= allowed
