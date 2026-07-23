# Inverted marker certification for the CI audit shell scanner (issue #106, phase 1)

Date: 2026-07-23

Status: design spec for the first deliverable of issue #106. Non-authoritative until implemented;
durable decisions transfer to [ARCHITECTURE.md](../../../ARCHITECTURE.md) and any release note to
[CHANGELOG.md](../../../CHANGELOG.md) at ship time.

Issue: <https://github.com/Guardantix/doc-lattice/issues/106>

Predecessor context: issue #105 fix (`_reject_marker_bearing_dispatcher`, PR #107) hardened the
inline-dispatcher fail-closed rule through eleven review rounds. The retain decision record
[2026-07-22-mvdan-helper-retain-decision.md](2026-07-22-mvdan-helper-retain-decision.md) fixed
this scanner as the permanent CI audit surface and made its frozen checkpoint immutable.

Baseline for all accounting: `main` at `fb7547c` (after PR #107 merged, which folded rounds 1-11
into `main`).

## 1. Verdict

The scanner's per-simple-command certification default is INVERTED. Today a marker-bearing simple
command is certified clean unless its head matches a recognized dispatcher; the dispatcher set is
an open enumeration of external execution semantics (six shells, restricted variants, `.exe`
forms, uv requirement and wheel grammar, wrapper programs), so any un-enumerated dispatcher-shaped
head is a silent false-safe. After this change a marker-bearing simple command is certified only
when payload resolution asserts it as a doc-lattice invocation; every other marker-bearing simple
command fails closed. Unknown heads refuse by construction rather than certify by omission.

The change deletes the dispatcher enumeration as the security boundary. It does not add a
replacement enumeration. There is NO inert-head / trusted-mention allowlist in this phase: a bare
(slash-free) command name is resolved by the shell through functions, then builtins, then `PATH`
(<https://www.gnu.org/software/bash/manual/html_node/Command-Search-and-Execution.html>), so no
bare head is provably unable to execute its argv. A workflow-defined function can shadow `echo`,
`printf`, or `test`, and an external name such as `grep` or `cat` can resolve to an
attacker-controlled executable. Certifying a marker-bearing command on the strength of its head
would reintroduce a false-safe, empirically:

```bash
echo() { eval "$CMD"; }
CMD='doc-lattice reconcile' echo done   # runs reconcile; head is "echo"
```

verified to execute the smuggled command under real bash. Exemptions are therefore out of scope
until real refusal evidence establishes need, at which point they are added as an explicitly
disclosed "standard, unshadowed command resolution" trust assumption, never as proof.

## 2. Scope boundary

This phase is per-simple-command only. It does not attempt cross-command data flow. Both of these
smuggle a mutating command past the inverted rule and are verified to run under real bash:

```bash
printf '%s\n' 'doc-lattice reconcile' > task.sh   # certifies: printf is not an invocation, but...
bash task.sh                                       # ...marker-free; the file handoff is invisible
```

```bash
CMD='doc-lattice reconcile'   # assignment, marker-bearing -> refuses today under inversion
eval "$CMD"                    # marker-free; but the variable handoff crosses commands
```

These stay DISCLOSED limitations, alongside the pre-existing function/alias/`PATH` and
dynamic-executable-name limitations. Closing them requires source-wide marker taint across
commands, which needs a command-evidence model the tokenizer does not currently retain
(`_ShellWord` carries decoded text and dynamism booleans but no source span or substitution
provenance; heredoc bodies are consumed after the owning command flushes; pipeline operators flush
each command without retaining producer/consumer links). That is a separate structural design, not
this spec. See section 7.

## 3. Certification model

For each simple command extracted by the existing tokenizer and command splitter:

1. Run the existing invocation finder (`_doc_lattice_command_index` and its payload/launcher
   resolution). If it asserts a doc-lattice invocation, certify it as that invocation (finding
   path, unchanged in behavior).
2. Otherwise, if any word of the simple command bears the ASCII marker
   (`doc[-_.]+lattice`, `re.ASCII | re.IGNORECASE`, unchanged), raise `_ShellScanIncomplete` with
   a new reason string: `"marker-bearing command is not a certified doc-lattice invocation"`.
3. Otherwise (no invocation, no marker), return no invocation and stay complete. Marker-free
   commands are never refused.

Comments carry no words after tokenization, so a marker in a comment certifies for free, unchanged.
Assignment-prefix words are part of the simple command, so a marker in a leading assignment refuses
under rule 2 exactly like a marker in an argument; the finding path's own assignment handling is
unchanged.

## 4. Machinery deleted

Dispatcher-specific surface, load-bearing only for the old open-enumeration boundary, is removed:

- `_reject_marker_bearing_dispatcher` is replaced by a small `_reject_marker_bearing_non_invocation`
  called from the same site in `_invocation_in_simple_command` (currently line 1731, reached when
  `executable.index is None`). The replacement scans the simple command's words for the marker and
  raises; it consults no head sets and no resolver-recorded state.
- `_reachable_dispatcher_heads`, `_record_walk_start`, `_normalize_dispatcher_head`, and
  `_shell_dispatcher_runs_inline_command` (the `-c` option walk) are deleted.
- The frozensets `_SHELL_DISPATCHER_HEADS`, `_PLAIN_DISPATCHER_HEADS`, and `_SHELL_EAGER_STOP_OPTIONS`
  are deleted, along with the noexec-purity and cluster grammar those tables fed.
- `_LauncherResolutionState.executable_positions`, `.opaque_tail_start`, `.mark_opaque_tail`, and the
  `_ExecutableCandidate` dataclass (including its `external_lookup` field) are deleted. Every
  `executable_positions.append(...)` call in the finding path (`_doc_lattice_payload_index`,
  `_nested_launcher_payload_index`, `_skip_builtin_wrapper`'s non-wrapper-target bail) is removed:
  those appends existed only to feed the dispatcher rule.
- Round-11 wheel-head-versus-shell derivation used only by the dispatcher rule is removed. The wheel
  distribution-name parser (`_wheel_distribution_name`, `_uv_requirement_is_path`) is RETAINED where
  it feeds the invocation finding path: `uvx ./dist/doc_lattice-2.0.0-py3-none-any.whl reconcile`
  must still assert its reconcile invocation.

## 5. Machinery kept

- The launcher / wrapper / uv resolution grammar (direct heads, `env`/`time` prefixes,
  `command`/`exec`/`builtin` wrappers, `coproc`, `uv run` / `uvx` / `uv tool run`, wheel-path
  doc-lattice resolution, may-disappear speculative handling). Its role changes from proving safety
  to finding invocations; anything it cannot resolve now lands in refuse-by-default.
- `_ResolvedIndex.external_lookup` (line 494) is KEPT. It is consumed by the `coproc` external-lookup
  gate and payload resolution in `_doc_lattice_command_index` (lines 2532-2559), which is the
  finding path, not the deleted dispatcher rule. Only `_ExecutableCandidate.external_lookup` (line
  588) is dispatcher-specific and deleted.
- The subcommand classifier (`linear`/`reconcile` mutating disposition, brace/glob and dynamic
  fail-closed) is unchanged.

## 6. Marker detection and budget

The deleted dispatcher rule gated its charged marker pass behind an uncharged frozenset head test.
With the head sets gone, the new refusal rule needs a cheap marker check that does not reintroduce
an unbudgeted linear scan and is case-correct (the marker is `IGNORECASE`, so a `"doc" in literal`
substring gate is both wrong and unbudgeted). The design records a per-word decoded-marker fact and
an authored-versus-dynamic fact during word construction (`_ShellWord` / `_ShellWordBuilder`), so
`_reject_marker_bearing_non_invocation` reads a precomputed boolean per word instead of rescanning.
Whether marker detection also needs a raw-authored-text fact for phase 2 is deferred with phase 2;
phase 1 only needs the decoded-word marker fact.

## 7. Deferred to a separate design (phase 2 / later #106)

Cross-command marker taint (file handoff, variable-plus-`eval`, pipeline producer/consumer, heredoc
and herestring bodies, substitution-assembled payloads). These require retaining command evidence
the scanner currently flushes. This is explicitly NOT in this spec and gets its own brainstorm and
spec built around a retained command-evidence / pipeline-summary model. The current disclosed
limitation text stands until then.

## 8. Oracle re-ratification

The frozen checkpoint (`tests/fixtures/github_ci_checkpoint/`) and the `successor-evaluation`
corpus are IMMUTABLE per the retain decision record (sections referencing checkpoint immutability).
This spec does not edit them and does not restore any evaluation harness or results artifact. New
production expectations are added to the live scanner tests (`tests/test_github_ci_shell_scanner.py`),
and old case IDs whose live outcome changes are mapped to their new outcome in this document's prose,
below, as the audit trail.

Rows that flip from certify to refuse (all previously certified marker-bearing non-invocations,
now fail-closed because no head is trusted):

- `find . -name 'doc-lattice*'` (find is not inert; `-exec` exists).
- `xargs doc-lattice-formatter --all` and `echo doc-lattice reconcile` (marker under a non-invocation
  head).
- `grep doc-lattice README.md`, `cat docs/doc-lattice-usage.md` (marker-bearing mentions).
- `bash ./doc-lattice-runner.sh`, `nohup bash ./doc-lattice-runner.sh` (script-file forms carrying
  the marker in a word).
- `uvx env@1.0 doc-lattice reconcile` and every unknown-uv-tool marker form.
- The retired provably-inert shell certifications: `bash --help -c 'doc-lattice ...'`,
  `bash -n -c 'doc-lattice ...'` (and `-nc`, `-o noexec`), `exec eval 'doc-lattice ...'`,
  `env source ./doc-lattice-env.sh`, `exec coproc bash -c 'doc-lattice ...'`, `command time -p eval
  'doc-lattice ...'`, path-qualified `./eval 'doc-lattice ...'`. Their empirical facts are preserved
  as expected-refuse rows so the knowledge is not lost, but they are no longer load-bearing.

Rows that remain certify (real invocations, unchanged): direct `doc-lattice reconcile`, launcher and
wrapper forms that resolve to a doc-lattice invocation (`uv run doc-lattice ...`, `env time --
doc-lattice ...`, `uvx ./dist/doc_lattice-2.0.0-py3-none-any.whl reconcile`), marker-in-comment.

Rows that were refuse and stay refuse: every issue #105 dispatcher fail-closed case still fails
closed; the mechanism is now the inverted default rather than the dispatcher rule, so their
expected outcome is unchanged even though the code path differs.

## 9. Tests

- Rebuild the two dispatcher case lists in `tests/test_github_ci_shell_scanner.py` into a CERTIFY
  list (real invocations; marker-in-comment; marker-free commands) and a REFUSE list (every
  marker-bearing non-invocation, including each row flipped in section 8 and each retired inert
  shell form as an expected-refuse pin).
- Keep the audit integration cases: a PR run body whose only doc-lattice reference is a
  marker-bearing non-invocation raises `ConfigError` (exit 2) end to end.
- Budget cases: a marker-free command consumes no marker-pass budget; a marker-bearing command is
  detected via the precomputed word fact without an unbudgeted rescan.
- Full suite green at the repo coverage gate; corpus battery rerun against the section 8 outcomes,
  results kept in the working session, not committed as a fixture.

## 10. Docs and logistics

- README audit-limitations paragraph is rewritten to the two-sided contract: certified means a
  resolved doc-lattice invocation; every other marker-bearing command exits 2; and an explicit,
  honest statement that certification assumes neither function/alias/`PATH` soundness nor
  cross-command data-flow analysis, both disclosed as limitations.
- ARCHITECTURE.md gains a durable decision entry for the inverted default once implemented.
- No CHANGELOG entry: `ci audit` is unreleased (`[Unreleased]`), consistent with the issue #105 and
  retain-decision precedent.
- Branch off `main` (`fb7547c`) referencing #106. Implementation via subagent-driven development per
  the repo's Fable delegation policy, with the full handoff verification set (pytest, Ruff check and
  format, `ty`, typing boundaries, version sync) plus the corpus battery.
