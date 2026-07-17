# CI Audit Shell, Secret, and Read Consistency Design

**Date:** 2026-07-17
**Status:** Approved for autonomous implementation

## Purpose

Close three verified fail-open paths in the GitHub CI audit:

1. A pull-request workflow can select `doc-lattice linear` through a step shell or inherited
   `defaults.run.shell` while its `run` value contains non-shell configuration text.
2. A GitHub expression can expose the complete secrets context, or a wildcard subset, without
   spelling either protected Linear secret name.
3. Workflow discovery can return bytes from a stale descriptor after the repository path is
   atomically replaced by different content of the same size.

The fixes must preserve deterministic, offline audit behavior and fail closed whenever local
analysis cannot prove that a pull-request command or secret access is unrelated to the protected
Linear operation.

## Selected approach

### Effective pull-request shell

The workflow parser will normalize three optional fields into the typed audit model:

- workflow-level `defaults.run.shell`;
- job-level `defaults.run.shell`; and
- step-level `shell`.

The audit will resolve them with GitHub's precedence, where the step wins over the job and the job
wins over the workflow. For every pull-request `run` step it will first replace the runner's `{0}`
script placeholder with an inert literal and scan the effective shell template for direct
`doc-lattice` invocations. A template such as `doc-lattice linear --config {0}` therefore produces
`PR_LINEAR_INVOCATION` even though the `run` value is configuration rather than Bash.

The `run` body will be scanned only when its execution semantics are provably Bash-compatible:
the ordinary default on a known GitHub-hosted Ubuntu or macOS runner, the exact `bash` or `sh`
built-in selector, or a narrow custom Bash/sh template that passes `{0}` as its final script-file
argument using non-command-string options. Explicit PowerShell, cmd, Python, dynamic runner or
shell expressions, unknown runner defaults, `bash -c`, and other custom semantics will raise a
stable `ConfigError`. If an unsupported shell template directly invokes a prohibited command, the
audit emits that policy finding without attempting to interpret the configuration body as shell.

This deliberately avoids partial PowerShell and cmd parsers. A syntax-specific parser that misses
one invocation form would recreate the same fail-open class under a different shell.

### Whole-context secret expressions

The existing protected-name match remains the first check, including its single canonical trusted
slot exemption. A bounded expression scanner will then inspect unquoted portions of each complete
or unterminated `${{ ... }}` span. Each `secrets` context token must be followed by exactly one
static access:

- `.UNRELATED_NAME`, with optional whitespace around the dot; or
- `['UNRELATED_NAME']`, using GitHub expression single-quoted string syntax.

Standalone context access, `secrets.*`, `secrets[*]`, computed indexes, and chained dereferences
are not provably limited to a static unrelated secret and therefore produce
`LINEAR_SECRET_REFERENCE`. Tokens inside expression string literals and ordinary prose outside an
expression are ignored. Static protected names continue to be detected by the existing
case-insensitive protected-name matcher.

### Descriptor and path consistency

Every bounded workflow or managed-artifact read will carry the complete pre-open stat result into
the shared reader. The reader will compare a stable snapshot containing device, inode, mode, link
count, size, nanosecond modification time, and nanosecond metadata-change time at four points:

1. the pre-open repository path;
2. the opened descriptor before reading;
3. the same descriptor after reading; and
4. the freshly resolved, non-symlink repository path after reading.

An identity mismatch reports a path change; a metadata mismatch reports a content change. The
post-read target must still be a regular non-symlink. This rejects atomic same-size replacement,
replacement between inspection and open, and detectable in-place rewriting while preserving the
existing byte limits and stable diagnostics.

## Alternatives rejected

- Scanning every `run` value as Bash preserves false confidence for PowerShell, cmd, Python, and
  custom interpreters.
- Scanning only the configured shell text still misses invocations in a Bash body and does not
  resolve inherited defaults.
- Implementing minimal PowerShell and cmd tokenizers expands the trusted parser surface without a
  complete grammar or a current product need.
- Matching only `toJSON(secrets)` misses direct standalone contexts, wildcards, other functions,
  and future whole-context consumers.
- Rejecting every scalar containing the word `secrets` would flag documentation and quoted string
  literals that cannot access the GitHub context.
- Re-reading the pathname and comparing bytes adds I/O but still needs identity checks to prove
  which object was read. Advisory locks cannot constrain a concurrent repository writer.

## Test strategy

Each production change begins with a focused regression that is observed failing:

- parser coverage proves all three shell configuration scopes are normalized;
- pull-request audit coverage proves step, job-default, and workflow-default custom templates are
  detected, precedence is honored, and unsupported PowerShell semantics fail closed;
- secret coverage rejects whole-context and wildcard expressions while retaining static unrelated
  dot and bracket references and quoted literals;
- workflow discovery atomically replaces an opened file with different same-size bytes and must
  reject the stale descriptor rather than return the old workflow;
- focused suites run green after each minimal implementation; and
- final verification runs the full pytest suite, Ruff check and format check, `ty`, typing-boundary
  validation, version synchronization, and `git diff --check` before the implementation commit and
  push.
