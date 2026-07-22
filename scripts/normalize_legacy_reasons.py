"""Record the normalized legacy replay baseline for the successor replay gate (spec S6.4).

The replay gate compares, per replay-inventory entry, the tuple (status, retained invocation
tuples, reason category). The baseline scanner's ``incomplete_reason`` is unstructured English
prose, so this script freezes each entry's baseline tuple at commit ``be4b7b1`` and maps every
distinct ``incomplete_reason`` string to a stable successor reason category through one explicit,
static mapping. The mapping is embedded in the artifact so the future gate harness never
re-infers a category from a legacy error substring (S6.4).

The mapping is total for the strings the 580-entry inventory produces: an ``incomplete_reason``
absent from ``_REASON_MAP`` aborts generation rather than falling into a silent bucket, so any
future scanner string is a deliberate addition. Where one legacy string could map to two
successor codes, the affected entries carry ``owner_adjudicate: true`` and the conservative
(broadest-refusal, fail-closed) code is pinned pending owner ratification. Legacy scanner resource
bounds that no successor code models are recorded under ``legacy_only_categories``.

Run ``env -u VIRTUAL_ENV uv run --group dev python scripts/normalize_legacy_reasons.py``. The
output is deterministic: identical inputs produce byte-identical output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = REPO_ROOT / "tests" / "fixtures" / "github_ci_checkpoint"
SUCCESSOR = REPO_ROOT / "tests" / "fixtures" / "github_ci_successor_checkpoint"
INVENTORY = CHECKPOINT / "replay_inventory.json"
REASON_CODES = SUCCESSOR / "tables" / "reason_codes.json"
OUTPUT = SUCCESSOR / "legacy_normalization.json"

# The frozen baseline the recorded tuples are pinned to. Docs-only commits may sit on top, but
# every source file under src/ must match this commit (checked in ``_verify_baseline``).
BASELINE_COMMIT = "be4b7b16d46353ee6a38502cdc7c4ceef3487567"  # pragma: allowlist secret

# Reason categories the successor recognizer never emits, used for legacy scanner resource bounds
# (recursion, step, invocation, and nesting limits) that no successor reason code models.
LEGACY_SCAN_BUDGET = "legacy-scan-budget"
_LEGACY_ONLY_CATEGORIES: tuple[str, ...] = (LEGACY_SCAN_BUDGET,)

# Every distinct ``incomplete_reason`` string the live scanner emits over the replay inventory,
# mapped to its successor reason code (the ``code`` column of the frozen reason-code table) or to
# a legacy-only category. Grouped by the refusal the legacy string describes.
_REASON_MAP: dict[str, str] = {
    # Dynamic env/exec assignment prefixes: an assignment prefix whose value is not statically
    # known. Exact match for the command-local ``assignment-prefix`` code.
    "quoted dynamic env assignment cannot be scanned safely": "assignment-prefix",
    "unquoted dynamic env assignment cannot be scanned safely": "assignment-prefix",
    "dynamic env prefix cannot be scanned safely": "assignment-prefix",
    "expandable env prefix cannot be scanned safely": "assignment-prefix",
    # Brace or glob expansion on a command, subcommand, or launcher word: the word can expand to
    # more than one argument. Matches the S5.2 multi-cardinality-word to ``splitting-unsafe-word``
    # mapping.
    "executable word uses brace or glob expansion": "splitting-unsafe-word",
    "subcommand word uses brace or glob expansion": "splitting-unsafe-word",
    "uv command word uses brace or glob expansion": "splitting-unsafe-word",
    # Unresolved doc-lattice or uv launcher options: the source looks like a doc-lattice launch
    # but cannot be resolved under the floor. Command-local ``policy-unresolvable``.
    "unresolved doc-lattice root option": "policy-unresolvable",
    "unresolved uv launcher option": "policy-unresolvable",
    "unresolved uv global option": "policy-unresolvable",
    # Constructs the certifier does not model (locale translation, ANSI-C NUL, unsupported
    # env/exec options, and the external time(1) wrapper). Terminal ``unsupported-construct``.
    "ANSI-C quoted word decodes to NUL": "unsupported-construct",
    "locale-translated executable cannot be scanned safely": "unsupported-construct",
    "locale-translated heredoc delimiter cannot be scanned safely": "unsupported-construct",
    "unsupported env option cannot be scanned safely": "unsupported-construct",
    "unsupported exec option cannot be scanned safely": "unsupported-construct",
    "env option value cannot be scanned safely": "unsupported-construct",
    "external time option cannot be scanned safely": "unsupported-construct",
    "dynamic external time prefix cannot be scanned safely": "unsupported-construct",
    # --- Owner-adjudicated ties (see _ADJUDICATED). ---
    # env --split-string / -S both reads as an unmodeled option and as word splitting. Conservative
    # pin: terminal unsupported-construct (broadest refusal, matching the legacy terminal stop).
    "env split-string option cannot be scanned safely": "unsupported-construct",
    # An expansion at the command-word position reads as both an unquoted expansion in the command
    # word and an unstable first word. Conservative pin: unquoted-expansion-in-command-word.
    "command-position expansion cannot be scanned safely": "unquoted-expansion-in-command-word",
    # Extglob reads as both an unmodeled expansion (subtree-local) and an unmodeled construct.
    # Conservative pin: terminal unsupported-construct (broadest refusal).
    "extglob expansion cannot be scanned safely": "unsupported-construct",
    # A dynamic relative ./doc-lattice executable reads as both a doc-lattice launch that cannot be
    # resolved and an unstable first word. Conservative pin: policy-unresolvable.
    "dynamic relative doc-lattice executable cannot be scanned safely": "policy-unresolvable",
    # Legacy scanner recursion bound: no successor reason code models it.
    "recursion limit exceeded": LEGACY_SCAN_BUDGET,
}

# Legacy strings a single string could reasonably assign to two successor codes; the entries they
# produce carry owner_adjudicate: true so the owner ratifies the conservative pin above.
_ADJUDICATED: frozenset[str] = frozenset(
    {
        "env split-string option cannot be scanned safely",
        "command-position expansion cannot be scanned safely",
        "extglob expansion cannot be scanned safely",
        "dynamic relative doc-lattice executable cannot be scanned safely",
    }
)


def _verify_baseline() -> None:
    """Abort unless every tracked src/ file matches the frozen baseline commit.

    Docs-only commits may sit on top of the baseline, but a source change would invalidate the
    recorded tuples, so a non-empty ``git diff --stat`` against src/ stops generation.

    Raises:
        SystemExit: If git is unavailable or src/ diverges from the baseline commit.
    """
    result = subprocess.run(
        ["git", "diff", "--stat", BASELINE_COMMIT, "--", "src/"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"baseline check failed: git diff exited {result.returncode}: {result.stderr.strip()}"
        )
    if result.stdout.strip():
        raise SystemExit(
            "src/ diverges from baseline "
            f"{BASELINE_COMMIT[:7]}; the recorded tuples would be stale:\n{result.stdout}"
        )


def _validate_mapping(valid_codes: set[str]) -> None:
    """Confirm every mapping target is a known successor code or a legacy-only category.

    Args:
        valid_codes: The ``code`` values from the frozen reason-code table.

    Raises:
        SystemExit: If a mapping target is neither a successor code nor a legacy-only category.
    """
    allowed = valid_codes | set(_LEGACY_ONLY_CATEGORIES)
    unknown = sorted({category for category in _REASON_MAP.values() if category not in allowed})
    if unknown:
        raise SystemExit(f"mapping targets are not valid categories: {unknown}")
    missing = sorted(_ADJUDICATED - set(_REASON_MAP))
    if missing:
        raise SystemExit(f"adjudicated strings absent from the mapping: {missing}")


def _normalize_entries(entries_in: list[dict[str, object]]) -> list[dict[str, object]]:
    """Record one baseline tuple per replay entry, in inventory order.

    Args:
        entries_in: The replay-inventory entries, each carrying ``id`` and ``source``.

    Returns:
        One normalized record per entry with status, invocations, reason category, and the
        owner-adjudication flag.

    Raises:
        SystemExit: If an entry produces an ``incomplete_reason`` absent from the mapping.
    """
    from doc_lattice.github_ci.shell_scanner import (  # noqa: PLC0415
        scan_doc_lattice_invocations,
    )

    records: list[dict[str, object]] = []
    for entry in entries_in:
        source = str(entry["source"])
        result = scan_doc_lattice_invocations(source)
        invocations = [[command, dry_run] for command, dry_run in result.invocations]
        reason = result.incomplete_reason
        if reason is None:
            record: dict[str, object] = {
                "id": entry["id"],
                "status": "complete",
                "invocations": invocations,
                "reason_category": None,
                "owner_adjudicate": False,
            }
        else:
            if reason not in _REASON_MAP:
                raise SystemExit(
                    f"unmapped incomplete_reason {reason!r} for entry {entry['id']!r}; add it to "
                    "_REASON_MAP deliberately"
                )
            record = {
                "id": entry["id"],
                "status": "incomplete",
                "invocations": invocations,
                "reason_category": _REASON_MAP[reason],
                "owner_adjudicate": reason in _ADJUDICATED,
            }
        records.append(record)
    return records


def _print_summary(entries: list[dict[str, object]]) -> None:
    """Print complete/incomplete, per-category, and adjudication counts for the operator."""
    complete = sum(1 for entry in entries if entry["status"] == "complete")
    incomplete = len(entries) - complete
    adjudicated = sum(1 for entry in entries if entry["owner_adjudicate"])
    category_counts: dict[str, int] = {}
    for entry in entries:
        category = entry["reason_category"]
        if isinstance(category, str):
            category_counts[category] = category_counts.get(category, 0) + 1
    print(f"entries: {len(entries)}  complete: {complete}  incomplete: {incomplete}")
    print(f"owner_adjudicate: {adjudicated}")
    print("reason categories:")
    for category in sorted(category_counts):
        print(f"  {category}: {category_counts[category]}")


def main() -> None:
    """Generate the legacy-reason normalization artifact and print the summary counts."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    _verify_baseline()

    reason_codes = json.loads(REASON_CODES.read_text(encoding="utf-8"))
    valid_codes = {str(row["code"]) for row in reason_codes["rows"]}
    _validate_mapping(valid_codes)

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    entries = _normalize_entries(inventory["entries"])
    if len(entries) != inventory["count"]:
        raise SystemExit(
            f"entry count {len(entries)} does not match inventory count {inventory['count']}"
        )

    artifact = {
        "baseline_commit": BASELINE_COMMIT,
        "mapping": {reason: _REASON_MAP[reason] for reason in sorted(_REASON_MAP)},
        "legacy_only_categories": sorted(_LEGACY_ONLY_CATEGORIES),
        "entries": entries,
    }
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_summary(entries)


if __name__ == "__main__":
    main()
