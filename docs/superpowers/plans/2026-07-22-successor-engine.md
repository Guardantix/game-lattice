# Successor Python Engine Implementation Plan (Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dormant Python successor engine (protocol boundary, supervisor, locator,
direct-marker relocation, D6 shell composition, the launcher-policy interface revision,
syntax certifier, successor audit) and bring every locally runnable gate (spec section 9,
gates 1 through 10) green against the frozen checkpoint and the Plan A helper binary.

**Architecture:** The Go helper (Plan A, complete at `c00c821`) emits syntax-only events over
the frozen wire protocol. This plan adds the Python half: one generated contracts module
projects the checkpoint tables and limits into typed constants; `helper_protocol_boundary.py`
is the only module that touches raw helper JSON; `helper_supervisor.py` owns the process
lifecycle; `syntax_certifier.py` is translation-only (byte-to-char and sentinel offset
projection); all product policy (markers, dispatcher, look-alike, precedence) lives in the
revised `launcher_policy.py`; `successor_audit.py` folds events into D4/D5 outcomes.
Everything is dormant: `audit.py`, `shell_scanner.py`, and the CLI never import any new
module in this plan. The gate harness builds the helper binary once per session and drives
the full pipeline against the frozen corpus, tiers, replay baseline, and protocol fixtures.

**Tech Stack:** Python 3.13 via `uv`, pytest, the Plan A Go helper built by
`scripts/build_successor_helper.sh` (Go 1.26.5 at `/usr/local/go/bin/go`), `/bin/bash` and
`shfmt` as the gate 7 oracles, the frozen checkpoint at
`tests/fixtures/github_ci_successor_checkpoint/` (cited as CP).

**Spec:** `docs/superpowers/specs/2026-07-21-mvdan-helper-evaluation-design.md` (cited as
S3.1, S5.2, etc.). Read the cited sections and CP artifacts before each task; the CP tables
and fixtures are the executable contract.

**Deferred to Plan C (evidence phase):** the evaluation CI workflow, five-target candidate
wheels and install smoke, the sdist degradation harness, peak-RSS and end-to-end performance
gates (11, 12), the wheel gate (13), surface accounting (14), evidence pinning, and the
decision record.

## Global Constraints

- The checkpoint is RATIFIED and FROZEN at its current revision (the Plan A tree at
  `c00c821` includes two owner-authorized post-ratification revisions, recorded in
  `CP/README.md`). Nothing under `tests/fixtures/github_ci_successor_checkpoint/` may change
  in this plan; `tests/test_successor_checkpoint.py::test_manifest_matches_checkpoint_inputs`
  enforces it. A task that believes it needs a checkpoint change is BLOCKED: stop and
  escalate to Rick; only the owner can authorize a revision.
- Release freeze holds: version stays `2.0.0`; no CHANGELOG heading changes; no tags; no
  README behavior changes. `audit.py`, `shell_scanner.py`, `direct_marker_scanner.py`
  behavior, the CLI, and the runtime import graph stay untouched (Task 2's import relocation
  is the sole, behavior-preserving exception in `direct_marker_scanner.py`).
- The frozen D3 checkpoint `tests/fixtures/github_ci_checkpoint/` is never modified.
- Baseline commit for this plan: `c00c821` (Plan A complete). Work on branch
  `successor-evaluation` in the existing worktree. Do not push and do not open a PR.
- Generated files are never hand-edited. The new `_successor_contracts.py` follows the
  `_github_slugger_data.py` convention: generator script with a `--check` drift mode.
- Pinned implementation obligations from the adversarial rounds: (1) dispatcher-selector
  recognition claims an unresolved selector word BEFORE the generic `single=False`
  cardinality precheck (Task 6); (2) the wire IR invariant `text is not None implies single`
  is validated at the protocol boundary (Task 3), never assumed.
- Helper binaries build via `scripts/build_successor_helper.sh ABSOLUTE_PATH` with the
  output OUTSIDE the repository (the script enforces this). Never commit a binary.
- Python rules: `typing.Any`/`typing.cast` only in boundary-named modules recognized by
  `scripts/check_typing_boundaries.py` (`helper_protocol_boundary.py` qualifies via its
  `_boundary` stem suffix; no other new module may use them). Custom exceptions extend
  `ProjectError` and hardcode a `code`. `Literal` + `get_args()` + `frozenset` for string
  domains in `constants.py`. No `datetime.now()` anywhere new (`time.monotonic()` is the
  deadline clock). Module docstrings everywhere; Google-style docstrings on public
  functions; Ruff 100-char lines; no em dashes in any drafted content (ASCII hyphens only).
- Run pytest as `env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest`
  (the dev shell exports `VIRTUAL_ENV` and `FORCE_COLOR=3`, both break runs otherwise).
- Source mirroring: `src/doc_lattice/github_ci/foo.py` maps to `tests/test_github_ci_foo.py`.
- Gate tests that need the helper binary or the Go toolchain use the shared session fixture
  from Task 10 and skip cleanly when `/usr/local/go/bin/go` is absent; every new production
  module must reach the coverage floor from Go-free unit tests alone (fake helpers).
- Every task ends with its focused tests green, Ruff clean on touched files, and a commit.
  Tasks 6 and onward also keep `ty` and the typing-boundaries check green. Full-suite runs
  happen at Tasks 6, 9, and 13, not every task.
- The SDD ledger records per-task Minors. The checkpoint ratification list is settled; no
  task reopens it.

## File Structure

```
scripts/
  generate_successor_contracts.py       # CP tables/limits -> generated Python constants
src/doc_lattice/
  constants.py                          # ScanReasonCategory extended (6 new members)
  github_ci/
    _successor_contracts.py             # generated, committed; never hand-edited
    direct_marker.py                    # relocated DIRECT_MARKER_RE + D2/S6.2 helpers
    direct_marker_scanner.py            # import relocation only; behavior unchanged
    helper_protocol_boundary.py         # the ONLY module touching raw helper JSON
    helper_supervisor.py                # process lifecycle, caps, deadline, BatchFailure
    helper_locator.py                   # package-owned helper lookup, typed unavailability
    launcher_policy.py                  # revised ScanWord + evaluate_command precheck stage
    shell_composition.py                # D1+D2+D6 collection, sentinel projection
    syntax_certifier.py                 # translation-only: events -> policy inputs, offsets
    successor_audit.py                  # dormant collect/batch/aggregate, D4/D5 fold
tests/
  conftest.py                           # + session-scoped successor_helper build fixture
  github_ci_successor_harness.py        # shared gate harness (loaders, pipeline drivers)
  test_github_ci_successor_contracts.py
  test_github_ci_direct_marker.py
  test_github_ci_helper_protocol_boundary.py
  test_github_ci_helper_supervisor.py   # gate 9 fault-injection core
  test_github_ci_helper_locator.py
  test_github_ci_launcher_policy.py     # extended; existing tests stay green
  test_github_ci_shell_composition.py
  test_github_ci_syntax_certifier.py
  test_github_ci_successor_audit.py
  test_github_ci_successor_gates.py     # gates 1-8, 10 against the real binary
  test_github_ci_successor_surface.py   # __all__ accounting + dormancy guard
```

---

### Task 1: Contracts projection into Python

**Files:**
- Create: `scripts/generate_successor_contracts.py`
- Create: `src/doc_lattice/github_ci/_successor_contracts.py` (generated, committed)
- Test: `tests/test_github_ci_successor_contracts.py`

**Interfaces:**
- Produces (`_successor_contracts.py`, all module-level constants):
  - `PROTOCOL_VERSION: int = 1`
  - `PARSER_VERSION: str = "mvdan.cc/sh/v3@v3.13.1"` (from `CP/pins/parser_pin.json`
    `module` + `"@"` + `version`)
  - `LIMITS: dict[str, int]` (every integer-valued top-level key of `CP/limits.json`:
    `python_source_cap_chars`, `helper_source_cap_bytes`, `aggregate_request_cap_bytes`,
    `stdout_cap_bytes`, `stderr_capture_cap_bytes`, `max_sources_per_batch`,
    `json_max_depth`, `max_argv_words_per_site`, `max_assignments_per_site`,
    `statement_cap`, `visitor_node_cap`, `visitor_depth_cap`, `event_cap`,
    `peak_rss_max_bytes`, `e2e_median_ceiling_ms`, `e2e_repetitions_per_python`)
  - `DEADLINE_MS: dict[str, int]` (the four keys of `limits.json["deadline_ms"]`)
  - `REASON_SCOPES: dict[str, str]` (reason code to scope, 19 entries)
  - `REASON_CATEGORIES: dict[str, str]` (reason code to `scan_reason_category`)
  - `STABLE_REASONS: dict[str, str]` (reason code to `stable_reason`)
  - `DISPATCHER_PLAIN_HEADS: frozenset[str]` (`{"eval", "source", "."}`)
  - `DISPATCHER_SHELL_HEADS: frozenset[str]` (`{"bash", "sh", "dash", "zsh"}`)
  - `PRECEDENCE_CHAIN: tuple[str, ...]` (the five-step chain from `CP/tables/precedence.json`)
- Produces (script): `--check` mode exiting 1 on drift, mirroring
  `scripts/generate_github_slugger_data.py`.

- [ ] **Step 1: Write the failing parity test**

Create `tests/test_github_ci_successor_contracts.py`:

```python
"""Parity tests for the generated successor contract projection (spec S8)."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECKPOINT = REPO / "tests" / "fixtures" / "github_ci_successor_checkpoint"


def test_generated_constants_match_checkpoint():
    """Every generated value equals its frozen checkpoint source value."""
    from doc_lattice.github_ci import _successor_contracts as gen

    limits = json.loads((CHECKPOINT / "limits.json").read_text(encoding="utf-8"))
    for key, value in limits.items():
        if isinstance(value, int):
            assert gen.LIMITS[key] == value, key
    assert gen.DEADLINE_MS == limits["deadline_ms"]
    rows = json.loads(
        (CHECKPOINT / "tables" / "reason_codes.json").read_text(encoding="utf-8")
    )["rows"]
    assert gen.REASON_SCOPES == {r["code"]: r["scope"] for r in rows}
    assert gen.REASON_CATEGORIES == {r["code"]: r["scan_reason_category"] for r in rows}
    assert gen.STABLE_REASONS == {r["code"]: r["stable_reason"] for r in rows}
    grammar = json.loads(
        (CHECKPOINT / "tables" / "dispatcher_grammar.json").read_text(encoding="utf-8")
    )
    assert gen.DISPATCHER_PLAIN_HEADS == frozenset(grammar["plain_heads"])
    assert gen.DISPATCHER_SHELL_HEADS == frozenset(grammar["shell_heads"])
    chain = json.loads(
        (CHECKPOINT / "tables" / "precedence.json").read_text(encoding="utf-8")
    )["chain"]
    assert gen.PRECEDENCE_CHAIN == tuple(chain)
    pin = json.loads((CHECKPOINT / "pins" / "parser_pin.json").read_text(encoding="utf-8"))
    assert gen.PARSER_VERSION == f"{pin['module']}@{pin['version']}"
    assert gen.PROTOCOL_VERSION == 1


def test_check_mode_is_clean():
    """The committed generated module matches a fresh generator run byte for byte."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_successor_contracts.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run to verify it fails**

Run: `env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest tests/test_github_ci_successor_contracts.py -q --no-cov`
Expected: FAIL (`ModuleNotFoundError: ... _successor_contracts`).

- [ ] **Step 3: Write the generator and generate**

`scripts/generate_successor_contracts.py` (module docstring; Google docstrings; no
`typing.Any`): reads `CP/limits.json`, `CP/tables/reason_codes.json`,
`CP/tables/dispatcher_grammar.json`, `CP/tables/precedence.json`, and
`CP/pins/parser_pin.json`; renders `_successor_contracts.py` deterministically (dict
literals in sorted key order, frozenset literals from sorted lists, a fixed header comment
naming the source files and the generator, "generated, do not edit"); default mode writes
the file, `--check` compares rendered bytes against the on-disk file and exits 1 on drift.
Model the argument handling and rendering style on
`scripts/generate_github_slugger_data.py`. The generated module needs a module docstring as
its first statement (repo rule) and plain literals only, so `ty` and Ruff pass without
suppressions.

Run the generator, then run it a second time and confirm `git status` shows no change
(deterministic output).

- [ ] **Step 4: Run the test file to verify it passes**, plus
`uv run --group dev ruff check scripts/generate_successor_contracts.py src/doc_lattice/github_ci/_successor_contracts.py tests/test_github_ci_successor_contracts.py`.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_successor_contracts.py src/doc_lattice/github_ci/_successor_contracts.py tests/test_github_ci_successor_contracts.py
git commit -m "feat: project the ratified checkpoint contracts into Python"
```

---

### Task 2: Reason-category domain extension and direct-marker relocation

**Files:**
- Modify: `src/doc_lattice/constants.py` (extend `ScanReasonCategory`)
- Create: `src/doc_lattice/github_ci/direct_marker.py`
- Modify: `src/doc_lattice/github_ci/direct_marker_scanner.py` (import relocation only)
- Test: `tests/test_github_ci_direct_marker.py`; extend `tests/test_constants.py`

**Interfaces:**
- Produces: `ScanReasonCategory` extended with exactly six new members:
  `"syntax-error"`, `"unsupported-construct"`, `"parser-divergence-guard"`,
  `"dispatcher-payload"`, `"marker-head-look-alike"`, `"splitting-unsafe-word"`
  (every value of `_successor_contracts.REASON_CATEGORIES` must then be a member).
- Produces (`direct_marker.py`):
  - `DIRECT_MARKER_RE = re.compile(r"doc[-_.]+lattice", re.ASCII | re.IGNORECASE)`
    (relocated verbatim; single product owner per S3.3)
  - `SCRIPT_PLACEHOLDER: str = "{0}"` and `SCRIPT_SENTINEL: str = "__doc_lattice_script__"`
    (the S6.2 sentinel pair; `audit.py` keeps its private copies untouched until PR B)
  - `has_direct_marker(text: str) -> bool`
  - `word_carries_marker(text: str | None, raw_segment: str | None) -> bool` implementing
    S6.2 synthetic-safe provenance: True when the pattern matches the statically known
    final `text` AFTER masking sentinel content (`text.replace(SCRIPT_SENTINEL,
    SCRIPT_PLACEHOLDER)`), or matches the authored `raw_segment` (decisive when `text` is
    None). A None `text` with a None `raw_segment` is False.
- Produces: `direct_marker_scanner.py` defines `DIRECT_MARKER_RE` no longer; it imports it
  from `direct_marker` and re-exports the same name so every existing importer
  (`tests/github_ci_evaluation_harness.py`, `tests/test_successor_checkpoint.py`,
  `tests/test_github_ci_direct_marker_scanner.py`) resolves unchanged.

- [ ] **Step 1: Write the failing tests**

`tests/test_github_ci_direct_marker.py`:

```python
"""Tests for the relocated direct-marker predicate and S6.2 provenance rule."""

from typing import get_args

from doc_lattice.constants import ScanReasonCategory
from doc_lattice.github_ci import _successor_contracts as contracts
from doc_lattice.github_ci.direct_marker import (
    SCRIPT_PLACEHOLDER,
    SCRIPT_SENTINEL,
    has_direct_marker,
    word_carries_marker,
)


def test_marker_predicate_matches_the_frozen_pattern():
    """The relocated predicate keeps the frozen D2 semantics."""
    assert has_direct_marker("# doc-lattice")
    assert has_direct_marker("DOC_LATTICE lint")
    assert has_direct_marker("./doc.lattice-wrapper")
    assert not has_direct_marker('doc-"lattice" linear')
    assert not has_direct_marker("doclattice")


def test_every_successor_category_is_in_the_domain():
    """Every frozen scan_reason_category value is a ScanReasonCategory member."""
    members = frozenset(get_args(ScanReasonCategory))
    for category in contracts.REASON_CATEGORIES.values():
        assert category in members, category


def test_word_marker_provenance_is_synthetic_safe():
    """S6.2: sentinel content never manufactures a marker; raw segments are decisive."""
    assert word_carries_marker("doc-lattice", "doc-lattice")
    assert word_carries_marker(None, '"doc-lattice $X"')
    assert not word_carries_marker(SCRIPT_SENTINEL, SCRIPT_PLACEHOLDER)
    assert not word_carries_marker(None, "$EXTRA")
    assert not word_carries_marker(None, None)
    # Known text is checked even when the raw spelling hides the marker (fail-closed).
    assert word_carries_marker("doc-lattice linear", "doc-\"lattice\" linear")
```

Extend `tests/test_constants.py` with the six new members following its existing pattern
(assert membership in `VALID_SCAN_REASON_CATEGORIES`).

- [ ] **Step 2: Run to verify failure**

Run: `env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest tests/test_github_ci_direct_marker.py tests/test_constants.py -q --no-cov`

- [ ] **Step 3: Implement**

Extend the `ScanReasonCategory` Literal in `constants.py` (append the six members;
`VALID_SCAN_REASON_CATEGORIES` follows automatically via `get_args`). Create
`direct_marker.py` with the interface above. In `direct_marker_scanner.py`, delete the
local `DIRECT_MARKER_RE` definition and add
`from doc_lattice.github_ci.direct_marker import DIRECT_MARKER_RE` near the top imports;
change nothing else in that module.

- [ ] **Step 4: Run the new tests plus the untouched regressions**

Run: `env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest tests/test_github_ci_direct_marker.py tests/test_constants.py tests/test_github_ci_direct_marker_scanner.py tests/test_successor_checkpoint.py -q --no-cov`
Expected: all pass; the scanner and checkpoint suites prove the relocation is inert.

- [ ] **Step 5: Commit**

```bash
git add src/doc_lattice/constants.py src/doc_lattice/github_ci/direct_marker.py \
  src/doc_lattice/github_ci/direct_marker_scanner.py tests/test_github_ci_direct_marker.py tests/test_constants.py
git commit -m "feat: extend the reason-category domain and relocate the direct marker"
```

---

### Task 3: helper_protocol_boundary.py (canonical encoder, strict decoder)

**Files:**
- Create: `src/doc_lattice/github_ci/helper_protocol_boundary.py`
- Test: `tests/test_github_ci_helper_protocol_boundary.py`

**Interfaces:**
- Produces (all `@dataclass(frozen=True, slots=True)`):
  - `WireWord(text: str | None, single: bool, start_byte: int, end_byte: int)`
  - `WireAssignment(name: str, value_known: bool, start_byte: int, end_byte: int)`
  - `WireEvent(kind: str, ordinal: int, code: str, start_byte: int, end_byte: int,
    assignments: tuple[WireAssignment, ...], argv: tuple[WireWord, ...])` (`kind` is
    `"command_site"` or `"refusal"`; refusals carry empty `assignments`/`argv` and
    ordinal 0; command sites carry `code=""`, mirroring the Go tagged union)
  - `WireResult(id: int, events: tuple[WireEvent, ...], work_units: int)`
- Produces: `HelperProtocolError(ProjectError)` constructed as
  `HelperProtocolError(message, code)` with `code` drawn from the S4.4 taxonomy names this
  module owns: `"malformed_output"`, `"protocol_violation"`, `"parser_pin_mismatch"`,
  `"helper_identity_mismatch"`, `"request_cap_exceeded"`.
- Produces: `encode_request(sources: Sequence[tuple[int, str]]) -> bytes` implementing the
  canonical encoder (`CP/protocol/encoder.json`): compact separators `(",", ":")`,
  `ensure_ascii=False`, `allow_nan=False`, no BOM, surrogate rejection before encoding;
  enforces ids contiguous `0..n-1` in order, batch count, per-source UTF-8 byte cap, and
  the aggregate cap measured on the encoded bytes; raises `HelperProtocolError` with
  `request_cap_exceeded` (caps) or `protocol_violation` (id or surrogate violations).
- Produces: `decode_response(raw: bytes, *, expected_ids: Sequence[int],
  source_byte_lengths: Mapping[int, int], expected_helper_version: str,
  expected_parser_version: str) -> tuple[WireResult, ...]`.
- This is the ONLY new module permitted `typing.Any` (its `_boundary` stem is recognized by
  `scripts/check_typing_boundaries.py`).

- [ ] **Step 1: Write the failing fixture-driven tests**

`tests/test_github_ci_helper_protocol_boundary.py` drives the frozen protocol fixtures:

```python
"""Strict wire-boundary tests against the frozen protocol fixtures (S4.2)."""

import json
from pathlib import Path

import pytest

from doc_lattice.error_types import ProjectError
from doc_lattice.github_ci.helper_protocol_boundary import (
    HelperProtocolError,
    decode_response,
    encode_request,
)

PROTOCOL = Path("tests/fixtures/github_ci_successor_checkpoint/protocol")


def _fixture(name: str) -> dict:
    return json.loads((PROTOCOL / "conformance" / name).read_text(encoding="utf-8"))


def _decode_kwargs(fixture: dict) -> dict:
    sources = fixture["request"]["sources"]
    return {
        "expected_ids": [s["id"] for s in sources],
        "source_byte_lengths": {s["id"]: len(s["source"].encode()) for s in sources},
        "expected_helper_version": fixture["response"]["helper_version"],
        "expected_parser_version": fixture["response"]["parser_version"],
    }


@pytest.mark.parametrize("name", sorted(p.name for p in (PROTOCOL / "conformance").iterdir()))
def test_conformance_round_trip(name):
    """Every frozen conformance pair encodes and decodes exactly."""
    fixture = _fixture(name)
    encoded = encode_request([(s["id"], s["source"]) for s in fixture["request"]["sources"]])
    assert json.loads(encoded) == fixture["request"]
    raw = json.dumps(fixture["response"], separators=(",", ":"), ensure_ascii=False).encode()
    results = decode_response(raw, **_decode_kwargs(fixture))
    assert [r.id for r in results] == [s["id"] for s in fixture["request"]["sources"]]
    for result, expected in zip(results, fixture["response"]["results"], strict=True):
        assert result.work_units == expected["work_units"]
        assert len(result.events) == len(expected["events"])
        for event, exp in zip(result.events, expected["events"], strict=True):
            assert event.kind == exp["kind"]
            assert (event.start_byte, event.end_byte) == (exp["start_byte"], exp["end_byte"])
            if event.kind == "command_site":
                assert [w.text for w in event.argv] == [w["text"] for w in exp["argv"]]
                assert [w.single for w in event.argv] == [w["single"] for w in exp["argv"]]
            else:
                assert event.code == exp["code"]


def test_error_taxonomy_is_project_error():
    """The boundary error carries a taxonomy code and extends ProjectError."""
    error = HelperProtocolError("boom", "malformed_output")
    assert isinstance(error, ProjectError)
    assert error.code == "malformed_output"
```

Then add the negative and boundary suites (write these fully in this task; the list below
is the required coverage, one test each, all expecting `HelperProtocolError` with the named
code unless stated):

- Response-shaped rejections built by mutating a valid response's serialized bytes:
  duplicate keys (`b'{"protocol_version":1,"protocol_version":1,...'` spliced) ->
  `malformed_output`; `NaN` number -> `malformed_output`; `True` where an int belongs
  (`isinstance(x, bool)` guard) -> `malformed_output`; invalid UTF-8 bytes
  (`PROTOCOL/negative/invalid-utf8.bin` fed as a response) -> `malformed_output`; trailing
  non-whitespace after the document -> `malformed_output`; unknown or missing fields ->
  `malformed_output`; JSON nesting deeper than `LIMITS["json_max_depth"]` ->
  `malformed_output`.
- Protocol violations on a well-formed document: results not exactly `expected_ids` in
  order (use `PROTOCOL/negative/out-of-order-results.json`'s response) ->
  `protocol_violation`; a span with `end_byte` past the recorded source byte length (use
  `PROTOCOL/negative/span-out-of-range.json`'s response) -> `protocol_violation`; events
  not in span order -> `protocol_violation`; `text` non-null with `single` false ->
  `protocol_violation`; more than `LIMITS["max_argv_words_per_site"]` argv entries or
  `LIMITS["max_assignments_per_site"]` assignments or `LIMITS["event_cap"]` events ->
  `protocol_violation` (construct these synthetically).
- Version checks: wrong `helper_version` -> `helper_identity_mismatch`; wrong
  `parser_version` -> `parser_pin_mismatch`.
- Request-side: encoding a batch of `LIMITS["max_sources_per_batch"]` one-byte sources
  succeeds while one more raises `request_cap_exceeded`; a source containing a lone
  surrogate (`"\ud800"`) raises `protocol_violation`; the boundary fixture
  `PROTOCOL/boundary/max-length-four-byte-source.json` request encodes successfully and its
  encoded length is under `LIMITS["aggregate_request_cap_bytes"]` (the S4.2 composition
  pin); non-contiguous ids raise `protocol_violation`.

- [ ] **Step 2: Run to verify failure** (import error), same pytest command scoped to the
new file.

- [ ] **Step 3: Implement**

Implementation requirements (S4.2, mirroring the Go decoder in
`helper/doc-lattice-shell-parser/wire.go`):

- Decode: strict UTF-8 (`raw.decode("utf-8")`, catching `UnicodeDecodeError`); a manual
  byte-level structure pre-scan before `json.loads` that tracks in-string and escape state,
  counts bracket depth against `LIMITS["json_max_depth"]`, and rejects trailing non-space
  bytes after the root value closes; `json.loads` with an `object_pairs_hook` that rejects
  duplicate keys and builds plain dicts, and `parse_constant` that raises (rejecting
  `NaN`/`Infinity`).
- Shape validation is exhaustive and closed: exactly the schema fields, correct types with
  `isinstance(value, bool)` checked before `isinstance(value, int)`, `protocol_version == 1`,
  `helper_version`/`parser_version` exact matches against the expected values (mismatch
  codes as above), results exactly `expected_ids` in ascending order, per-result events
  span-ordered (non-decreasing `start_byte`, tie-broken by kind then ordinal, matching the
  helper's stable sort), spans `0 <= start <= end <= source_byte_lengths[id]`, the
  `text is not None implies single` invariant, refusal codes non-empty strings, and the
  element caps listed in Step 1. Everything after the JSON parse raises `protocol_violation`;
  parse-level failures raise `malformed_output`.
- Encode: validate ids and surrogates first (`any(0xD800 <= ord(c) <= 0xDFFF for c in
  source)`), measure the per-source cap on `len(source.encode("utf-8"))` against
  `LIMITS["helper_source_cap_bytes"]` and the character cap is NOT this module's concern
  (the certifier owns `python_source_cap_chars`); build the document with
  `json.dumps(..., ensure_ascii=False, allow_nan=False, separators=(",", ":"))`, encode to
  UTF-8, and enforce the aggregate cap on the encoded bytes.
- `typing.Any` may appear only in this module's decode internals; every returned object is
  a typed frozen dataclass.

- [ ] **Step 4: Run the file green**, then
`uv run --group dev python scripts/check_typing_boundaries.py src` (must pass with the new
module using `Any`), and Ruff on touched files.

- [ ] **Step 5: Commit**

```bash
git add src/doc_lattice/github_ci/helper_protocol_boundary.py tests/test_github_ci_helper_protocol_boundary.py
git commit -m "feat: add the strict helper protocol boundary"
```

---

### Task 4: helper_supervisor.py (process lifecycle and BatchFailure)

**Files:**
- Create: `src/doc_lattice/github_ci/helper_supervisor.py`
- Test: `tests/test_github_ci_helper_supervisor.py`

**Interfaces:**
- Produces: `BatchFailure(ProjectError)` constructed as `BatchFailure(message, code)` with
  `code` from the frozen S4.4 taxonomy: `spawn_failure`, `timeout`, `exit_nonzero`,
  `output_cap_exceeded`, `malformed_output`, `protocol_violation`, `parser_pin_mismatch`,
  `helper_identity_mismatch`, `request_cap_exceeded`, `transport_failure`. Boundary errors
  (`HelperProtocolError`) are re-raised as `BatchFailure` carrying the same code and a
  bounded message (never raw helper bytes).
- Produces: `run_batch(helper_path: Path, sources: Sequence[tuple[int, str]], *,
  expected_helper_version: str, deadline_ms_override: int | None = None)
  -> tuple[WireResult, ...]`. The keyword-only override is a test seam; production callers
  omit it and get the frozen formula
  `min(DEADLINE_MS["ceiling"], DEADLINE_MS["base"] + DEADLINE_MS["per_source"] * len(sources)
  + len(encoded) // 4096 * DEADLINE_MS["per_4096_bytes"])`.
- Consumes: Task 3's `encode_request` / `decode_response`,
  `_successor_contracts.LIMITS/DEADLINE_MS/PARSER_VERSION`.

- [ ] **Step 1: Write the failing fault-injection tests (gate 9 core)**

Fake helpers are tiny Python scripts written to `tmp_path` and `chmod +x`-ed
(`#!/usr/bin/env python3` shebang; invoke via the script path directly). Write one test per
row; each asserts `BatchFailure` is raised with the exact `code` (or success for the happy
path). Use the `single-certified.json` conformance pair as the golden request/response and
its recorded `helper_version` placeholder as `expected_helper_version`:

| fake helper behavior | expected outcome |
| --- | --- |
| reads stdin fully, writes the golden response bytes, exit 0 | results equal the decoded fixture |
| exits 3 without output | `exit_nonzero` |
| writes the golden response then `sys.exit(1)` | `exit_nonzero` (exit 0 required even with valid-looking output) |
| sleeps 30s (use `deadline_ms_override=300`) | `timeout`, child reaped (no zombie: `process.poll()` is not None after) |
| floods stdout with `LIMITS["stdout_cap_bytes"] + 1` bytes | `output_cap_exceeded` |
| writes the golden response plus trailing garbage, exit 0 | `malformed_output` |
| never reads stdin, exits 0 immediately (request larger than the pipe buffer: use a batch with one ~1 MiB source so the writer hits a broken pipe) | `transport_failure` or `malformed_output`, never a hang and never an unhandled `BrokenPipeError` |
| writes the golden response with a mutated `helper_version`, exit 0 | `helper_identity_mismatch` |
| writes the golden response with a mutated `parser_version`, exit 0 | `parser_pin_mismatch` |
| nonexistent helper path | `spawn_failure` |
| request over the aggregate cap (no helper spawned; assert with a huge synthetic batch against a fake that would succeed, and assert the fake never ran via a touch-file) | `request_cap_exceeded` |

Also: `test_stderr_is_captured_and_bounded` (fake helper writes 100 KiB to stderr then a
valid response; success is still returned and no more than
`LIMITS["stderr_capture_cap_bytes"]` stderr bytes are retained on the supervisor's private
debug attribute), and `test_deadline_formula` (pure: compute the deadline for 3 sources and
a known encoded size and compare against the hand-computed value; expose the formula as a
pure function `batch_deadline_ms(source_count: int, encoded_byte_length: int) -> int`).
Keep every fake helper under one second of runtime.

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

`subprocess.Popen([str(helper_path)], stdin=PIPE, stdout=PIPE, stderr=PIPE,
close_fds=True, cwd=<dedicated neutral dir>, env=<minimal>)`. Requirements:

- Neutral cwd: a `tempfile.mkdtemp()` per batch, removed in a `finally`.
- Minimal env: `{"PATH": ""}` on POSIX (document inline that Windows would need
  `SystemRoot`; this plan targets the local Linux gates, PR B revisits).
- Never `communicate()`. One writer thread feeds stdin in chunks and closes it, swallowing
  `BrokenPipeError`/`OSError` into a flag; two reader threads drain stdout and stderr with
  byte caps (stop reading past the cap and record the overflow).
- A `time.monotonic()` deadline from `batch_deadline_ms` (or the override). On breach:
  `kill()`, bounded drain, mandatory `wait()`. POSIX process-group kill
  (`start_new_session=True` + `os.killpg`) as defense in depth, documented as such (S4.4:
  no process-tree containment claim).
- Every exit path reaps the child (`wait()` in `finally`).
- Results publish only after: EOF on stdout, exit code 0, no cap overflow, and full
  `decode_response` validation. Any earlier failure raises the mapped `BatchFailure`;
  writer-side pipe failures map to `transport_failure` unless the child already produced a
  decodable failure signal (exit nonzero wins as `exit_nonzero`).
- Bounded stderr is retained on the exception as a private attribute for debugging and
  never propagated into user-facing text (S4.4).

- [ ] **Step 4: Run the file green** (real threading paths, all fake helpers).

- [ ] **Step 5: Commit**

```bash
git add src/doc_lattice/github_ci/helper_supervisor.py tests/test_github_ci_helper_supervisor.py
git commit -m "feat: add the helper batch supervisor"
```

---

### Task 5: helper_locator.py (package-owned lookup)

**Files:**
- Create: `src/doc_lattice/github_ci/helper_locator.py`
- Test: `tests/test_github_ci_helper_locator.py`

**Interfaces:**
- Produces: `HelperUnavailable(ProjectError)` with `code` `"missing_binary"` or
  `"unsupported_platform"`.
- Produces: `locate_helper(*, package_root: Path | None = None) -> Path` resolving the
  bundled binary from package data for the current platform, never `PATH` (S2). The wheel
  layout proposed for PR B and used by Plan C's candidate wheels:
  `src/doc_lattice/_helper/doc-lattice-shell-parser-<triple>` (plus `.exe` on Windows),
  with `<triple>` one of the five `CP/pins/platform_matrix.json` triples. `package_root`
  defaults to the installed `doc_lattice` package directory (via
  `importlib.resources.files("doc_lattice")`); the keyword is the unit-test seam. Plan C's
  sdist degradation harness calls the real default path (never a merely injected
  nonexistent path).
- Produces: `current_platform_triple() -> str` mapping
  `(platform.system(), platform.machine())` to the frozen triples
  (`Linux/x86_64 -> x86_64-unknown-linux-gnu`, `Linux/aarch64 -> aarch64-unknown-linux-gnu`,
  `Darwin/x86_64 -> x86_64-apple-darwin`, `Darwin/arm64 -> aarch64-apple-darwin`,
  `Windows/AMD64 -> x86_64-pc-windows-msvc`), raising `HelperUnavailable
  ("unsupported_platform")` for anything else.

- [ ] **Step 1: Write the failing tests**: platform mapping for all five pairs plus an
unsupported pair (monkeypatch `platform.system`/`platform.machine`); `locate_helper` with a
`package_root` `tmp_path` containing a fake `_helper/doc-lattice-shell-parser-<triple>`
file returns that exact path; an empty `package_root` raises `HelperUnavailable` with code
`missing_binary`; an unsupported platform raises before any filesystem access.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** (pure logic plus one `Path.is_file()` probe; no `PATH` search,
no environment reads).
- [ ] **Step 4: Run green.**
- [ ] **Step 5: Commit** `feat: add the package-owned helper locator`

```bash
git add src/doc_lattice/github_ci/helper_locator.py tests/test_github_ci_helper_locator.py
git commit -m "feat: add the package-owned helper locator"
```

---

### Task 6: launcher_policy.py revision (ScanWord, precheck stage, dispatcher, look-alike)

**Files:**
- Modify: `src/doc_lattice/github_ci/launcher_policy.py`
- Test: `tests/test_github_ci_launcher_policy.py` (extend; every existing test stays green)

**Interfaces:**
- Produces: `ScanWord` revised to
  `ScanWord(text: str | None, start: int, end: int, unstable: bool, single: bool = True,
  raw_segment: str | None = None)`. Field order keeps every existing positional
  construction valid; `text` becomes optional (S5.2). The certifier upholds two invariants
  the module documents: `text is None implies unstable is True`, and
  `text is not None implies single is True` (wire-validated in Task 3).
- Produces: `ScanAssignment(name: str, value_known: bool, start: int, end: int)`.
- Produces: `PolicyRefusal(code: str, offset: int)` where `code` is a key of
  `_successor_contracts.REASON_CATEGORIES` (the certifier and audit map codes to
  categories and stable reasons; `resolve_command`'s legacy `CandidateResolution` refusals
  map through unchanged category names).
- Produces: `CommandEvaluation(invocation: tuple[str, bool] | None,
  refusals: tuple[PolicyRefusal, ...], work: int)`.
- Produces: `evaluate_command(assignments: Sequence[ScanAssignment],
  words: Sequence[ScanWord]) -> CommandEvaluation`, the named precheck stage ahead of
  `resolve_command` (S5.2), implementing the frozen pre-policy matrix
  (`CP/tables/pre_policy_matrix.json`), the S6.1 dispatcher rule
  (`CP/tables/dispatcher_grammar.json`), and the S6.3 look-alike rule, in the frozen
  precedence order (`CP/tables/precedence.json`). `work` is one unit per `ScanWord` and
  per `ScanAssignment` examined (the frozen `limits.json` work-unit definition).
- `resolve_command` keeps its exact public signature and behavior for legacy callers
  (`direct_marker_scanner.py`); internal accesses to `word.text` gain `None`-narrowing
  guards that fail closed (`policy-unresolvable` at the word start) so `ty` stays green.

- [ ] **Step 1: Write the failing tests from the frozen artifacts**

Extend `tests/test_github_ci_launcher_policy.py` with an `evaluate_command` section. Build
`ScanWord`/`ScanAssignment` sequences by hand mirroring what the certifier will emit, and
assert exact `(invocation, refusal codes, offsets)`. Required cases, each traceable to a
frozen row:

```python
def _word(text, start, end, *, single=True, raw=None):
    unstable = text is None
    return ScanWord(text, start, end, unstable, single, raw if raw is not None else text)
```

1. Pre-policy matrix (`CP/tables/pre_policy_matrix.json`):
   - assignments-only: `evaluate_command([ScanAssignment("X", True, 0, 3)], [])` ->
     `invocation=None`, no refusals.
   - assignments-plus-argv-literal: literal `X=1` prefix plus
     `doc-lattice check` -> `invocation=("check", False)`, no refusals.
   - assignments-plus-argv-dynamic: `VAR` with `value_known=False` at start 0 plus
     `doc-lattice check` -> refusal `("assignment-prefix", 0)` AND
     `invocation=("check", False)` (retained argv, amendment B).
   - first-word-unknown: head `_word(None, 0, 3)` -> single refusal
     `("unstable-first-word", 0)`, `invocation=None`.
   - multi-cardinality-word: `doc-lattice check $EXTRA-as-single=False` -> refusal
     `("splitting-unsafe-word", <that word's start>)`, `invocation=None`.
2. Dispatcher rows (all eight `CP/corpus/new_fixtures.json` `dispatcher` family sources,
   hand-tokenized): `bash -c 'doc-lattice linear'` -> `dispatcher-payload`;
   `eval` + `_word(None, ..., raw='"doc-lattice $X"')` -> `dispatcher-payload` (raw-segment
   marker); `sh -lc '...'` cluster -> `dispatcher-payload`; `bash -c 'echo ok' doc-lattice`
   -> `dispatcher-payload` (pinned false positive); `bash --norc -c '...'` ->
   `dispatcher-payload`; `bash $OPT 'doc-lattice lint'` with `$OPT` as
   `_word(None, 5, 9, single=False, raw="$OPT")` -> `dispatcher-selector-unresolved` at 5
   (THE PINNED ORDERING OBLIGATION: this must win over `splitting-unsafe-word`);
   `bash -c 'echo hello'` with no marker-bearing word -> `invocation=None`, NO refusals
   (marker-free dispatch falls through to not-candidate); `source ./doc-lattice-env.sh` ->
   `dispatcher-payload`.
3. Look-alike rows (`look_alike` family): `doc_lattice check` ->
   `marker-head-look-alike` at 0; `./doc.lattice-wrapper run` -> `marker-head-look-alike`;
   `doc-lattice.exe check` -> `invocation=("check", False)`; `DOC-LATTICE lint` ->
   `invocation=("lint", False)`.
4. Template-shaped rows (offset oracle, scan-text coordinates here; projection is Task 8's
   job): head `doc-lattice` then the sentinel word
   `_word(SCRIPT_SENTINEL, 12, 34, raw="{0}")` -> refusal `("policy-unresolvable", 12)`
   (unknown subcommand via `resolve_command`); `bash` + `_word(None, 5, 9, single=False,
   raw="$PRE")` + sentinel + `doc-lattice` -> `("dispatcher-selector-unresolved", 5)`;
   `bash -e` + sentinel + `_word(None, ..., single=False, raw="$EXTRA")` -> the -e cluster
   has no `c` and the sentinel operand ends option scanning, so NOT a dispatcher; generic
   cardinality fires: `("splitting-unsafe-word", <$EXTRA start>)`.
5. Resolution passthrough: every historical `resolve_command` behavior reachable through
   `evaluate_command` (e.g. `uvx doc-lattice lint` resolves; `env doc-lattice check`
   refuses `policy-unresolvable`), and a refused resolution surfaces as
   `PolicyRefusal("policy-unresolvable", offset)` with `invocation=None`.
6. Work accounting: `evaluate_command` returns `work == len(words) + len(assignments)`.

- [ ] **Step 2: Run to verify failure** (new names undefined). Also run the existing file
first and record its pass count; it must not drop.

- [ ] **Step 3: Implement**

The precedence chain (`CP/tables/precedence.json`) is
`doc-lattice-or-launcher-resolution, dispatcher-payload, marker-head-look-alike,
off-floor-wrapper, not-candidate`; the pre-policy matrix runs where word knowledge gates
each step. Exact staging inside `evaluate_command`:

```python
def evaluate_command(assignments, words):
    work = len(words) + len(assignments)
    refusals: list[PolicyRefusal] = []
    if not words:
        return CommandEvaluation(None, (), work)
    dynamic = next((a for a in assignments if not a.value_known), None)
    if dynamic is not None:
        refusals.append(PolicyRefusal("assignment-prefix", dynamic.start))
    head = words[0]
    if head.text is None:
        refusals.append(PolicyRefusal("unstable-first-word", head.start))
        return CommandEvaluation(None, tuple(refusals), work)
    dispatcher = _dispatcher_refusal(words)          # BEFORE generic cardinality (pinned)
    if dispatcher is not None:
        refusals.append(dispatcher)
        return CommandEvaluation(None, tuple(refusals), work)
    unsafe = next((w for w in words if not w.single), None)
    if unsafe is not None:
        refusals.append(PolicyRefusal("splitting-unsafe-word", unsafe.start))
        return CommandEvaluation(None, tuple(refusals), work)
    resolution = resolve_command(tuple(words))
    if resolution.kind == "resolved":
        return CommandEvaluation(resolution.invocation, tuple(refusals), work)
    if resolution.kind == "refused":
        refusals.append(PolicyRefusal(resolution.reason_category, resolution.offset))
        return CommandEvaluation(None, tuple(refusals), work)
    if _head_is_marker_look_alike(head):
        refusals.append(PolicyRefusal("marker-head-look-alike", head.start))
        return CommandEvaluation(None, tuple(refusals), work)
    return CommandEvaluation(None, tuple(refusals), work)
```

(`CandidateResolution.reason_category` values are also reason-code keys, so the append is
type-clean; assert that with a comment referencing `REASON_CATEGORIES`.)

`_dispatcher_refusal(words) -> PolicyRefusal | None` implements S6.1 against
`DISPATCHER_PLAIN_HEADS` / `DISPATCHER_SHELL_HEADS` from `_successor_contracts`:

- Head normalization: basename after `/`-stripping, casefolded, optional `.exe` suffix
  stripped (`c_option_grammar.exe_and_case`).
- Marker-bearing check: `word_carries_marker(word.text, word.raw_segment)` over ALL words
  (argv-wide rule). If no word carries a marker, return None (marker-free dispatch never
  fires the rule; `marker-free-dispatch` fixture).
- Plain head (`eval`, `source`, `.`) plus any marker word: `dispatcher-payload` anchored at
  the first marker-carrying word's start.
- Shell head (`bash`, `sh`, `dash`, `zsh`) plus any marker word: scan words after the head
  as the selector region. A word with `text is None` encountered before `-c` is
  established: `dispatcher-selector-unresolved` at that word (this is what outruns the
  generic cardinality refusal). A known word: `--` ends option parsing (no `-c` after it
  counts); a short-option cluster (leading single `-`, no `=`) containing `c` establishes
  `-c` -> `dispatcher-payload` at the first marker word; any other option-like word
  (leading `-`) is skipped per `value_options_before_c`; the first non-option word ends the
  selector region. No `-c` established by region end: return None (not a dispatcher).

`_head_is_marker_look_alike(head)` (S6.3): known authored head only:
`word_carries_marker(head.text, head.raw_segment)`.

`resolve_command` internals: after each existing `word.unstable` guard, narrow
`word.text` with a fail-closed `if text is None: return _refused(word.start)` so the
`str | None` type checks; behavior for all legacy inputs (text always `str`) is unchanged,
which the untouched existing test suite proves.

- [ ] **Step 4: Run the full file green** plus the legacy consumers:

Run: `env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest tests/test_github_ci_launcher_policy.py tests/test_github_ci_direct_marker_scanner.py -q --no-cov`
Then `uv run --group dev ty check src` and the boundaries script. Then the FIRST full-suite
milestone: `env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest -q`
(expect the pre-plan 2,689 plus every test added in Tasks 1-6; zero failures).

- [ ] **Step 5: Commit**

```bash
git add src/doc_lattice/github_ci/launcher_policy.py tests/test_github_ci_launcher_policy.py
git commit -m "feat: add the successor precheck stage to launcher policy"
```

---

### Task 7: shell_composition.py (D1 + D2 + D6 collection with projection)

**Files:**
- Create: `src/doc_lattice/github_ci/shell_composition.py`
- Test: `tests/test_github_ci_shell_composition.py`

**Interfaces:**
- Produces (all frozen dataclasses):
  - `SourceRef(path: str, job_id: str, step_index: int, source_kind: AuditSourceKind)`
  - `ProjectionSegment(scan_start: int, scan_end: int, raw_start: int, raw_end: int,
    synthetic: bool)` (a sentinel occurrence is `synthetic=True`; its raw span is the
    authored `{0}`)
  - `CollectedSource(ref: SourceRef, raw_text: str, scan_text: str,
    projection: tuple[ProjectionSegment, ...])` with methods
    `project_index(scan_index: int) -> int` (a scan-text char index to a raw-text char
    index; inside a synthetic segment it maps to the segment's `raw_start`, i.e. the `{0}`
    brace, per S5.2) and `project_span(start: int, end: int) -> tuple[int, int]` (start via
    `project_index`; an `end` inside a synthetic segment maps to that segment's `raw_end`,
    so a whole-sentinel word's raw segment is exactly `"{0}"`)
  - `CompositionOutcome(sources: tuple[CollectedSource, ...],
    diagnostics: tuple[AuditDiagnostic, ...], not_applicable: tuple[SourceRef, ...])`
- Produces: `substitute_template(template: str) -> tuple[str, tuple[ProjectionSegment, ...]]`
  replacing every `SCRIPT_PLACEHOLDER` occurrence with `SCRIPT_SENTINEL` and recording the
  segment map (identity segments between occurrences; run bodies use an empty projection,
  meaning identity).
- Produces: `compose_workflow(document: WorkflowDocument) -> CompositionOutcome`
  implementing D1 pruning (`reachability.job_is_pr_reachable` with
  `audit.PR_EVENTS`, a public constant) and the D6 table exactly as
  `tests/github_ci_evaluation_harness.py::evaluate_workflow` does today (promote, do not
  import, the harness logic; the harness file stays untouched):
  marker facts on AUTHORED text (`has_direct_marker(shell)` / `has_direct_marker(run)`);
  a marker-bearing template is always collected (kind `shell_template`, substituted
  scan_text) and additionally diagnosed `UNSUPPORTED_EXECUTION_SEMANTICS` when the body
  class is not BASH; a marker-bearing body is collected only under BASH semantics, else
  diagnosed; marker-free sources land in `not_applicable`. The body-class rule (BASH /
  NON_BASH / UNKNOWN) is re-owned here: a private `_supports_bash_run_body(shell)` and
  `_BASH_DEFAULT_RUNNERS` reimplemented to match `audit.py`'s frozen D6 behavior
  byte-for-byte (copy the semantics, cite the PR B unification in the docstring).
- Produces: `collection_order(ref: SourceRef) -> tuple` implementing the frozen S4.1 batch
  ordering key `(path, job_id, step_index, kind_rank)` with `shell_template` ranked before
  `run_body` (template before body).

- [ ] **Step 1: Write the failing tests**

`tests/test_github_ci_shell_composition.py`, three groups:

1. Projection algebra (pure): `substitute_template("bash $PRE {0} doc-lattice")` yields
   scan text `bash $PRE __doc_lattice_script__ doc-lattice`; `project_index` is identity
   before the sentinel (index 5 -> 5), maps every in-sentinel index to 10 (the `{0}`
   brace), and shifts indices after it by `len(sentinel) - 3`; `project_span` over the
   whole sentinel word returns the `{0}` span so `raw_text[a:b] == "{0}"`; a template with
   two `{0}` occurrences round-trips both. A run body (`projection=()`) projects
   identically.
2. D6 truth table over synthetic `WorkflowDocument`s (build minimal documents with the
   `model.py` constructors, mirroring the harness's existing patterns): marker-bearing
   bash-class body -> one `run_body` CollectedSource; marker-bearing non-bash body -> zero
   sources, one `UNSUPPORTED_EXECUTION_SEMANTICS` diagnostic; marker-bearing template with
   non-bash body -> template collected AND diagnosed; marker-free step -> `not_applicable`
   ref only; D1-unreachable job -> nothing at all; `UNKNOWN` body class treated as
   non-BASH for bodies (matching the harness).
3. Ordering: `collection_order` sorts a template ref ahead of its sibling body ref and
   sorts by path/job/step first.
4. Cross-check against the harness on a real document: parse
   `.github/workflows/ci.yml` with `parse_workflow` and assert `compose_workflow`'s
   pruned/collected/diagnosed sets equal `evaluate_workflow`'s view (pruned job ids match;
   the set of `(job_id, step_index, source_kind)` collected equals the harness's scanned
   set; diagnostics codes match), proving the promotion is faithful.

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** per the interface block. Keep every function pure
(`WorkflowDocument` in, tuples out; no I/O).
- [ ] **Step 4: Run the file green; `ty` and Ruff clean.**
- [ ] **Step 5: Commit**

```bash
git add src/doc_lattice/github_ci/shell_composition.py tests/test_github_ci_shell_composition.py
git commit -m "feat: add the D6 shell composition and sentinel projection"
```

---

### Task 8: syntax_certifier.py (translation and offset projection)

**Files:**
- Create: `src/doc_lattice/github_ci/syntax_certifier.py`
- Test: `tests/test_github_ci_syntax_certifier.py`

**Interfaces:**
- Produces (frozen dataclasses):
  - `CertifiedSite(ordinal: int, start: int, end: int,
    assignments: tuple[ScanAssignment, ...], words: tuple[ScanWord, ...])` with every
    offset already a RAW-TEXT character index and every word carrying its
    `raw_segment` (S5.2)
  - `HelperRefusal(code: str, offset: int, scope: str)` (raw-text character offset;
    `scope` from `REASON_SCOPES`)
  - `CertifiedSource(ref: SourceRef, sites: tuple[CertifiedSite, ...],
    refusals: tuple[HelperRefusal, ...], work_units: int)`
- Produces: `certify_batch(helper_path: Path, sources: Sequence[CollectedSource], *,
  expected_helper_version: str, deadline_ms_override: int | None = None)
  -> tuple[CertifiedSource, ...]`:
  1. Sort by `collection_order`, assign ids `0..n-1`, keep the id-to-ref map private
     (S4.1: no attribution on the wire).
  2. A source whose `scan_text` exceeds `LIMITS["python_source_cap_chars"]` characters is
     never sent: it yields a synthetic `CertifiedSource` with one terminal
     `HelperRefusal("source-cap", 0, "terminal")` (the inherited Python character cap
     governs, S3.5).
  3. Remaining sources go through `helper_supervisor.run_batch` as ONE batch.
  4. Per result: build the byte-to-char index map for the source's `scan_text`
     (incremental UTF-8 walk); a wire byte offset that is not a char boundary or out of
     range raises `BatchFailure(..., "protocol_violation")` and invalidates the whole
     batch (S5.2 atomicity). Convert every span to scan-text char indices, then project to
     raw indices via `CollectedSource.project_index`/`project_span`.
  5. Map events: `command_site` -> `CertifiedSite` with
     `ScanAssignment(name, value_known, raw_start, raw_end)` per wire assignment and
     `ScanWord(text, raw_start, raw_end, unstable=(text is None), single,
     raw_segment=raw_text[raw_start:raw_end])` per wire word; `refusal` ->
     `HelperRefusal(code, raw_start, REASON_SCOPES[code])`; an unknown code raises
     `BatchFailure(..., "protocol_violation")`.
  6. `work_units` passes through from the wire (never zero-filled; the wire schema already
     guarantees presence).
- Translation-only: this module never applies markers, policy, or aggregation (S2).

- [ ] **Step 1: Write the failing tests**

Fake-helper driven (no Go): a `_fake_helper(tmp_path, response_bytes)` helper writes a
Python script that echoes canned bytes; responses are built with the Task 3 dataclass
shapes serialized by hand (reuse the conformance fixtures where they fit). Required cases:

1. Round trip: the `single-certified.json` request/response pair through
   `certify_batch` yields one `CertifiedSource` whose site words are
   `ScanWord("doc-lattice", 0, 11, False, True, "doc-lattice")` and
   `ScanWord("check", 12, 17, False, True, "check")` (identity projection).
2. Multibyte projection: source `echo "😀"; $X doc-lattice check` (a run body) with a
   hand-built response placing a refusal at byte 13 -> `HelperRefusal` offset 10
   (character index; this is the frozen `emoji-before-marker` arithmetic).
3. Template projection: the collected template `bash $PRE {0} doc-lattice` with a
   hand-built response containing a word spanning the sentinel bytes -> that
   `ScanWord.raw_segment == "{0}"`, and a refusal whose byte offset falls inside the
   sentinel projects to raw index 10, the `{0}` brace
   (`b0 a1 s2 h3 space4 dollar5 P6 R7 E8 space9 brace10`).
4. Ordering: two refs (template + body of the same step) are batched template-first and
   map back to the right refs regardless of input order.
5. Off-boundary span (byte offset pointing into the middle of the emoji) raises
   `BatchFailure` with code `protocol_violation`.
6. Over-character-cap source (a `1_048_577`-char ASCII string) yields the local
   `source-cap` refusal and the fake helper never runs (touch-file assertion).
7. Unknown refusal code in the response raises `protocol_violation`.

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** per the interface block.
- [ ] **Step 4: Run green; `ty`, boundaries, Ruff clean** (this module must NOT need
`typing.Any`; it consumes typed `WireResult`s).
- [ ] **Step 5: Commit**

```bash
git add src/doc_lattice/github_ci/syntax_certifier.py tests/test_github_ci_syntax_certifier.py
git commit -m "feat: add the translation-only syntax certifier"
```

---

### Task 9: successor_audit.py (D4 fold, D5 mapping, batch pipeline)

**Files:**
- Create: `src/doc_lattice/github_ci/successor_audit.py`
- Test: `tests/test_github_ci_successor_audit.py`

**Interfaces:**
- Produces: `scan_certified_source(certified: CertifiedSource) -> BlockScan`, the pure
  S5.3 fold: run `evaluate_command` per site in order; invocations accumulate
  monotonically; collect policy refusals (class `policy`) and helper refusals (class
  `syntax`); `work_charged = certified.work_units + sum(evaluation work)`;
  status `certified` when no refusals, else `uninspectable` with the winning refusal
  chosen by the FROZEN tie rule: earliest offset, then syntax-class over policy-class,
  then reason code as the final deterministic tie-break; `reason =
  STABLE_REASONS[code]`, `reason_category = REASON_CATEGORIES[code]`, `offset` = the
  winning refusal's raw offset. All retained invocations are always reported (S5.3).
- Produces: `scan_execution_sources(sources: Sequence[str], helper_path: Path, *,
  expected_helper_version: str) -> tuple[BlockScan, ...]`, the corpus/replay entry point:
  applies the D2 gate first (`has_direct_marker(raw)`; marker-free ->
  `BlockScan("not_applicable", (), None, None, None, 1)` without batching), wraps the rest
  as `run_body` CollectedSources with synthetic refs, one batch, one fold each.
- Produces: `SuccessorAuditOutcome(evaluations: tuple[SourceOutcome, ...],
  diagnostics: tuple[AuditDiagnostic, ...], invocations: tuple[tuple[str, bool], ...])`
  and `SourceOutcome(ref: SourceRef, scan: BlockScan)`.
- Produces: `audit_workflow_documents(documents: Sequence[WorkflowDocument],
  helper_path: Path, *, expected_helper_version: str) -> SuccessorAuditOutcome`:
  compose every document, gather all CollectedSources repo-wide, ONE batch, fold each
  source; every `uninspectable` scan becomes an `AuditDiagnostic(ref...,
  "UNINSPECTABLE_SOURCE", scan.reason, scan.offset)`; composition diagnostics pass
  through; diagnostics sort by `model.diagnostic_sort_key`; `invocations` is the ordered
  dedup of all certified-and-retained invocation pairs. A `BatchFailure` or
  `HelperUnavailable` is caught ONCE at this level and mapped to one
  `UNINSPECTABLE_SOURCE` diagnostic per batched source with full attribution,
  `offset=None`, and a stable owned reason string
  (`f"successor helper batch failed: {error.code}"`, never helper stderr), per S4.5.
  Exit-code behavior stays out (dormant; PR B wires the CLI).

- [ ] **Step 1: Write the failing tests**

Fake-helper and hand-built `CertifiedSource` driven (no Go):

1. Fold basics: one site resolving `("check", False)` -> certified BlockScan with that
   invocation and `work_charged == wire_work + site work`.
2. Retained argv: a site with a dynamic assignment refusal plus resolved argv ->
   uninspectable, `reason_category == "assignment-prefix"`, invocations retained
   (the `multibyte-assignment-prefix` shape).
3. Tie rule: a syntax refusal and a policy refusal at the same offset -> syntax wins; two
   syntax refusals at different offsets -> earliest wins; equal offset and class -> lower
   code string wins. Assert `reason == STABLE_REASONS[winning code]`.
4. Terminal ordering: a source with a site then a terminal `syntax-error` refusal ->
   uninspectable at the refusal offset with the site's invocation retained (the canonical
   S3.1 shape).
5. D2 gate: `scan_execution_sources(["echo hello"], ...)` -> `not_applicable` and the fake
   helper never runs; a marker-bearing source runs and folds.
6. Batch failure mapping: a fake helper that exits nonzero under
   `audit_workflow_documents` -> one `UNINSPECTABLE_SOURCE` diagnostic per collected
   source, `offset=None`, reason mentioning `exit_nonzero`, zero invocations.
7. Workflow shape: a synthetic two-job document (one PR-reachable marker-bearing bash
   body, one unreachable) with a fake helper returning a certified site ->
   `invocations == (("check", False),)`, no diagnostics, evaluation refs correct.

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** per the interface block (pure fold; the only I/O is via the
supervisor call inside `certify_batch`).
- [ ] **Step 4: Run green; then the SECOND full-suite milestone** (full pytest, Ruff
check + format check, `ty`, boundaries, version sync) before the gate work starts.
- [ ] **Step 5: Commit**

```bash
git add src/doc_lattice/github_ci/successor_audit.py tests/test_github_ci_successor_audit.py
git commit -m "feat: add the dormant successor audit pipeline"
```

---

### Task 10: Gate harness and gates 1 + 8 (corpus, families, offset oracle)

**Files:**
- Modify: `tests/conftest.py` (add the session-scoped build fixture ONLY; do not touch
  `lattice_dir`)
- Create: `tests/github_ci_successor_harness.py`
- Create: `tests/test_github_ci_successor_gates.py` (gates 1 and 8 in this task)

**Interfaces:**
- Produces (`tests/conftest.py`):

```python
GO_TOOLCHAIN = Path("/usr/local/go/bin/go")


@pytest.fixture(scope="session")
def successor_helper(tmp_path_factory):
    """Build the successor helper once per session; skip when Go is unavailable."""
    if not GO_TOOLCHAIN.exists():
        pytest.skip("pinned Go toolchain not installed")
    out = tmp_path_factory.mktemp("successor-helper") / "doc-lattice-shell-parser"
    subprocess.run(
        [str(REPO / "scripts" / "build_successor_helper.sh"), str(out)],
        check=True,
        capture_output=True,
    )
    return out
```

  plus `successor_helper_version` (session fixture running
  `scripts/check_helper_digest.py` via `sys.executable` and returning the 64-hex digest,
  which IS the expected `helper_version` of a wrapper-built binary).
- Produces (`tests/github_ci_successor_harness.py`): checkpoint loaders
  (`load_acceptance_labels()`, `load_new_fixtures()`, `load_tier(name)`,
  `load_legacy_normalization()`), `scan_source(source, helper, version) -> BlockScan`
  (wrapping `successor_audit.scan_execution_sources` for one source), and
  `assert_tuple(scan, expected_status, expected_invocations, reason_category)` used by
  every tier gate (compares exactly the frozen tuple; on `uninspectable` also the
  category).

- [ ] **Step 1: Write the harness and the failing gate tests**

Gate 1 (corpus): parametrize over all 87 `CP/corpus/acceptance_labels.json` cases (ids from
`description`); for each, `scan_source(case["source"], ...)` and assert the frozen tuple:
label `must-certify` -> status `certified` with `expected_invocations`; label
`intentional-exit-2` -> status `uninspectable` with `expected_invocations` and
`reason_category`; label `outside-direct-marker-contract` -> status `not_applicable`.
Then parametrize the `new_fixtures.json` families the same way: `dispatcher` (8),
`look_alike` (4), `heredoc_guard` (3, additionally asserting the `benchmark-false-safe`
row's `forbidden_outcome`: never certified-with-zero-events), `malformed_tail` (3),
`stmtsseq` (1). The `encoder_composition` row asserts `encode_request` on the boundary
fixture's source stays under the aggregate cap and the scan is `not_applicable`
(marker-free astral source). Template-flagged rows (`"template": true`) build a
`CollectedSource` via `substitute_template` and run through `certify_batch` +
`scan_certified_source` instead of the bare-source path.

Gate 8 (offset oracle): parametrize the 7 `offset_oracle` rows; assert
`scan.offset == expected_refusal_raw_index` and `scan.reason_category == reason_category`;
rows carrying `expected_invocations` assert those too.

- [ ] **Step 2: Run to verify the gates fail or pass honestly**

Run: `env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest tests/test_github_ci_successor_gates.py -q --no-cov -x`

This is the first contact between the full pipeline and the frozen corpus. Fix real
defects in Tasks 6-9 modules until green. THE FIXTURES ARE GROUND TRUTH: if a fixture and
the implementation cannot be reconciled without a checkpoint edit, STOP and escalate to
Rick (Global Constraints); never edit the checkpoint, never special-case a fixture id in
production code.

- [ ] **Step 3: Run the sibling suites for regressions**
(`tests/test_github_ci_launcher_policy.py`, `tests/test_github_ci_successor_audit.py`,
`tests/test_successor_checkpoint.py`).

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/github_ci_successor_harness.py tests/test_github_ci_successor_gates.py
git commit -m "test: bring successor gates 1 and 8 green against the frozen corpus"
```

---

### Task 11: Gates 2 through 6 (replay and tiers)

**Files:**
- Modify: `tests/test_github_ci_successor_gates.py` (append)
- Modify: `tests/github_ci_successor_harness.py` (append loaders/classifier)

**Interfaces:**
- Produces: `classify_successor_divergence(entry: dict, scan: BlockScan) -> str` in the
  harness, the S6.4 comparison: statuses map `complete -> certified`,
  `incomplete -> uninspectable`. Classes:
  - `identical`: same mapped status, same invocation tuples, and (when both incomplete)
    `scan.reason_category == entry["reason_category"]`.
  - `outside-direct-marker`: `scan.status == "not_applicable"` (D2-dropped baseline rows).
  - `intentional-exit-2`: baseline complete, successor uninspectable (fail-closed
    direction; never false-safe).
  - `old-incomplete-new-certified`: baseline incomplete, successor certified (the
    successor traverses more by design; gate 2 reports the count).
  - `legacy-only-reason`: both incomplete and `entry["reason_category"]` is in
    `legacy_normalization["legacy_only_categories"]` (no successor equivalent exists).
  - `unexplained`: anything else. Gate 2 requires ZERO of these.

- [ ] **Step 1: Write the failing gate tests**

Gate 2 (replay): iterate `legacy_normalization["entries"]` (580) zipped with the D3
`replay_inventory.json` sources by index (`entries[i]` normalizes `inventory["entries"][i]`;
assert the ids line up). Batch all marker-bearing sources through
`scan_execution_sources` in inventory order (ONE batch; this is also a soak of the 4,096
batch cap handling if the marker-bearing count exceeds it: split into successive batches
of at most `LIMITS["max_sources_per_batch"]`). Classify every pair; assert
`counts["unexplained"] == 0`; assert no entry classified `identical`/`intentional-exit-2`
lost an invocation the baseline had while certifying (explicit zero-false-safe check:
never `scan.status == "certified"` with `set(entry invocations) - set(scan invocations)`
non-empty); print the class counts into the assertion message for the evidence record.

Gate 3 (tier 1): render the managed workflows exactly as
`CP/tiers/tier1_expected.json["workflows"]` derives them (`doc_lattice.github_ci.render`;
mirror the existing harness/test usage of the renderer for owner/repo/version inputs);
parse each rendered text with `parse_workflow`; run `audit_workflow_documents` with the
real helper; assert `outcome.invocations == tuple(tuple(f) for f in tier1["findings"])`
and zero diagnostics.

Gate 4 (tier 2): parse every checked-in `.github/workflows/*.yml`; for the PR-triggered
ones assert against `tier2_expected` per workflow: pruned jobs, reachable steps (from
composition), `marker_gated_sources` and `batched_sources` (both empty today), zero
findings, zero diagnostics.

Gate 5 (tier 3A): 13 cases from `CP/tiers/tier3a_expected.json` via `scan_source`,
asserting each `(expected_status, expected_invocations)` tuple.

Gate 6 (tier 3B): for the 20 fixtures, extract run blocks with the existing
`github_ci_evaluation_harness.tier3b_run_block`, scan, assert each expected tuple, and
assert the budget arithmetic: `statuses.count("uninspectable") <= 2`, zero false-positive
(no fixture uninspectable whose expectation is certified), zero false-safe (no fixture
certified-with-different-invocations where the expectation is uninspectable or richer).

- [ ] **Step 2: Run and iterate to green** (same STOP rule as Task 10; in particular a
gate 2 `unexplained` divergence is an escalation, not a classifier tweak, unless the
classifier itself misreads the frozen artifact).

- [ ] **Step 3: Commit**

```bash
git add tests/test_github_ci_successor_gates.py tests/github_ci_successor_harness.py
git commit -m "test: bring successor gates 2 through 6 green"
```

---

### Task 12: Gates 7, 9 (real-binary half), and 10

**Files:**
- Modify: `tests/test_github_ci_successor_gates.py` (append)

- [ ] **Step 1: Gate 10 (cross-language conformance)**

For every `CP/protocol/conformance/*.json`: run the built helper as a subprocess with the
fixture's request bytes (canonical: re-encode with `encode_request`) on stdin; assert exit
0; assert stdout equals the byte-exact expected response, computed as
`json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode()` with the
fixture's `helper_version` placeholder replaced by the session digest (the Go marshaler's
field order matches the fixture key order; a mismatch here is a real finding, escalate);
then `decode_response` the stdout with the digest and `PARSER_VERSION` and assert it
round-trips. For every `negative/*.json` and `negative/*.bin`: pipe the raw bytes into the
helper and assert exit code 2 with empty stdout; ALSO feed each response-shaped negative
through `decode_response` and assert `HelperProtocolError` (both decoders reject, S4.2
symmetry). For `boundary/source-count-at-limit.json`: run through `run_batch` with the
real helper and assert 4,096 results; for `boundary/max-length-four-byte-source.json`:
encode, run, assert one result (accepted at limit).

- [ ] **Step 2: Gate 9 completion (real-binary adversarial)**

Append: `run_batch` against the real helper with a WRONG `expected_helper_version` raises
`helper_identity_mismatch` (proves the identity tripwire end to end); a request built from
4,097 sources raises `request_cap_exceeded` before spawn; the Task 4 fake-helper suite is
cited in a comment as the remaining taxonomy coverage (gate 9 evidence = both).

- [ ] **Step 3: Gate 7 (differential oracles)**

Mirror `tests/test_github_ci_semantic_differential.py`'s oracle mechanics for the
successor over the frozen corpus:

- Pin checks first: `/bin/bash --version` contains `CP/pins/bash_pin.json["version"]`;
  `shfmt --version` equals `CP/pins/shfmt_pin.json["version"]` (skip the gate with an
  explicit `pytest.skip` naming the mismatch when either oracle is absent or
  version-mismatched; record that a skip here means gate 7 is NOT green).
- Syntax agreement (shfmt): for every corpus row (87 labels + families) whose successor
  outcome is `certified`, `shfmt --to-json --filename stdin.bash` must parse the source
  (exit 0); for every row whose winning refusal category is `syntax-error`, shfmt must
  reject it (nonzero) OR the row is one of the pinned parser-alignment reclassifications
  (the three heredoc-continuation rows in `CP/README.md`; list them by id in the test with
  the README citation). Zero false-safe direction: no source shfmt rejects may certify.
- Structural agreement: for every `must-certify` row with non-empty
  `expected_invocations`, extract the successor's certified site count and known first
  words (via `certify_batch` on the raw source) and compare against the shfmt typed-JSON
  `CallExpr` structure using a recursive analog of the existing
  `_shfmt_command_structure` (extended to recurse into `CmdSubst`; assert equal
  invocation-bearing command counts and equal first literals where the successor knows
  `text`).
- Bash oracle: for every certified row, `bash -n` (the pinned `/bin/bash`) accepts the
  source; the `benchmark-false-safe` heredoc row asserts the DIVERGENCE is fail-closed:
  bash accepts it, the successor refuses `parser-divergence-guard` (this is the guard's
  reason to exist; assert the refusal, not agreement).

- [ ] **Step 4: Run the complete gate file green**

Run: `env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest tests/test_github_ci_successor_gates.py -q --no-cov`
Expected: every gate 1-10 test passes on this machine (Go, bash, shfmt all present).

- [ ] **Step 5: Commit**

```bash
git add tests/test_github_ci_successor_gates.py
git commit -m "test: bring successor gates 7, 9, and 10 green"
```

---

### Task 13: Surface accounting, dormancy guard, ARCHITECTURE decision, final sweep

**Files:**
- Create: `tests/test_github_ci_successor_surface.py`
- Modify: every new `src/doc_lattice/github_ci/` module (add `__all__` where missing)
- Modify: `ARCHITECTURE.md` (one new decision entry)

- [ ] **Step 1: Write the failing surface tests**

`tests/test_github_ci_successor_surface.py`:

1. `test_all_declarations_are_valid` (S6.6): for each successor module
   (`_successor_contracts`, `direct_marker`, `helper_protocol_boundary`,
   `helper_supervisor`, `helper_locator`, `launcher_policy`, `shell_composition`,
   `syntax_certifier`, `successor_audit`): `__all__` exists, every listed name is an
   attribute, names are unique, and the intended cross-module exports used by this plan
   (`encode_request`, `decode_response`, `run_batch`, `BatchFailure`, `locate_helper`,
   `HelperUnavailable`, `evaluate_command`, `ScanWord`, `ScanAssignment`,
   `compose_workflow`, `substitute_template`, `certify_batch`,
   `scan_certified_source`, `scan_execution_sources`, `audit_workflow_documents`,
   `word_carries_marker`, `has_direct_marker`, `DIRECT_MARKER_RE`) are present in their
   owners' `__all__`.
2. `test_runtime_import_graph_is_untouched` (dormancy guard): parse
   `src/doc_lattice/github_ci/audit.py`, `src/doc_lattice/github_ci/shell_scanner.py`,
   and every module under `src/doc_lattice/cli/` with `ast`, collect all import targets,
   and assert none references the successor modules
   (`helper_protocol_boundary`, `helper_supervisor`, `helper_locator`,
   `shell_composition`, `syntax_certifier`, `successor_audit`, `_successor_contracts`).
   (`direct_marker` is exempt only via `direct_marker_scanner`'s relocation import, which
   is itself test-reachable only; assert `audit.py` does not import `direct_marker`
   directly.)

- [ ] **Step 2: Implement**: add `__all__` blocks; fix any surfaced import leak.

- [ ] **Step 3: ARCHITECTURE decision entry**

Add one decision to `ARCHITECTURE.md` following its existing format: the successor
engine's effect-ownership boundaries: `helper_protocol_boundary.py` owns raw helper JSON
(the `typing.Any` boundary), `helper_supervisor.py` owns the helper subprocess lifecycle,
`helper_locator.py` owns package-data resolution; all successor modules are dormant
(runtime import graph unchanged) pending the PR B decision record; link the spec document
and the checkpoint README rather than restating their contracts (CLAUDE.md single-owner
rule).

- [ ] **Step 4: Full handoff verification**

```bash
env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest -q
uv run --group dev ruff check src tests scripts
uv run --group dev ruff format --check src tests scripts
uv run --group dev ty check src
uv run --group dev python scripts/check_typing_boundaries.py src
uv run --group dev python scripts/check_version_sync.py
uv run --group dev python scripts/generate_successor_contracts.py --check
cd helper/doc-lattice-shell-parser && /usr/local/go/bin/go test ./... && cd ../..
```

Expected: full suite green (2,689 baseline plus all new tests, gates included), coverage
over the 80 percent floor, all checks clean, Go suite still green (nothing in this plan
touches the helper).

- [ ] **Step 5: Commit and hand off**

```bash
git add tests/test_github_ci_successor_surface.py ARCHITECTURE.md src/doc_lattice/github_ci/
git commit -m "test: pin the successor surface and dormancy guarantees"
```

Report to Rick: the head commit, the gate 1-10 status table (with the gate 2 divergence
class counts and the gate 6 indeterminate count against the 2/20 zero-headroom budget),
any escalations, and the reminder that Plan C (CI matrix, wheels, gates 11-14, evidence,
decision record) is next. Do not push; the branch stays local until Plan C opens the PR.

---

## Self-review notes

- Spec coverage: S2 modules -> Tasks 2-9 (one module each; `successor_audit` carries S4.5
  and S5.3; `helper_locator` S2/S7). S3.3 category domain -> Task 2. S4.1/S4.2 -> Task 3.
  S4.3 identity expectation -> Tasks 10/12 (digest fixture + mismatch test). S4.4 -> Task
  4. S5.1 -> Task 7. S5.2 -> Tasks 6/8. S6.1-S6.3 -> Task 6. S6.4 -> Task 11. S6.6 ->
  Task 13. Gates 1-10 -> Tasks 4 (9-core), 10, 11, 12. Gates 11-14 are Plan C by scope.
- The two owner-authorized checkpoint revisions (heredoc reclassification, conformance
  alignment) are already inside the frozen artifacts this plan consumes; no task
  re-litigates them, and the three reclassified heredoc rows are explicitly allowed in
  gate 7's shfmt disagreement handling.
- Type consistency spot checks: `ScanWord` field order preserves positional callers;
  `PolicyRefusal.code` (not category) feeds `REASON_CATEGORIES`/`STABLE_REASONS` lookups
  in Task 9; `CandidateResolution.reason_category` values double as reason codes (see the
  reason-code table: every command-local category string is also a code), so Task 6's
  passthrough append is well-typed; `decode_response` keyword names match between Tasks 3,
  4, and 8.
