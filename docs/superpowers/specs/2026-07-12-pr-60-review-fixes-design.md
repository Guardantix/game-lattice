# PR #60 Review Fixes Design

## Goal

Address the two unresolved review findings on PR #60 without weakening the release gate's
fail-closed behavior or expanding the published source distribution with repository automation.

## Release decision boundary

The release workflow runs once for a push to `main`, and a single push may land several commits.
The release decision must therefore compare the state before the push with the final landed state,
not compare `GITHUB_SHA` only with its immediate parent.

The workflow will pass `github.event.before` to `scripts/release_gate.py` as `GITHUB_BEFORE`. The
gate will continue to validate and tag the resolved `GITHUB_SHA`. When the target tag is absent, it
will read the version at `GITHUB_BEFORE`:

- If the pre-push source declares a different version, or has no version file, the push introduced
  the final version. Release work proceeds and the tag is created at the final landed commit.
- If the pre-push source already declares the final version, the push is an ordinary no-op.
- If either boundary cannot be resolved or contains a malformed version declaration, the gate
  fails closed.

Existing-tag retry and corruption checks remain unchanged. In particular, a matching tag at the
final commit resumes release work, while a healthy matching-version tag at an older commit remains
an ordinary no-op.

This boundary-based approach is preferable to walking backward through history, which could
resurrect an intentionally skipped older release during a later push. It is also preferable to
checking whether the version file changed, because comparing parsed source versions preserves the
gate's existing validation semantics.

## Source distribution test boundary

The sdist will continue to include package source and distributable tests while excluding GitHub
workflow configuration and release scripts. The two tests that directly validate those repository
automation files will be explicitly excluded:

- `tests/test_release_gate.py`
- `tests/test_release_workflow.py`

This keeps the artifact minimal and makes its packaged test set internally complete. Shipping
`.github/workflows/ci.yml` and `scripts/release_gate.py` solely to satisfy repository-only tests
would expand the artifact with files that downstream users do not need.

## Test strategy

Release-gate regression coverage will model a real repository with a pre-push commit on the old
version, a version-bump commit, and a later same-version commit used as `GITHUB_SHA`. The expected
decision is `proceed=true` and `create_tag=true`, with the final commit remaining the tag target.
Existing no-op, retry, malformed-source, and missing-version cases will be expressed in terms of
the explicit pre-push boundary. A workflow contract test will require `GITHUB_BEFORE` to be passed
from `github.event.before`.

Package metadata tests will require the explicit sdist exclusions and verify the built archive does
not contain either repository-only test. The existing archive allowlist continues to reject
`.github/` and `scripts/` content.

## Documentation impact

`RELEASING.md` will describe decisions across a push boundary and clarify that a version bump may
occur anywhere in a multi-commit push while the release tag still identifies the final landed
commit. No user-facing package behavior changes.
