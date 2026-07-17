# CI Audit and Publication Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all six verified CI audit, shell-wrapper, batch-consistency, and directory-durability review gaps.

**Architecture:** Extend the existing conservative static scanners with bounded grammar helpers that either resolve command position exactly or fail closed. Treat a mutable artifact batch as a locked read phase followed by an input-ordered write phase, and durably synchronize each descriptor-relative directory entry before descending into it.

**Tech Stack:** Python 3.13+, pytest, Bash, GNU Coreutils option semantics, POSIX directory descriptors and `fsync`, Ruff, `ty`, and `uv`.

---

### Task 1: Fail closed on computed secret keys

**Files:**
- Modify: `tests/test_github_ci_audit.py`
- Modify: `src/doc_lattice/github_ci/audit.py`
- Modify: `README.md`

- [ ] **Step 1: Write the failing computed-key regression**

Add these tests beside the existing secret-reference cases:

```python
def test_global_audit_fails_closed_on_computed_secret_key():
    document = _workflow(
        """\
on: issue_comment
jobs:
  unrelated:
    environment: doc-lattice-linear
    runs-on: ubuntu-latest
    steps:
      - env:
          TOKEN: ${{ secrets[format('DOC_LATTICE_LINEAR_API_{0}', 'KEY')] }}
        run: true
"""
    )

    assert _finding_codes(audit_global_workflows((document,))) == {
        "LINEAR_SECRET_REFERENCE"
    }


def test_global_audit_allows_static_unrelated_secret_index():
    document = _workflow(
        """\
on: push
jobs:
  unrelated:
    runs-on: ubuntu-latest
    steps:
      - env:
          TOKEN: ${{ secrets['RELEASE_TOKEN'] }}
        run: true
"""
    )

    assert audit_global_workflows((document,)) == ()
```

- [ ] **Step 2: Run RED**

Run:

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_audit.py::test_global_audit_fails_closed_on_computed_secret_key \
  tests/test_github_ci_audit.py::test_global_audit_allows_static_unrelated_secret_index -q
```

Expected: the computed-key case fails with no finding; the static unrelated case passes.

- [ ] **Step 3: Add narrow computed-index classification**

Add case-insensitive `secrets[` detection plus a static-key grammar:

```python
_SECRETS_INDEX_RE = re.compile(r"(?<![A-Za-z0-9_])secrets\s*\[\s*", re.IGNORECASE)
_STATIC_SECRET_INDEX_RE = re.compile(r"'[A-Za-z_][A-Za-z0-9_]*'\s*\]")


def _has_computed_secret_index(value: str) -> bool:
    return any(
        _STATIC_SECRET_INDEX_RE.match(value, match.end()) is None
        for match in _SECRETS_INDEX_RE.finditer(value)
    )
```

In `_has_linear_secret_reference`, treat `_has_computed_secret_index(scalar.value)` the same as an
exact protected-name match after preserving the canonical exact-slot exemption.

Update the README audit paragraph to state that computed `secrets[...]` keys fail closed because
their resolved name cannot be proven locally.

- [ ] **Step 4: Run GREEN and the surrounding audit suite**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_audit.py -q
```

Expected: PASS.

### Task 2: Parse GNU env command-position options

**Files:**
- Modify: `tests/test_github_ci_shell_scanner.py`
- Modify: `tests/test_github_ci_audit.py`
- Modify: `src/doc_lattice/github_ci/shell_scanner.py`

- [ ] **Step 1: Write failing direct and PR-audit regressions**

Add direct scanner cases covering the reported forms and the same root cause in other GNU options:

```python
@pytest.mark.parametrize(
    "script",
    [
        "env --uns NAME doc-lattice linear",
        "env --ch /tmp doc-lattice linear",
        "env --arg fake doc-lattice linear",
        "env -iu NAME doc-lattice linear",
        "env -iC /tmp doc-lattice linear",
        "env -ia fake doc-lattice linear",
    ],
)
def test_direct_doc_lattice_invocations_consumes_env_option_values(script):
    assert direct_doc_lattice_invocations(script) == LINEAR
```

Add a PR workflow parameterization for `env --uns NAME doc-lattice linear` and
`env -iu NAME doc-lattice reconcile --all`, expecting `PR_LINEAR_INVOCATION` and
`PR_MUTATING_RECONCILE` respectively. Add one test requiring an unsupported static `env` option to
raise `ConfigError` containing `unsupported env option`.

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_shell_scanner.py::test_direct_doc_lattice_invocations_consumes_env_option_values \
  tests/test_github_ci_audit.py -k 'env_option_values_on_pr' -q
```

Expected: the value-consuming forms return no invocation and the PR cases have no finding.

- [ ] **Step 3: Implement a bounded GNU env option resolver**

Define the supported long-option kinds and short-option sets:

```python
_ENV_LONG_OPTION_KINDS = {
    "--argv0": "required",
    "--block-signal": "optional",
    "--chdir": "required",
    "--debug": "flag",
    "--default-signal": "optional",
    "--help": "stop",
    "--ignore-environment": "flag",
    "--ignore-signal": "optional",
    "--list-signal-handling": "flag",
    "--null": "flag",
    "--split-string": "split",
    "--unset": "required",
    "--version": "stop",
}
_ENV_SHORT_FLAGS = frozenset({"0", "i", "v"})
_ENV_SHORT_REQUIRED = frozenset({"a", "C", "u"})
```

Add helpers that resolve exactly one long-option prefix, reject ambiguous/unknown prefixes, and
parse a short cluster left to right. A required option consumes an attached suffix or validates and
consumes the next static single-field word. A split-string option raises the existing incomplete
reason. A stop option returns the end of the words. An optional long argument is consumed only via
`=`. Mirror the static pending-value result in `_advance_prefix_env` so incremental tracking stays
aligned with `_skip_env_prefix`.

- [ ] **Step 4: Run GREEN and existing env/split-string coverage**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_shell_scanner.py tests/test_github_ci_audit.py -q
```

Expected: PASS, including split-string failure and option-terminator cases.

### Task 3: Parse clustered exec argv0 options

**Files:**
- Modify: `tests/test_github_ci_shell_scanner.py`
- Modify: `tests/test_github_ci_audit.py`
- Modify: `src/doc_lattice/github_ci/shell_scanner.py`

- [ ] **Step 1: Write failing direct and PR-audit regressions**

```python
@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("exec -ca fake doc-lattice linear", LINEAR),
        ("exec -la fake doc-lattice reconcile --all", RECONCILE),
        ("exec -cafake doc-lattice linear", LINEAR),
    ],
)
def test_direct_doc_lattice_invocations_consumes_clustered_exec_argv0(script, expected):
    assert direct_doc_lattice_invocations(script) == expected
```

Add PR workflow cases for `exec -ca fake doc-lattice linear` and
`exec -la fake doc-lattice reconcile --all`.

- [ ] **Step 2: Run RED**

Run the new direct test and PR parameterization with `pytest --no-cov -q`. Expected: no direct
invocations and no PR findings.

- [ ] **Step 3: Parse exec clusters**

Replace exact `-a` handling with a helper that accepts `c` and `l` until it reaches `a`. When `a`
has an attached suffix, that suffix is the `argv[0]` value; otherwise validate and consume the next
word. Reject an unknown option before `a`, preserve ambiguity for a dynamic separate value, and
mirror the pending-value result in `_advance_prefix_exec`.

- [ ] **Step 4: Run GREEN**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_shell_scanner.py tests/test_github_ci_audit.py -q
```

Expected: PASS.

### Task 4: Follow supported Bash builtin wrappers

**Files:**
- Modify: `tests/test_github_ci_shell_scanner.py`
- Modify: `tests/test_github_ci_audit.py`
- Modify: `src/doc_lattice/github_ci/shell_scanner.py`

- [ ] **Step 1: Write failing direct and PR-audit regressions**

```python
@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("builtin exec doc-lattice linear", LINEAR),
        ("builtin command doc-lattice reconcile --all", RECONCILE),
        ("builtin -- exec -ca fake doc-lattice linear", LINEAR),
        ("builtin builtin command doc-lattice linear", LINEAR),
    ],
)
def test_direct_doc_lattice_invocations_follows_supported_builtin_targets(script, expected):
    assert direct_doc_lattice_invocations(script) == expected
```

Add PR cases for the two reviewer examples. Add a dynamic-target case
`builtin "$TARGET" doc-lattice linear` that must fail closed on command-position expansion.

- [ ] **Step 2: Run RED**

Run the new direct, dynamic, and PR tests with `pytest --no-cov -q`. Expected: literal forms return
no invocation and the dynamic form does not fail closed.

- [ ] **Step 3: Add a supported builtin target resolver**

Add `_skip_builtin_wrapper` that consumes optional `--`, recursively exposes literal `builtin`,
`command`, or `exec`, and follows a dynamic or erasable target with `ambiguous=True`. Integrate it
before `command` and `exec` in `_skip_shell_prefixes`. Add `builtin` to incremental normal-prefix
tracking and route its supported targets into the existing wrapper modes.

- [ ] **Step 4: Run GREEN and scanner/audit suites**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_shell_scanner.py tests/test_github_ci_audit.py -q
```

Expected: PASS.

### Task 5: Prevalidate current artifacts under the publication lock

**Files:**
- Modify: `tests/test_github_ci_filesystem.py`
- Modify: `src/doc_lattice/github_ci/filesystem.py`

- [ ] **Step 1: Write the failing lock-time batch regression**

Create the first desired artifact, preflight the three-artifact create, then reorder the batch so a
create precedes the current entry. Monkeypatch `_claim_lock` to acquire the real lock and replace
the current artifact with old managed bytes before returning:

```python
def test_apply_prevalidates_current_artifacts_under_lock_before_mutating(
    tmp_path: Path,
    monkeypatch,
):
    desired = render_managed_artifacts("Guardantix/doc-lattice", "2.1.0")
    old = render_managed_artifacts("Guardantix/doc-lattice", "2.0.0")
    _write_artifacts(tmp_path, (desired[0],))
    planned = preflight_create(tmp_path, desired)
    changes = (planned[1], planned[0], planned[2])
    current_target = tmp_path / desired[0].relative_path
    real_claim = filesystem._claim_lock

    def _race_current_after_claim(fd: int) -> None:
        real_claim(fd)
        current_target.write_text(old[0].text, encoding="utf-8")

    monkeypatch.setattr(filesystem, "_claim_lock", _race_current_after_claim)

    with pytest.raises(ConfigError, match=r"changed after preflight.*doc-lattice\.yml"):
        apply_changes(changes)

    assert not (tmp_path / desired[1].relative_path).exists()
    assert not (tmp_path / desired[2].relative_path).exists()
```

- [ ] **Step 2: Run RED**

Run the new test with `pytest --no-cov -q`. Expected: no exception; both missing artifacts are
created around the stale current entry.

- [ ] **Step 3: Add a locked read phase**

Extract descriptor-relative unchanged-byte validation shared by current and replace changes. In
`apply_changes`, after locking, first iterate over every `current` change, authenticate its root,
resolve it, open its existing parent without creation, and require current bytes to equal its
preflight `before` bytes. Only after all current entries pass, iterate through non-current changes
in caller order and publish them. Reject a current change with absent `before` bytes.

- [ ] **Step 4: Run GREEN and filesystem/CLI publication coverage**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_filesystem.py tests/cli/test_init.py tests/cli/test_ci.py -q
```

Expected: PASS.

### Task 6: Synchronize parent directories after ancestor creation

**Files:**
- Modify: `tests/test_github_ci_filesystem.py`
- Modify: `src/doc_lattice/github_ci/filesystem.py`

- [ ] **Step 1: Write failing syscall-order and error regressions**

Wrap `filesystem.os.mkdir` and `filesystem.os.fsync`, record each successful mkdir's parent
`(st_dev, st_ino)` and each fsync descriptor identity, then assert the event immediately after each
mkdir is an fsync of the same parent. Store the original functions before monkeypatching and invoke
them from the wrappers.

Add a second test that makes the first `fsync` raise `OSError("synthetic parent sync failure")`,
expects `ConfigError` containing `cannot synchronize managed artifact parent`, asserts the
partial-state note is present, and asserts no canonical artifact file exists.

- [ ] **Step 2: Run RED**

Run the two new tests with `pytest --no-cov -q`. Expected: the first mkdir is followed by another
mkdir rather than parent fsync, and the error is reported later as artifact-write failure.

- [ ] **Step 3: Sync each containing directory before descent**

In `_ensure_locked_artifact_ancestor`, remember when initial lookup observed `FileNotFoundError`.
After `mkdir` or a `FileExistsError` race, stat and validate the resulting real directory, then:

```python
try:
    os.fsync(parent_fd)
except OSError as exc:
    raise _filesystem_error(
        "cannot synchronize managed artifact parent",
        exc,
        path=artifact_path,
    ) from exc
```

Return only after synchronization, so `_open_locked_artifact_parent` cannot open the child first.

- [ ] **Step 4: Run GREEN**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_filesystem.py -q
```

Expected: PASS.

### Task 7: Full verification, requirement audit, commit, and push

**Files:**
- Verify every modified source, test, README, design, and plan file.

- [ ] **Step 1: Run the complete repository gates**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev ruff check src tests
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev ruff format --check src tests
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev ty check src
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev python scripts/check_typing_boundaries.py src
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev python scripts/check_version_sync.py
git diff --check
```

Expected: every command exits 0; pytest reports zero failures and coverage at or above 80 percent.

- [ ] **Step 2: Audit all six findings against fresh evidence**

Run the six focused regression groups again, inspect `git diff --stat`, `git diff`, and
`git status --short`, and map each review finding to its test and production path. Confirm no
unrelated user changes are included.

- [ ] **Step 3: Commit all remaining implementation changes**

```bash
git add README.md src/doc_lattice/github_ci/audit.py \
  src/doc_lattice/github_ci/shell_scanner.py src/doc_lattice/github_ci/filesystem.py \
  tests/test_github_ci_audit.py tests/test_github_ci_shell_scanner.py \
  tests/test_github_ci_filesystem.py \
  docs/superpowers/plans/2026-07-17-ci-audit-publication-review-fixes.md
git commit -m "fix: close ci audit and publication review gaps"
```

- [ ] **Step 4: Push and verify the remote branch**

```bash
git push origin feature/github-linear-ci-bootstrap-impl
git status --short --branch
git rev-parse HEAD
git rev-parse origin/feature/github-linear-ci-bootstrap-impl
```

Expected: push succeeds, the worktree is clean, and local/remote object IDs match.
