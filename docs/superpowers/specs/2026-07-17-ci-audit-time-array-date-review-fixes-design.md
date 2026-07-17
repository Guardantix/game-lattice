# CI Audit Time, Array, and Date Review Fixes Design

**Date:** 2026-07-17
**Status:** Approved for autonomous implementation

## Purpose

Close three verified GitHub workflow audit defects:

1. Forced-external `time` forms can hide a Linear or mutating reconcile invocation from the
   pull-request policy.
2. Bash compound array assignments are recursively scanned as subshells, so data elements create
   false policy findings.
3. The YAML loader converts an unquoted ISO date into `datetime.date`, even though GitHub Actions
   treats workflow scalars as strings, and the typed workflow boundary then rejects the document.

## Selected approach

### Bash keyword eligibility and forced-external `time`

Preserve whether each decoded shell word is eligible to be a Bash reserved word. A word remains
eligible only when every character was unquoted and unescaped. The prefix scanner will treat
`time` as the Bash keyword only when that provenance is present. Quoted or escaped spellings such
as `\time`, `'time'`, and `ti""me` will instead reach the existing executable launcher resolver,
which already applies the conservative external `time` grammar.

When the Bash `command` or `exec` builtin resolves a literal `time` target, the prefix scanner
will route directly through the external `time` grammar. This preserves wrapper option handling
while preventing the exposed target from being reclassified as a keyword. Known portable `-p`
and `--` forms continue to reveal their payload; unknown options such as GNU `-f` fail closed.
The same reserved-word provenance will be used for the scanner's other Bash keyword checks so the
new model stays internally consistent.

### Compound array assignments

When an opening parenthesis immediately follows an assignment-shaped word ending in `=` or `+=`,
consume it as Bash compound assignment data without flushing the current simple command. Track
balanced data parentheses so indexed-array arithmetic such as `[1+(2)]` remains data rather than
a nested command group. Quoting, escapes, comments, and ordinary elements are skipped as shell
data.

The array consumer will continue invoking the scanner's existing expansion routines. Command
substitutions and process substitutions in array elements execute at runtime and must remain
visible to policy, while literal elements such as `doc-lattice linear` must not produce findings.
The existing scan-step, recursion, and invocation budgets remain in force.

### Workflow timestamp scalar semantics

Configure each local safe YAML resolver instance to omit only the implicit YAML timestamp rule
before composing or loading a workflow. Unquoted ISO dates and datetimes then load as strings, as
GitHub Actions expects, and flow through the existing string scalar normalization and budgets.

Do not remove the timestamp constructor and do not coerce constructed date objects after loading.
An explicitly tagged `!!timestamp` value will still construct a date-like unsupported scalar and
be rejected by the typed boundary, preserving the loader's explicit-tag safety policy. All other
YAML 1.2 scalar resolution, duplicate-key detection, tag handling, and resource limits remain
unchanged.

## Alternatives rejected

- Matching `\time`, `command time`, and `exec time` directly in source text would duplicate the
  shell lexer and fail on quoting, concatenation, and wrapper options.
- Treating every decoded `time` token as external would break valid Bash keyword forms such as
  `time -p doc-lattice linear`.
- Skipping array text without using the expansion scanners would introduce a new bypass through
  `args=($(doc-lattice linear))` or `args=(<(doc-lattice reconcile --all))`.
- Suppressing every parenthesized region after any prior assignment would hide real subshells
  separated by a command boundary; detection must use the immediately pending assignment word.
- Converting `datetime.date` and `datetime.datetime` values to strings after YAML construction
  would also accept explicit `!!timestamp` tags and blur the boundary between GitHub-compatible
  implicit scalars and intentionally unsupported tagged types.
- Mutating ruamel.yaml's class-level resolver table would leak workflow-specific semantics into
  unrelated YAML consumers. The resolver change must remain local to each parse.

## Test strategy

Each defect starts with a focused regression observed failing:

- scanner and pull-request audit cases cover escaped, `command`, and `exec` external `time`
  spellings with GNU `-f`, plus portable external `-p` controls and ordinary keyword controls;
- scanner and pull-request audit cases prove literal indexed and declared arrays are ignored,
  while command substitutions and process substitutions inside arrays remain visible; and
- workflow parser cases prove unquoted ISO dates and datetimes remain exact strings while an
  explicit `!!timestamp` scalar remains rejected.

Focused suites follow each minimal implementation. Final verification runs the complete pytest
suite, Ruff check and format check, `ty`, typing-boundary validation, version synchronization,
pre-commit, and `git diff --check`. A final requirement audit inspects the complete diff before a
non-force push of the current branch.
