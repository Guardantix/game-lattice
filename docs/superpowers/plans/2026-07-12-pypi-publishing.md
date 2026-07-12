# PyPI Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `doc-lattice` 1.0.0 to PyPI through GitHub Trusted Publishing and make exact PyPI pins the default generated installation path.

**Architecture:** Keep `release` responsible for version health, smoke tests, the Git tag, and the GitHub Release. A dependent unprivileged job checks out the exact tag, builds and validates distributions, and uploads one artifact. The final OIDC job only downloads that artifact and publishes it; executable Git-repository tests cover gate behavior and static contracts cover every workflow boundary.

**Tech Stack:** Python 3.13+, Hatchling, uv, pytest, ruamel.yaml, GitHub Actions, PyPA `gh-action-pypi-publish`, PyPI Trusted Publishing.

**Binding spec:** `docs/superpowers/specs/2026-07-12-pypi-publishing-design.md`

---

## File Map

- `src/doc_lattice/scaffold.py`: generate exact PyPI requirements instead of Git URLs.
- `src/doc_lattice/cli.py`: pass the plain package version into scaffold generation.
- `src/doc_lattice/version_check.py`: recognize both PyPI and tagged-Git README pins.
- `tests/test_scaffold.py`, `tests/test_cli.py`, `tests/test_version_check.py`: behavior tests for consumer-facing pins.
- `scripts/release_gate.py`: stdlib-only release decision logic, including the first-parent version check.
- `.github/workflows/ci.yml`: retry-safe release, unprivileged artifact build, and OIDC publish-only jobs.
- `tests/test_release_gate.py`: executable release-state tests using temporary Git repositories.
- `tests/test_release_workflow.py`: static contracts for permissions, dependencies, immutable action pins, and artifact wiring.
- `pyproject.toml`: explicit sdist contents, expanded PyPI project URLs, and version 1.0.0.
- `tests/test_package_metadata.py`: packaging configuration contract.
- `src/doc_lattice/__init__.py`, `uv.lock`, `CHANGELOG.md`, `README.md`, `RELEASING.md`: synchronized release state and operator/user documentation.

## Global Constraints

- Work on `feat/pypi-publishing`; the approved design is already committed there.
- Follow red-green-refactor for Python behavior and static configuration contracts: add one focused failing test, run it, implement the minimum change, and rerun it.
- Do not publish from the development machine and do not add a PyPI token. The first real upload happens only after merge through the configured `pypi` environment.
- Do not move or reuse `v0.9.0`. The new release is `v1.0.0`.
- Keep permissions separate: `release` has only `contents: write`, `build-release` only
  `contents: read`, and `publish` only `id-token: write`.
- Pin artifact upload, artifact download, and PyPI publication actions to reviewed full commit SHAs.
- Run pytest as `env -u FORCE_COLOR uv run --locked --group dev pytest`; the developer shell may export color-forcing variables that make Rich output assertions unreliable.

---

### Task 1: Generate exact PyPI pins

**Files:**
- Modify: `tests/test_scaffold.py:90-110`
- Modify: `tests/test_cli.py:1104-1114`
- Modify: `src/doc_lattice/scaffold.py:32-129`
- Modify: `src/doc_lattice/cli.py:604`

- [ ] **Step 1: Replace the Git-source scaffold tests with PyPI requirement tests**

In `tests/test_scaffold.py`, replace `test_snippets_pin_rev_url_and_python` and
`test_invocation_installs_from_pinned_git_ref` with:

```python
def test_snippets_pin_pypi_version_and_python():
    scaffold = build_scaffold(("docs",), None, "0.2.0")
    for text in (scaffold.precommit_text, scaffold.ci_text):
        assert "--from doc-lattice==0.2.0" in text
        assert "--python 3.13" in text
        assert "git+" not in text
    assert "repo: local" in scaffold.precommit_text
    assert "pass_filenames: false" in scaffold.precommit_text
    assert "actions/checkout@v4" in scaffold.ci_text
    assert "astral-sh/setup-uv@v6" in scaffold.ci_text
    assert "linear" not in scaffold.ci_text


def test_invocation_installs_from_exact_pypi_requirement():
    scaffold = build_scaffold(("docs",), None, "0.2.0")
    for text in (scaffold.precommit_text, scaffold.ci_text):
        assert "--from doc-lattice==0.2.0 doc-lattice check" in text
        assert "--from doc-lattice==0.2.0 doc-lattice lint" in text
```

Change the other `build_scaffold` calls in that file from `"v0.3.0"` to `"0.3.0"`.

In `tests/test_cli.py`, change the final assertion in `test_init_writes_config_and_prints_codegen`
to:

```python
    assert f"--from doc-lattice=={__version__}" in result.stdout
    assert "git+" not in result.stdout
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
env -u FORCE_COLOR uv run --locked --group dev pytest \
  tests/test_scaffold.py::test_snippets_pin_pypi_version_and_python \
  tests/test_scaffold.py::test_invocation_installs_from_exact_pypi_requirement \
  tests/test_cli.py::test_init_writes_config_and_prints_codegen -q
```

Expected: failures show the generated text still contains `git+https://...@0.2.0` and the CLI
still passes a leading `v`.

- [ ] **Step 3: Change scaffold generation to consume a package version**

Replace `_invocation` in `src/doc_lattice/scaffold.py` with:

```python
def _invocation(version: str, command: str) -> str:
    """Return a uvx command pinned to an exact PyPI version and Python interpreter."""
    return (
        f"uvx --python {PYTHON_PIN} --from doc-lattice=={version} "
        f"doc-lattice {command}"
    )
```

Rename the `rev` parameters of `render_precommit`, `render_ci`, and `build_scaffold` to `version`,
pass `version` to `_invocation`, and replace the `build_scaffold` argument documentation with:

```python
        version: The exact PyPI package version the snippets install, for example "1.0.0".
```

In `src/doc_lattice/cli.py`, change the scaffold call to:

```python
        scaffold = build_scaffold(roots, linear_team, __version__)
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
env -u FORCE_COLOR uv run --locked --group dev pytest tests/test_scaffold.py tests/test_cli.py -q
```

Expected: both modules pass.

- [ ] **Step 5: Commit the consumer-pin migration**

```bash
git add src/doc_lattice/scaffold.py src/doc_lattice/cli.py tests/test_scaffold.py tests/test_cli.py
git commit -m "feat: generate exact PyPI install pins"
```

---

### Task 2: Teach version sync about PyPI requirements

**Files:**
- Modify: `tests/test_version_check.py:5-125`
- Modify: `src/doc_lattice/version_check.py:5-113`

- [ ] **Step 1: Convert the fixture to a PyPI pin and add dual-syntax coverage**

Set `_README` in `tests/test_version_check.py` to:

```python
_README = "# doc-lattice\n\nuvx --from doc-lattice==0.4.0 doc-lattice --help\n"
```

Replace the existing README-pin tests with:

```python
def test_readme_pypi_pin_matches_is_consistent():
    readme = "uvx --from doc-lattice==0.4.0 doc-lattice\n"
    assert check_version_consistency("0.4.0", _PYPROJECT, _CHANGELOG, readme) == []


def test_readme_tagged_git_pin_matches_is_consistent():
    readme = (
        "uvx --from git+https://github.com/Guardantix/"
        "doc-lattice@v0.4.0 doc-lattice\n"
    )
    assert check_version_consistency("0.4.0", _PYPROJECT, _CHANGELOG, readme) == []


def test_readme_stale_pypi_pin_is_reported():
    readme = "uvx --from doc-lattice==0.3.0 doc-lattice\n"
    messages = check_version_consistency("0.4.0", _PYPROJECT, _CHANGELOG, readme)
    assert len(messages) == 1
    assert "README.md" in messages[0]
    assert "0.3.0" in messages[0]
    assert "0.4.0" in messages[0]


def test_readme_stale_tagged_git_pin_is_reported():
    readme = (
        "uvx --from git+https://github.com/Guardantix/"
        "doc-lattice@v0.3.0 doc-lattice\n"
    )
    messages = check_version_consistency("0.4.0", _PYPROJECT, _CHANGELOG, readme)
    assert len(messages) == 1
    assert "README.md" in messages[0]
    assert "0.3.0" in messages[0]


def test_readme_duplicate_stale_version_across_pin_syntaxes_yields_one_message():
    readme = (
        "uvx --from doc-lattice==0.3.0 doc-lattice init\n"
        "uvx --from git+https://github.com/Guardantix/"
        "doc-lattice@v0.3.0 doc-lattice --help\n"
    )
    messages = check_version_consistency("0.4.0", _PYPROJECT, _CHANGELOG, readme)
    assert len(messages) == 1
    assert "README.md" in messages[0]
```

Keep `test_readme_without_pin_is_consistent` unchanged. In
`test_first_version_heading_wins_over_later_ones`, change `readme_030` to:

```python
    readme_030 = "uvx --from doc-lattice==0.3.0 doc-lattice\n"
```

- [ ] **Step 2: Run the new PyPI-pin test and verify RED**

Run:

```bash
uv run --locked --group dev pytest tests/test_version_check.py::test_readme_stale_pypi_pin_is_reported -q
```

Expected: FAIL because the current regex ignores `doc-lattice==0.3.0`.

- [ ] **Step 3: Generalize the pin matcher and mismatch message**

In `src/doc_lattice/version_check.py`, replace `_PINNED_REF` with:

```python
_PINNED_REF = re.compile(r"doc-lattice(?:==|@v)(?P<version>\d+\.\d+\.\d+)")
```

Update the return-value docstring phrase from ``doc-lattice@vX.Y.Z`` to
``doc-lattice==X.Y.Z`` or ``doc-lattice@vX.Y.Z``. Replace the README mismatch message with:

```python
        messages.append(
            f"README.md pins doc-lattice version {stale_version}, "
            f"expected {init_version}; update the pinned install refs."
        )
```

- [ ] **Step 4: Run version tests and verify GREEN**

```bash
uv run --locked --group dev pytest tests/test_version_check.py -q
```

Expected: all version-check tests pass.

- [ ] **Step 5: Commit version-pin support**

```bash
git add src/doc_lattice/version_check.py tests/test_version_check.py
git commit -m "feat: validate PyPI version pins"
```

---

### Task 3: Add a retry-safe Trusted Publishing workflow

**Files:**
- Create: `scripts/release_gate.py`
- Create: `tests/test_release_gate.py`
- Create: `tests/test_release_workflow.py`
- Modify: `.github/workflows/ci.yml:59-180`

- [ ] **Step 1: Add executable gate and static workflow-contract tests**

In `tests/test_release_gate.py`, invoke `scripts/release_gate.py` in temporary real Git
repositories. Cover the complete output pair for an existing current tag retry, an existing older
tag no-op, an absent tag whose first parent already declares the version, an absent tag whose
parent declares another version, and an absent tag whose parent lacks the version file. Also assert
that a mismatched tagged version and malformed current or tagged source produce a GitHub error and
exit nonzero.

In `tests/test_release_workflow.py`, load `ci.yml` with `ruamel.yaml` and assert:

- release outputs and idempotent tag/GitHub Release behavior remain intact;
- the gate fetches tags and invokes `scripts/release_gate.py` with the runner environment;
- `build-release` needs `release`, checks out the exact release tag, has only `contents: read`,
  builds, validates, and uploads one named `dist/` artifact with `if-no-files-found: error`;
- artifact upload/download and PyPI publish actions use the reviewed 40-character SHAs;
- `publish` needs both earlier jobs, has only `id-token: write`, and has exactly two non-shell
  steps: download the named artifact to `dist/`, then publish it with `skip-existing: true`.

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
env -u FORCE_COLOR uv run --locked --group dev pytest \
  tests/test_release_gate.py tests/test_release_workflow.py -q --no-cov
```

Expected: failures because the script and build job do not exist, the workflow still has inline
gate logic, and the OIDC job still builds package code with a mutable publish-action ref.

- [ ] **Step 3: Implement and wire the release gate**

Add this mapping to the `release` job after `runs-on`:

```yaml
    outputs:
      proceed: ${{ steps.gate.outputs.proceed }}
      create_tag: ${{ steps.gate.outputs.create_tag }}
      version: ${{ steps.target.outputs.version }}
      tag: ${{ steps.target.outputs.tag }}
```

Create a stdlib-only `scripts/release_gate.py` that reads `TAG`, `VERSION`, `GITHUB_SHA`, and
`GITHUB_OUTPUT`, inspects the checked-out Git repository, and writes both `proceed` and
`create_tag` for every healthy state. Validate the current version source before deciding. For an
existing tag, compare its declared version and commit. For an absent tag, compare the first
parent's declared version; a missing parent version file means the current commit introduced the
version, while malformed source or unexpected Git/read errors fail clearly.

Replace the `Tag-health gate` shell body with:

```yaml
        run: |
          git fetch --tags --force
          uv run --no-sync python scripts/release_gate.py
```

Change the tag-creation step condition to:

```yaml
        if: steps.gate.outputs.create_tag == 'true'
```

- [ ] **Step 4: Make GitHub Release creation idempotent**

Replace the `Publish release notes` shell body with:

```yaml
        run: |
          if gh release view "${TAG}" >/dev/null 2>&1; then
            echo "GitHub Release ${TAG} already exists; leaving it unchanged."
          else
            uv run --no-sync python scripts/extract_release_notes.py "${VERSION}" > release-notes.md
            gh release create "${TAG}" --title "${TAG}" --notes-file release-notes.md --verify-tag
          fi
```

- [ ] **Step 5: Split unprivileged build from OIDC publication**

Append this job to `.github/workflows/ci.yml`:

```yaml
  build-release:
    name: Build release distributions
    needs: release
    if: needs.release.outputs.proceed == 'true'
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ needs.release.outputs.tag }}
      - uses: astral-sh/setup-uv@v6
      - name: Build distributions
        run: uv build
      - name: Validate distributions
        run: uvx --from twine twine check dist/*
      - name: Upload distributions
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: release-distributions
          path: dist/
          if-no-files-found: error

  publish:
    name: Publish to PyPI
    needs: [release, build-release]
    if: needs.release.outputs.proceed == 'true'
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - name: Download distributions
        uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093
        with:
          name: release-distributions
          path: dist/
      - name: Publish distributions to PyPI
        uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b
        with:
          skip-existing: true
```

- [ ] **Step 6: Run workflow tests and validate YAML**

```bash
env -u FORCE_COLOR uv run --locked --group dev pytest \
  tests/test_release_gate.py tests/test_release_workflow.py -q --no-cov
uv run pre-commit run check-yaml --files .github/workflows/ci.yml
```

Expected: all gate and workflow tests pass and `check-yaml` passes.

- [ ] **Step 7: Commit release automation**

```bash
git add .github/workflows/ci.yml scripts/release_gate.py \
  tests/test_release_gate.py tests/test_release_workflow.py \
  docs/superpowers/specs/2026-07-12-pypi-publishing-design.md \
  docs/superpowers/plans/2026-07-12-pypi-publishing.md
git commit -m "fix: isolate PyPI publishing credentials"
```

---

### Task 4: Restrict and describe package artifacts

**Files:**
- Create: `tests/test_package_metadata.py`
- Modify: `pyproject.toml:5-6,39-42`

- [ ] **Step 1: Add a packaging-configuration contract test**

Create `tests/test_package_metadata.py` with:

```python
"""Tests for the distributable package metadata and source contents."""

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_sdist_has_an_explicit_minimal_include_set():
    sdist = _PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert sdist["include"] == [
        "/src",
        "/tests",
        "/LICENSE",
        "/README.md",
        "/pyproject.toml",
    ]


def test_pypi_metadata_links_to_maintainer_resources():
    assert _PYPROJECT["project"]["urls"] == {
        "Homepage": "https://github.com/Guardantix/doc-lattice",
        "Source": "https://github.com/Guardantix/doc-lattice",
        "Issues": "https://github.com/Guardantix/doc-lattice/issues",
        "Changelog": "https://github.com/Guardantix/doc-lattice/blob/main/CHANGELOG.md",
        "Releases": "https://github.com/Guardantix/doc-lattice/releases",
    }
```

- [ ] **Step 2: Run the packaging tests and verify RED**

```bash
uv run --locked --group dev pytest tests/test_package_metadata.py -q
```

Expected: failures because there is no sdist target and only `Homepage` is declared.

- [ ] **Step 3: Add explicit sdist contents and project URLs**

Add after the wheel target in `pyproject.toml`:

```toml
[tool.hatch.build.targets.sdist]
include = [
    "/src",
    "/tests",
    "/LICENSE",
    "/README.md",
    "/pyproject.toml",
]
```

Replace `[project.urls]` with:

```toml
[project.urls]
Homepage = "https://github.com/Guardantix/doc-lattice"
Source = "https://github.com/Guardantix/doc-lattice"
Issues = "https://github.com/Guardantix/doc-lattice/issues"
Changelog = "https://github.com/Guardantix/doc-lattice/blob/main/CHANGELOG.md"
Releases = "https://github.com/Guardantix/doc-lattice/releases"
```

- [ ] **Step 4: Run packaging tests and verify GREEN**

```bash
uv run --locked --group dev pytest tests/test_package_metadata.py -q
```

Expected: both tests pass.

- [ ] **Step 5: Build and inspect the package before the version bump**

```bash
dist_dir="$(mktemp -d)"
uv build --out-dir "${dist_dir}"
uvx --from twine twine check "${dist_dir}"/*
tar -tzf "${dist_dir}/doc_lattice-0.9.0.tar.gz"
unzip -l "${dist_dir}/doc_lattice-0.9.0-py3-none-any.whl"
```

Expected: `twine check` passes; the sdist contains the selected repository paths, generated
`PKG-INFO`, and Hatchling's required `.gitignore`, with an artifact-level test enforcing that no
other repository files are present; the wheel contains `doc_lattice`, its metadata, license, and
console entry point.

- [ ] **Step 6: Commit packaging metadata**

```bash
git add pyproject.toml tests/test_package_metadata.py
git commit -m "build: define PyPI package contents"
```

---

### Task 5: Cut synchronized 1.0.0 release sources and documentation

**Files:**
- Modify: `src/doc_lattice/__init__.py:3`
- Modify: `pyproject.toml:10`
- Modify: `uv.lock:105-106`
- Modify: `CHANGELOG.md:5`
- Modify: `README.md:144-164,308-321`
- Rewrite: `RELEASING.md`

- [ ] **Step 1: Add the 1.0.0 changelog section**

Insert before the 0.9.0 section in `CHANGELOG.md`:

```markdown
## [1.0.0] - 2026-07-12

### Added

- Publish release wheels and source distributions to PyPI through GitHub Actions Trusted
  Publishing, with no stored PyPI credential.

### Changed

- Generated pre-commit and CI gates install an exact `doc-lattice==1.0.0` PyPI requirement
  instead of cloning and building a tagged Git revision.
- Release retries distinguish the current tagged commit from an ordinary unversioned merge,
  making GitHub Release and PyPI publication safe to resume after a partial failure.
- Source distributions contain only package source, tests, license, README, and build metadata.
```

- [ ] **Step 2: Make README installation and adoption PyPI-first**

Replace the Quick Start `Install` and `Run` blocks with:

````markdown
### Install and run

Run the released CLI without installing it globally:

```bash
uvx doc-lattice --help
```

Or install it into an isolated tool environment:

```bash
uv tool install doc-lattice
doc-lattice --help
```

`pipx install doc-lattice` provides the same isolated installation. A conventional
`python -m pip install doc-lattice` is also supported when installing into an activated virtual
environment.

### Development

```bash
uv sync --group dev
uv run doc-lattice --help
```
````

Replace the adoption command with:

```bash
uvx --python 3.13 --from doc-lattice==1.0.0 doc-lattice init
```

After the paragraph explaining generated files, add:

```markdown
To test an unreleased commit, replace the PyPI requirement with a Git source such as
`--from git+https://github.com/Guardantix/doc-lattice@<commit>`; released configurations
should keep the exact PyPI version pin.
```

- [ ] **Step 3: Rewrite the release operator guide**

Replace `RELEASING.md` with:

````markdown
# Releasing doc-lattice

doc-lattice publishes immutable Git tags, GitHub Releases, wheels, and source distributions.
PyPI authentication uses GitHub Actions Trusted Publishing: the PyPI publisher trusts
`Guardantix/doc-lattice`, workflow `ci.yml`, and GitHub environment `pypi`. No API token is
stored in GitHub.

## Checklist

1. Bump the version in `src/doc_lattice/__init__.py`, `pyproject.toml`, the newest versioned
   `CHANGELOG.md` heading, and every exact README pin.
2. Run `uv lock` and commit the refreshed `uv.lock`.
3. Ensure the matching changelog section is non-empty; its body becomes the GitHub Release notes.
4. Run the full local verification commands documented below, open a PR, and get CI green.
5. Merge to `main`. After quality jobs pass, the release job smoke-tests the commit, creates
   `vX.Y.Z`, and creates the GitHub Release. The unprivileged build job checks out that tag,
   builds and validates both distributions, and uploads one workflow artifact. The OIDC publish
   job only downloads that artifact and uploads it to PyPI.
6. Confirm `uvx doc-lattice --version` prints the released version from PyPI.

An ordinary merge without a version bump is a no-op. A rerun for a tag that identifies the same
commit resumes release, build, and publish work; an existing PyPI file is skipped. A tag for the
same version at an older commit remains a no-op. When the tag is absent, a first parent that
already declares the version also makes a later commit a no-op. A tag whose source declares
another version and malformed version source fail the release gate.

If a release fails after its tag is pushed, rerun the same workflow. Do not move the tag and do
not delete or replace uploaded PyPI files. If published contents are wrong, fix them and release
the next version.

## Local verification

```bash
env -u FORCE_COLOR uv run --locked --group dev pytest
uv run --locked --group dev ruff check src tests scripts/release_gate.py
uv run --locked --group dev ruff format --check src tests scripts/release_gate.py
uv run --locked --group dev ty check src scripts/release_gate.py
uv run --locked --group dev python scripts/check_typing_boundaries.py src
uv run --locked --group dev python scripts/check_version_sync.py
uv build
uvx --from twine twine check dist/*
```

Install the built wheel into a temporary Python 3.13 environment before merging:

```bash
smoke_dir="$(mktemp -d)"
uv venv --python 3.13 "${smoke_dir}"
uv pip install --python "${smoke_dir}/bin/python" dist/*.whl
"${smoke_dir}/bin/doc-lattice" --version
```
````

- [ ] **Step 4: Bump the canonical version sources and lockfile**

Set:

```python
__version__ = "1.0.0"
```

in `src/doc_lattice/__init__.py`, and set:

```toml
version = "1.0.0"
```

in `pyproject.toml`. Then run:

```bash
uv lock
```

Expected: the root `doc-lattice` package in `uv.lock` becomes version `1.0.0`.

- [ ] **Step 5: Verify synchronized release sources**

```bash
uv run --locked --group dev python scripts/check_version_sync.py
uv run --locked doc-lattice --version
```

Expected: version sync exits 0 and the CLI prints `1.0.0`.

- [ ] **Step 6: Commit the release bump and docs**

```bash
git add src/doc_lattice/__init__.py pyproject.toml uv.lock CHANGELOG.md README.md RELEASING.md
git commit -m "chore: prepare 1.0.0 PyPI release"
```

---

### Task 6: Full verification and release handoff

**Files:**
- Verify: all changed files and built artifacts

- [ ] **Step 1: Run the complete automated suite**

```bash
env -u FORCE_COLOR uv run --locked --group dev pytest
uv run --locked --group dev ruff check src tests scripts/release_gate.py
uv run --locked --group dev ruff format --check src tests scripts/release_gate.py
uv run --locked --group dev ty check src scripts/release_gate.py
uv run --locked --group dev python scripts/check_typing_boundaries.py src
uv run --locked --group dev python scripts/check_version_sync.py
```

Expected: every command exits 0 and coverage remains at least 80 percent.

- [ ] **Step 2: Build and validate final 1.0.0 artifacts**

```bash
uv build
uvx --from twine twine check dist/*
tar -tzf dist/doc_lattice-1.0.0.tar.gz
unzip -l dist/doc_lattice-1.0.0-py3-none-any.whl
```

Expected: exactly one sdist and one `py3-none-any` wheel; metadata checks pass; the sdist has only
the selected source paths, generated `PKG-INFO`, and Hatchling's required `.gitignore`, with the
artifact-level test rejecting every other repository file; the wheel has no tests, repository
cache, workflow, or internal docs.

- [ ] **Step 3: Install the wheel on the minimum Python and smoke-test the entry point**

```bash
smoke_dir="$(mktemp -d)"
uv venv --python 3.13 "${smoke_dir}"
uv pip install --python "${smoke_dir}/bin/python" dist/doc_lattice-1.0.0-py3-none-any.whl
"${smoke_dir}/bin/doc-lattice" --version
"${smoke_dir}/bin/doc-lattice" --help
```

Expected: version output is `1.0.0`; help exits 0 and lists the command set.

- [ ] **Step 4: Inspect the final diff and repository state**

```bash
git diff --check main...HEAD
git status --short
git log --oneline main..HEAD
```

Expected: no whitespace errors; only untracked `dist/` artifacts may remain; commits are limited
to the approved PyPI publishing scope.

- [ ] **Step 5: Post-merge verification**

After GitHub reports that `release`, `build-release`, and `publish` succeeded:

```bash
uvx --refresh doc-lattice --version
```

Expected: PyPI resolves `doc-lattice` and prints `1.0.0`. Confirm the PyPI release displays the
GitHub Trusted Publisher and attestations, and confirm the GitHub Release is tagged `v1.0.0`.
