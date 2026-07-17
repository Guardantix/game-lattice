# CI Audit Linear Help Design

**Date:** 2026-07-17
**Status:** Approved for autonomous implementation

## Purpose

Stop `ci audit` from reporting `PR_LINEAR_INVOCATION` when a pull-request workflow runs
effective `doc-lattice linear --help`. Typer handles that option eagerly and exits before the
Linear command callback loads a project, builds a lattice, or accesses Linear.

The correction must preserve fail-closed classification when `--help` is consumed as an option
value, appears after `--`, or is preceded by shell expansion whose runtime argv cannot be known.

## Selected approach

Replace the reconcile-only safe-option result with a small command-disposition model shared by
the two policy-sensitive commands. The bounded argument walk will use each command's static Typer
option grammar and produce one of three outcomes:

- effective `--help`: the command does not execute, so the scanner records no invocation;
- effective reconcile `--dry-run`: the command executes read-only, preserving the existing safe
  reconcile classification; or
- no certified stopping/read-only option: the invocation remains policy-sensitive.

Linear's value-taking options are `--from`, `--config`, `--format`, and `--indent`; its ordinary
flags are `--exit-code` and `--warn-exit`. Reconcile retains its existing option grammar. Known
value-taking options consume their successor before it can be interpreted as help, `--` ends
option parsing, and dynamic or argv-expanding words before a safe outcome remain conservative.

This makes non-execution explicit instead of overloading the invocation boolean used for
reconcile dry runs. It also makes effective help consistent with root and launcher help, which
already suppress impossible payload invocations.

## Alternatives rejected

- Treating any literal Linear `--help` token as non-executing would incorrectly approve
  `linear --config --help` and `linear -- --help`.
- Adding a separate Linear-only argument walker would duplicate the reconcile parser and allow the
  same Typer option-consumption rules to diverge again.
- Marking Linear help with the existing `True` invocation boolean and changing audit to ignore it
  would continue conflating a command that never runs with a command that runs read-only.

## Test strategy

First add focused regressions and observe them fail against the current scanner:

- PR audit emits no finding for effective Linear help, including known options before help;
- the scanner records no invocation for the same effective forms; and
- consumed, positional, and dynamically preceded help remain Linear invocations.

Then implement the shared disposition walk and rerun the focused tests. Final verification covers
the full shell-scanner and CI-audit suites, the full project test suite, Ruff lint and formatting,
type checking, typing-boundary and version checks, pre-commit, and `git diff --check` before the
implementation is committed and pushed without force.
