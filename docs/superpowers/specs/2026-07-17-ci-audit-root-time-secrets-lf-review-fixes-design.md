# CI Audit Root, Time, Secrets, and LF Review Fixes Design

**Date:** 2026-07-17
**Status:** Approved for autonomous implementation

## Purpose

Close four verified fail-open or unusable-installation paths in the managed GitHub CI feature:

1. Managed CI operations can inspect or write a nested `.github` directory instead of the Git
   repository root.
2. The Bash scanner misses payloads after the valid `time --` and `time -p --` prefixes.
3. Reusable-workflow jobs can forward the complete caller secret set with `secrets: inherit`
   without a `LINEAR_SECRET_REFERENCE` finding.
4. A normal Windows checkout can convert the managed bootstrap to CRLF even though Git Bash is a
   supported execution environment.

## Selected approach

### Repository-root ownership

Add one local Git adapter that resolves `git rev-parse --show-toplevel` from the invocation
directory, validates one UTF-8 absolute directory path, and requires the invocation directory to
remain inside that resolved root. `init --github`, `ci audit`, and `ci refresh` will resolve this
root before any managed-artifact inspection or write. GitHub-mode init will also place its project
config at the repository root, keeping one coherent installation. Ordinary `init` remains rooted
at the invocation directory and does not require Git.

Origin resolution will run from the resolved top-level so repository identity and artifact
inspection cannot refer to different repositories. Explicit `--repository` continues to bypass
origin lookup, but it does not bypass top-level resolution because filesystem scope still needs a
trusted anchor.

### Bash `time` terminator

Extend the existing `time` arm in `_skip_shell_prefixes`. After consuming the optional literal
`-p`, consume one literal, non-shape-changing `--`. Dynamic or quoted values keep their current
conservative treatment; only Bash's static option terminator is recognized. This keeps nested
wrapper handling in the shared prefix walk and exposes both Linear and reconcile payloads to the
existing policy classification.

### Reusable-workflow secret inheritance

Treat the exact scalar keyword `inherit` as unsafe only when its structure path is exactly a
reusable-workflow job's `jobs.<job_id>.secrets` field. The path constraint avoids rejecting prose,
step inputs, unrelated values named `inherit`, or invalid keyword spellings GitHub would not
execute. The canonical trusted Linear step does not use job-level secret inheritance, so no
exemption is needed.

### Checkout-stable LF bootstrap

Add `.github/.gitattributes` as a fourth managed artifact with an `attributes` ownership role and
the repository-relative rule:

```gitattributes
doc-lattice-bootstrap.sh text eol=lf
```

Locating the file inside `.github` scopes its pattern to the bootstrap without taking ownership of
a consumer's root `.gitattributes`. Init and refresh use the existing create-only and managed
replacement machinery. Audit validates ownership, version, repository identity, and the exact
effective non-comment rule while tolerating LF or CRLF separators in the attributes file itself.
Removing or weakening the rule therefore fails audit even if the ownership header remains.

The README will describe all four artifacts, the Git-root behavior, and the LF guarantee. The
architecture decision will record the additional local managed artifact without changing the
external human-administration boundary.

## Alternatives rejected

- Rejecting all subdirectory invocations would be safe but needlessly hostile when Git already
  provides one unambiguous top-level directory.
- Resolving the root only when `--repository` is omitted would keep the original fail-open path
  for explicit identities, including the identity used by generated workflows.
- Special-casing `time --` only in audit would duplicate shell grammar and leave the reusable
  scanner API incorrect.
- Treating every scalar `inherit` as secret inheritance would create false positives outside the
  `jobs.<job_id>.secrets` field.
- Merely rejecting CRLF bootstrap bytes would detect damage after checkout but would not prevent
  repeat conversion. Managing a scoped attributes file fixes the conversion source.
- Appending to a consumer's root `.gitattributes` would require unsafe partial-file mutation and
  conflict resolution. A managed `.github/.gitattributes` has a single purpose and bounded path.

## Test strategy

Each behavior starts with a focused regression observed failing:

- real Git repositories invoked from a nested directory prove that GitHub-mode init writes at the
  top-level and that audit and refresh ignore nested decoy artifacts;
- scanner and PR-policy cases cover `time -- doc-lattice linear` and
  `time -p -- doc-lattice reconcile --all`;
- reusable-workflow audit cases reject job-level `secrets: inherit` while allowing unrelated
  `inherit` scalars; and
- render, init, audit, and refresh tests prove the scoped attributes artifact exists, carries the
  LF rule, reports drift when the rule is weakened, and is recreated when missing.

Focused suites follow every minimal implementation. Final verification runs the complete pytest
suite, Ruff check and format check, `ty`, typing-boundary validation, version synchronization, and
`git diff --check`. A final requirement audit then inspects the complete diff before commit and a
non-force push of the current branch.
