# CI Audit Dynamic Subcommand Design

**Date:** 2026-07-17
**Status:** Approved for autonomous implementation

## Purpose

Make the pull-request shell audit fail closed when a direct `doc-lattice` invocation ends with
an unresolved dynamic subcommand. Today, scripts such as `CMD=linear; doc-lattice "$CMD"` and
`CMD='reconcile --all'; doc-lattice $CMD` produce a complete empty scan even though runtime shell
expansion can invoke a protected command.

The correction must preserve complete empty results for commands that are statically known not
to invoke a subcommand, including bare `doc-lattice` and eager root `--help` or `--version`.

## Selected approach

At the invocation-classification boundary, reject inherited executable or subcommand ambiguity
before accepting an absent or exhausted subcommand index. `_doc_lattice_subcommand_index` already
records the required provenance: it sets `ambiguous=True` whenever a dynamic word could become a
root option, option terminator, or subcommand, including when resolution reaches the end of the
simple command. The caller currently discards that signal by returning early.

Moving the existing ambiguity check ahead of the absent/exhausted-index return makes every
unresolved dynamic command-position path fail with the established `command-position expansion
cannot be scanned safely` reason. It changes no public result shape and requires no shell
evaluation or variable-state tracking.

## Alternatives rejected

- Special-casing a final dynamic word would close the reported examples but duplicate resolver
  semantics and risk missing another path that returns an absent index with ambiguity.
- Raising directly inside `_doc_lattice_subcommand_index` would couple a reusable resolution
  helper to policy. Returning `_ResolvedIndex` provenance and enforcing it at the classification
  boundary keeps the existing separation of responsibilities.
- Resolving preceding shell assignments would require stateful shell evaluation and still could
  not safely handle environment input, command substitution, arrays, or indirect expansion.

## Test strategy

First add scanner regressions for both quoted scalar and unquoted multi-field subcommands and
observe that they incorrectly return an empty result. Add a PR-audit integration regression that
expects the same forms to raise `ConfigError`, proving the policy cannot silently pass them.

After the focused tests fail for the expected reason, reorder the two existing guards in
`_invocation_in_simple_command` and rerun the focused tests. Conservative controls will confirm
that bare `doc-lattice` and effective root help/version remain complete empty scans. Final
verification covers both focused modules, the full project tests with coverage, static checks,
pre-commit, and diff hygiene before committing and pushing without force.
