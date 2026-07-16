# CI Audit Review Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all five verified CI audit and refresh safety gaps without weakening the existing conservative scanner or filesystem behavior.

**Architecture:** Normalize only bare shell continuation boundaries and fail closed for GNU `env` split-string construction. Move GitHub-CI path escaping into one helper. Serialize managed artifact mutation with an advisory root-directory lock covering the final re-read and atomic publication.

**Tech Stack:** Python 3.13+, pytest, Typer, POSIX `fcntl`, and `uv`.

---

### Task 1: Cover and fix bare shell continuations

**Files:**
- Modify: `tests/test_github_ci_shell_scanner.py`
- Modify: `tests/test_github_ci_audit.py`
- Modify: `src/doc_lattice/github_ci/shell_scanner.py`

- [ ] **Step 1: Write failing direct-scanner tests**

```python
@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("doc-lattice " + chr(92) + "\n  linear", LINEAR),
        ("doc-lattice " + chr(92) + "\n  reconcile --all", RECONCILE),
    ],
)
def test_direct_doc_lattice_invocations_handles_indented_bare_continuations(script, expected):
    assert direct_doc_lattice_invocations(script) == expected
```

Add a pull-request workflow regression that asserts those forms produce
`PR_LINEAR_INVOCATION` and `PR_MUTATING_RECONCILE`.

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_shell_scanner.py::test_direct_doc_lattice_invocations_handles_indented_bare_continuations -q
```

Expected: FAIL because both forms currently return no invocation.

- [ ] **Step 3: Implement the minimal parser boundary**

In `_ShellScanner._consume_command_boundary`, recognize a bare `\\\n` before word parsing:

```python
if self.source.startswith("\\\n", index):
    return index + 2
```

Leave `_parse_word` behavior intact for continuations in the middle of an existing word.

- [ ] **Step 4: Verify GREEN**

Run the Step 2 test and the related audit regression. Expected: PASS, including existing quoted and embedded-continuation cases.

- [ ] **Step 5: Commit**

```bash
git add src/doc_lattice/github_ci/shell_scanner.py tests/test_github_ci_shell_scanner.py tests/test_github_ci_audit.py
git commit -m "fix: classify indented shell continuations in ci audit"
```

### Task 2: Fail closed on GNU env split strings

**Files:**
- Modify: `tests/test_github_ci_shell_scanner.py`
- Modify: `tests/test_github_ci_audit.py`
- Modify: `src/doc_lattice/github_ci/shell_scanner.py`

- [ ] **Step 1: Write failing split-string tests**

```python
@pytest.mark.parametrize(
    "script",
    [
        "env -S 'doc-lattice linear'",
        "env -iS 'doc-lattice linear'",
        "env --split-string='doc-lattice reconcile --all'",
    ],
)
def test_direct_doc_lattice_invocations_fails_closed_on_env_split_string(script):
    with pytest.raises(ConfigError, match=r"shell scan.*env split-string"):
        direct_doc_lattice_invocations(script)
```

Add a PR-workflow test proving the audit is a typed scan error, not a successful audit.

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_shell_scanner.py::test_direct_doc_lattice_invocations_fails_closed_on_env_split_string -q
```

Expected: FAIL because the current generic env-option branch drops the wrapper payload.

- [ ] **Step 3: Implement conservative option recognition**

Add a helper that recognizes `-S`, short clusters containing `S`, `--split-string`, and
`--split-string=<value>`. In `_skip_env_prefix`, before generic option skipping, raise:

```python
raise _ShellScanIncomplete("env split-string option cannot be statically scanned")
```

- [ ] **Step 4: Verify GREEN**

Run the Step 2 test and existing ordinary `env` wrapper tests. Expected: split strings fail closed; assignments, `-u`, `--unset`, `-C`, and `--chdir` retain current behavior.

- [ ] **Step 5: Commit**

```bash
git add src/doc_lattice/github_ci/shell_scanner.py tests/test_github_ci_shell_scanner.py tests/test_github_ci_audit.py
git commit -m "fix: fail closed on env split-string ci commands"
```

### Task 3: Read all local origins before inference

**Files:**
- Modify: `tests/cli/test_ci.py`
- Modify: `src/doc_lattice/cli/commands/ci.py`

- [ ] **Step 1: Write a real-Git ambiguity regression**

Initialize a temporary repository, add two `remote.origin.url` values with `git config --add`,
invoke `ci audit` without `--repository`, and assert exit code `2`. Update the mocked call
assertion to:

```python
["git", "config", "--local", "--get-all", "remote.origin.url"]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/cli/test_ci.py::test_ci_audit_omitted_repository_rejects_real_ambiguous_local_origin -q
```

Expected: FAIL because `--get` returns only the final configured URL.

- [ ] **Step 3: Implement exact cardinality query**

Replace `--get` with `--get-all` in `_resolve_repository`; retain the existing decode,
`splitlines`, and exact-one-nonempty-value validation.

- [ ] **Step 4: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov tests/cli/test_ci.py -q
git add src/doc_lattice/cli/commands/ci.py tests/cli/test_ci.py
git commit -m "fix: reject ambiguous local origins in ci audit"
```

### Task 4: Share terminal-safe workflow path display

**Files:**
- Create: `src/doc_lattice/github_ci/display.py`
- Modify: `src/doc_lattice/github_ci/workflow_parser.py`
- Modify: `src/doc_lattice/github_ci/filesystem.py`
- Modify: `src/doc_lattice/cli/commands/ci.py`
- Modify: `tests/test_github_ci_audit.py`
- Modify: `tests/test_github_ci_workflow_parser.py`
- Modify: `tests/cli/test_ci.py`

- [ ] **Step 1: Write failing early-discovery diagnostic tests**

Use a filename such as `evil\\nFORGED:\\x1b.yml`. Exercise symlink, FIFO/non-regular,
oversized, changed-during-read, and non-UTF-8 diagnostics. Each assertion must require `\\n`
and `\\u001b`, reject actual LF/ESC bytes, and reject checkout-path leakage.

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_audit.py::test_discover_workflows_escapes_control_characters_in_candidate_diagnostics -q
```

Expected: FAIL because early discovery interpolates the raw candidate pathname.

- [ ] **Step 3: Add a common helper and consume it everywhere**

```python
def escape_repository_path(path: str | Path) -> str:
    """Render a repository-relative path without terminal-active control bytes."""
    return json.dumps(str(path), ensure_ascii=True)[1:-1]
```

Use it in workflow parsing, CLI findings, and every candidate-derived filesystem message. Keep a raw
path for path operations/model values and a separate escaped path for diagnostics.

- [ ] **Step 4: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_audit.py tests/test_github_ci_workflow_parser.py tests/cli/test_ci.py -q
git add src/doc_lattice/github_ci/display.py src/doc_lattice/github_ci/workflow_parser.py \
  src/doc_lattice/github_ci/filesystem.py src/doc_lattice/cli/commands/ci.py \
  tests/test_github_ci_audit.py tests/test_github_ci_workflow_parser.py tests/cli/test_ci.py
git commit -m "fix: escape workflow discovery diagnostics"
```

### Task 5: Lock final managed-artifact publication

**Files:**
- Modify: `tests/test_github_ci_filesystem.py`
- Modify: `src/doc_lattice/github_ci/filesystem.py`

- [ ] **Step 1: Write failing lock coverage tests**

Preflight two refreshes from one old artifact set. During the first mocked
`atomic_replace_bytes`, attempt the second `apply_changes` and assert:

```python
with pytest.raises(ConfigError, match="managed artifact refresh is in progress"):
    apply_changes(contending_changes)
```

Also disable locking with a monkeypatch and assert `apply_changes` raises before writing any target.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov \
  tests/test_github_ci_filesystem.py::test_apply_changes_locks_final_replacement \
  tests/test_github_ci_filesystem.py::test_apply_changes_fails_closed_without_locking -q
```

Expected: FAIL because current `apply_changes` has no operation-wide lock.

- [ ] **Step 3: Implement the nonblocking root-directory lock**

Add a deferred-`fcntl` context manager in `filesystem.py`. It must open the existing root,
acquire `LOCK_EX | LOCK_NB`, release/close on every exit, add cleanup errors as notes when another
operation error is active, and raise `ConfigError` for contention, setup failure, or unsupported
platform. Make `apply_changes` require one shared root for mutable changes and hold the lock across
the existing final read/compare and `atomic_replace_bytes` calls.

- [ ] **Step 4: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest --no-cov tests/test_github_ci_filesystem.py -q
git add src/doc_lattice/github_ci/filesystem.py tests/test_github_ci_filesystem.py
git commit -m "fix: lock managed artifact refresh publication"
```

### Task 6: Verify and publish the combined change

**Files:**
- Verify: all modified source and test files

- [ ] **Step 1: Run the complete suite**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev pytest
```

Expected: exit `0` with repository-wide coverage satisfied.

- [ ] **Step 2: Run required static checks**

```bash
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev ruff check src tests
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev ruff format --check src tests
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev ty check src
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev python scripts/check_typing_boundaries.py src
UV_CACHE_DIR=/tmp/doc_lattice_uv_cache uv run --active --group dev python scripts/check_version_sync.py
git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 3: Audit scope, commit, and push**

Run `git status --short`, inspect `git diff origin/feature/github-linear-ci-bootstrap-impl...HEAD`,
and confirm every review item has a regression test and implementation. Commit any uncommitted
plan/test/source changes, then push without force:

```bash
git push origin feature/github-linear-ci-bootstrap-impl
```
