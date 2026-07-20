"""Shared harness for the issue #100 recognizer evaluation gates.

Test-side only: this module orchestrates the frozen checkpoint artifacts, the old scanner
baseline, and the candidate recognizer for the predeclared gates. It never touches runtime
audit behavior.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from doc_lattice.error_types import ConfigError
from doc_lattice.github_ci.direct_marker_scanner import scan_execution_source
from doc_lattice.github_ci.model import BlockScan
from doc_lattice.github_ci.shell_scanner import (
    direct_doc_lattice_invocations,
    scan_doc_lattice_invocations,
)
from doc_lattice.github_ci.workflow_parser import parse_workflow

CHECKPOINT = Path("tests/fixtures/github_ci_checkpoint")


def _load(name: str):
    """Parse one checkpoint JSON artifact."""
    return json.loads((CHECKPOINT / name).read_text())


def load_replay_inventory():
    """Return the frozen 580-entry replay inventory."""
    return _load("replay_inventory.json")


def load_tier3a_cases():
    """Return the 13 Tier 3A conformance cases."""
    return _load("tier3a_cases.json")["cases"]


def load_tier3b_provenance():
    """Return the Tier 3B provenance manifest."""
    return _load("tier3b/provenance.json")


def load_probes():
    """Return the frozen probe inventory."""
    return _load("probes.json")


def load_mutations():
    """Return the frozen boundary-mutation set."""
    return _load("mutations.json")


def load_bash_pin():
    """Return the frozen Bash pin."""
    return _load("bash_pin.json")


def tier3b_run_block(fixture_id: str) -> str:
    """Extract the single run: block of one Tier 3B workflow fixture via the real parser."""
    path = CHECKPOINT / "tier3b" / f"{fixture_id}.yml"
    document = parse_workflow(path, path.read_text())
    runs = [step.run for job in document.jobs for step in job.steps if step.run is not None]
    assert len(runs) == 1, fixture_id
    return runs[0]


@dataclass(frozen=True, slots=True)
class OldResult:
    """Normalized old-scanner outcome for one source (raw and adapter layers)."""

    certified: bool
    invocations: tuple[tuple[str, bool], ...]
    incomplete_reason: str | None
    adapter_config_error: bool


def old_scan(source: str) -> OldResult:
    """Run both old entry points and normalize their results (never exception text)."""
    result = scan_doc_lattice_invocations(source)
    try:
        direct_doc_lattice_invocations(source)
        adapter_config_error = False
    except ConfigError:
        adapter_config_error = True
    return OldResult(
        certified=result.incomplete_reason is None,
        invocations=tuple(result.invocations),
        incomplete_reason=result.incomplete_reason,
        adapter_config_error=adapter_config_error,
    )


def classify_divergence(old: OldResult, new: BlockScan) -> str:
    """Classify one old-versus-new pair into the predeclared gate 2 categories."""
    if new.status == "not_applicable":
        return "outside-direct-marker"
    if old.certified and new.status == "certified":
        return "identical" if old.invocations == new.invocations else "unexplained"
    if old.certified and new.status == "uninspectable":
        return "intentional-exit-2"
    if not old.certified and new.status == "uninspectable":
        return "identical"
    if not old.certified and new.status == "certified":
        return "old-incomplete-new-certified"
    return "unexplained"


def _tier_sources() -> list[tuple[str, str]]:
    """Return (case id, source) pairs for every tier source beyond the replay inventory."""
    sources = [(case["id"], case["source"]) for case in load_tier3a_cases()]
    for row in load_tier3b_provenance()["fixtures"]:
        sources.append((row["id"], tier3b_run_block(row["id"])))
    return sources


def replay_records() -> list[dict]:
    """Produce one normalized record per replay-inventory entry and per tier source."""
    records = []
    entries = [(entry["id"], entry["source"]) for entry in load_replay_inventory()["entries"]]
    for case_id, source in entries + _tier_sources():
        old = old_scan(source)
        new = scan_execution_source(source)
        records.append(
            {
                "id": case_id,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "old_certified": old.certified,
                "old_invocations": [list(pair) for pair in old.invocations],
                "old_incomplete_reason": old.incomplete_reason,
                "old_adapter_config_error": old.adapter_config_error,
                "new_status": new.status,
                "new_invocations": [list(pair) for pair in new.invocations],
                "new_reason_category": new.reason_category,
                "new_offset": new.offset,
                "category": classify_divergence(old, new),
            }
        )
    return records
