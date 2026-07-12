# PyPI Publishing Design

**Date:** 2026-07-12
**Status:** Approved
**Target release:** 1.0.0

## Purpose

Publish `doc-lattice` as a PyPI project so adopters can install a released wheel with
`uvx`, `pipx`, or `pip` instead of cloning and building a pinned Git revision. Preserve the
existing version guard, tag creation, GitHub Release, and release smoke tests while adding a
PyPI publication stage with no stored credential and a minimal OIDC trust boundary.

The maintainer has completed the one-time external setup:

- the `doc-lattice` PyPI project has a GitHub Actions Trusted Publisher;
- the publisher trusts `Guardantix/doc-lattice`, workflow `ci.yml`, and environment `pypi`;
- the repository has a matching `pypi` environment.

## Release Architecture

The existing `release` job remains responsible for deciding whether the current `main` commit
is a new release, smoke-testing it, creating `v1.0.0`, and creating the GitHub Release. It exposes
the release decision and exact tag through job outputs. A dependent `build-release` job checks
out that tag, builds and validates the wheel and source distribution, and uploads `dist/` as one
workflow artifact. The final `publish` job downloads that artifact and uploads it to PyPI.

The jobs intentionally use separate permissions:

- `release` retains only `contents: write` for tags and GitHub Releases;
- `build-release` has only `contents: read` and runs package build and validation code;
- `publish` receives only `id-token: write`, uses the protected `pypi` environment, and runs no
  repository or package code.

Artifact transfer and publication actions are pinned to immutable commits:

- `actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02`;
- `actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093`;
- `pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b`.

The OIDC-capable job has exactly two steps: download the named distribution artifact to `dist/`,
then invoke the pinned PyPA publisher. Trusted Publishing supplies a short-lived credential; the
repository stores no PyPI token. The publish action uses `skip-existing: true` so retrying an
already-completed upload succeeds without attempting to replace immutable PyPI files.

## Release Gate and Retry Semantics

The tag-health gate is a small standard-library Python script exercised against real temporary
Git repositories. It validates the current source and distinguishes four healthy states and one
error state:

1. If the target tag exists at the workflow's `GITHUB_SHA` and declares the target version, the
   run is a retry. Tag creation is skipped, GitHub Release creation is made idempotent, and PyPI
   publication is allowed. This recovers from a failure after the tag was pushed.
2. If the target tag declares the target version but points at an older commit, the current push
   is an ordinary merge without a version bump. Release and publish work are skipped.
3. If the target tag is absent and the first parent already declares the target version, the
   current push is a later unchanged-version commit. Release and publish work are skipped so it
   cannot claim a tag that is unexpectedly missing.
4. If the target tag is absent and the first parent declares a different version, or has no
   version file, the current commit introduced the version. The job creates the tag and continues
   through GitHub Release, build, and publication.
5. If the tag's source declares a different version, the job fails because the tag is corrupt or
   was reused.

Malformed current, tagged, or parent version source and unexpected Git/read errors fail clearly;
they are never interpreted as healthy states. The release job exposes at least `proceed`,
`create_tag`, `version`, and `tag`. The build and publish jobs run only when `proceed` is true.
These rules ensure a distribution is always built from the same commit named by its Git tag and
prevent a later `main` commit from being published under an old version.

## Package Contents and Metadata

The existing Hatchling configuration already creates a platform-independent wheel containing the
`doc_lattice` package and `doc-lattice` console entry point. The first PyPI release keeps the
distribution name, import name, minimum Python version, license, author, and runtime dependencies
declared in `pyproject.toml`.

The source distribution will use an explicit Hatch include set so it contains only the material
needed to inspect, test, and rebuild the package: `src`, `tests`, `LICENSE`, `README.md`, and
`pyproject.toml`. Repository caches, internal agent instructions, CI files, development logs, and
design history are excluded. Both the wheel and source distribution must pass `twine check`, and
the wheel must install and report `1.0.0` on Python 3.13.

Project URLs may be expanded with source, issue tracker, changelog, and release links, but no new
runtime metadata system or dynamic versioning is introduced for this release.

## Version and Consumer Migration

The release version moves directly from `0.9.0` to `1.0.0`. All existing synchronized version
sources move together:

- `src/doc_lattice/__init__.py`;
- `pyproject.toml`;
- the newest versioned `CHANGELOG.md` heading;
- version pins in `README.md` checked by the version-sync guard.

Generated pre-commit and CI snippets change from a tagged Git source to an exact PyPI requirement:

```text
uvx --python 3.13 --from doc-lattice==1.0.0 doc-lattice <command>
```

The exact pin preserves reproducibility while avoiding Git checkout and local package builds.
README installation and adoption instructions make PyPI the primary released-package path and
retain `git+https://...@<ref>` only as a fallback for testing an unreleased commit. `RELEASING.md`
documents the Trusted Publisher prerequisite, PyPI publish stage, retry behavior, artifact checks,
and post-release smoke command.

## Failure Handling

- Build or metadata validation failure prevents the artifact from reaching the OIDC-capable job
  and leaves existing PyPI files unchanged.
- Trusted Publisher mismatch or missing OIDC permission fails only the publish job with no fallback
  to a stored token.
- A successful tag followed by a failed GitHub Release or PyPI upload is recoverable by rerunning
  the same workflow at the same commit.
- PyPI's immutable files are never overwritten; a genuinely bad published release requires a new
  version.
- An ordinary merge with no version bump remains a release no-op, even when its expected tag is
  unexpectedly absent.

## Testing and Acceptance

Automated tests will verify the generated pre-commit and CI snippets use the exact
`doc-lattice==1.0.0` PyPI requirement and no longer emit a Git source. Version-sync tests continue
to cover all declared sources. Executable release-gate tests use real Git repositories to cover
the tag retry, older-tag no-op, missing-tag parent checks, and corrupt-source failure. Static
workflow tests assert exact-tag checkout in the unprivileged build job, artifact validation and
transfer, immutable action pins, and the two-step OIDC publish-only boundary.

The implementation is complete when:

- the full test, lint, formatting, and type-check suite passes;
- `uv build` produces a wheel and source distribution with the intended contents;
- `twine check dist/*` passes;
- installing the wheel on Python 3.13 and running `doc-lattice --version` prints `1.0.0`;
- merging the version bump creates `v1.0.0`, a GitHub Release, and the PyPI release;
- `uvx doc-lattice --version` resolves from PyPI and prints `1.0.0`;
- rerunning the release workflow does not fail or republish different contents.

## Out of Scope

- Publishing historical versions, including `0.9.0`.
- Supporting Python versions older than 3.13.
- Replacing Hatchling, `uv`, or the existing version-sync mechanism.
- Storing a PyPI API token or adding a token-based publishing fallback.
- Moving release automation into a separate workflow.
