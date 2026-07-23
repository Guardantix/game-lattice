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
when payload resolution proves its effective executable is doc-lattice; every other marker-bearing
simple command fails closed. Unknown heads refuse by construction rather than certify by omission.

"Effective executable is doc-lattice" is the certification predicate throughout this spec, and it
is deliberately broader than "an invocation is emitted." A resolved doc-lattice head that produces
no classified invocation (bare `doc-lattice`, `doc-lattice --help`, `doc-lattice --version`, which
are pinned certified-empty at `tests/test_github_ci_shell_scanner.py:1425`) still certifies,
because resolution proved the executable, not because a subcommand ran.

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

This phase is per-simple-command only. It does not attempt cross-command data flow. The marker must
be genuinely out of band for a smuggle to survive phase 1: a command whose own decoded words spell
the marker (`printf 'doc-lattice reconcile'`, `CMD='doc-lattice reconcile'`) is refused directly by
rule 2, so those are NOT phase-2 examples. Both of these keep the marker out of every decoded word
and are verified to run under real bash:

```bash
printf '%s%s\n' 'doc-' 'lattice reconcile' > task.sh   # no word bears the whole marker -> certifies
bash task.sh                                            # marker-free; the file handoff is invisible
```

```bash
cat > task.sh <<'EOF'
doc-lattice reconcile
EOF
bash task.sh          # marker lives in a heredoc body the phase-1 word model does not retain
```

The first assembles the marker across two words; the second places it in a heredoc body. These stay
DISCLOSED limitations, alongside the pre-existing function/alias/`PATH` and
dynamic-executable-name limitations. Closing them requires source-wide marker taint across
commands, which needs a command-evidence model the tokenizer does not currently retain
(`_ShellWord` carries decoded text and dynamism booleans but no source span or substitution
provenance; heredoc bodies are consumed after the owning command flushes; pipeline operators flush
each command without retaining producer/consumer links). That is a separate structural design, not
this spec. See section 7.

## 3. Certification model

For each simple command extracted by the existing tokenizer and command splitter:

1. Run the existing invocation finder (`_doc_lattice_command_index` and its payload/launcher
   resolution). If it resolves the effective executable to doc-lattice, certify the command,
   whether or not subcommand classification emits an invocation (finding path, unchanged in
   behavior: an emitted invocation is returned; a resolved-but-non-executing form such as bare
   `doc-lattice` or `--help`/`--version` returns no invocation and stays certified).
2. Otherwise, if the simple command bears the ASCII marker (`doc[-_.]+lattice`,
   `re.ASCII | re.IGNORECASE`, unchanged), raise `_ShellScanIncomplete` with a new reason string:
   `"marker-bearing command is not a certified doc-lattice invocation"`.
3. Otherwise (executable not doc-lattice, no marker), return no invocation and stay complete.
   Marker-free commands are never refused.

Step 1's "effective executable is doc-lattice" is exactly the condition under which
`_invocation_in_simple_command` does NOT reach its fallback today: the fallback is called only when
`_doc_lattice_command_index` returns `executable.index is None`
(`src/doc_lattice/github_ci/shell_scanner.py:1730-1731`). Resolved-but-non-executing forms take the
`executable.index is not None` branch and return before the fallback, so the proposed call site
already draws the line at "effective executable is doc-lattice." No change to that branch is needed;
only the fallback body changes.

Comments carry no words after tokenization, so a marker in a comment certifies for free, unchanged.
Assignment-prefix words are part of the simple command, so a marker in a leading assignment refuses
under rule 2 exactly like a marker in an argument; the finding path's own assignment handling is
unchanged.

## 4. Machinery deleted

Dispatcher-specific surface, load-bearing only for the old open-enumeration boundary, is removed:

- `_reject_marker_bearing_dispatcher` is replaced by a small `_reject_marker_bearing_non_invocation`
  called from the same site in `_invocation_in_simple_command` (currently line 1731, reached when
  `executable.index is None`). The replacement reads the aggregate command-marker boolean (section
  6) and raises; it consults no head sets and no resolver-recorded state.
- `_reachable_dispatcher_heads`, `_record_walk_start`, `_normalize_dispatcher_head`, and
  `_shell_dispatcher_runs_inline_command` (the `-c` option walk) are deleted.
- The frozensets `_SHELL_DISPATCHER_HEADS`, `_PLAIN_DISPATCHER_HEADS`, and `_SHELL_EAGER_STOP_OPTIONS`
  are deleted, along with the noexec-purity and cluster grammar those tables fed.
- `_LauncherResolutionState.executable_positions`, `.opaque_tail_start`, `.mark_opaque_tail`, and the
  `_ExecutableCandidate` dataclass (including its `external_lookup` field) are deleted. Every
  `executable_positions.append(...)` call in the finding path (`_doc_lattice_payload_index`,
  `_nested_launcher_payload_index`, `_skip_builtin_wrapper`'s non-wrapper-target bail) is removed:
  those appends existed only to feed the dispatcher rule.
- Only the dispatcher-rule CONSUMER of the round-11 uv head derivation is removed, not the derivation
  itself. `_uv_requirement_executable_name` has two callers: `_reachable_dispatcher_heads` (line
  1864, deleted) and `_nested_launcher_payload_index` (line 2995, the finding path, KEPT). The
  function and the wheel parser (`_wheel_distribution_name`, `_uv_requirement_is_path`) are retained
  for the finding path. Pin both surviving finding-path uses: `uvx
  ./dist/doc_lattice-2.0.0-py3-none-any.whl reconcile` still asserts its reconcile invocation, and
  the nested launcher `uvx ./uv-0.8.0-py3-none-any.whl run doc-lattice linear` still asserts linear.

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
With the head sets gone, the new refusal rule needs an O(1) marker check at command flush. A
per-word boolean that the fallback then iterates over is still an uncharged linear walk of every
word and does not meet that bar. The design instead records two facts:

- a decoded-marker boolean on `_ShellWord`, computed once when the word is finalized in
  `_ShellWordBuilder` from the fully composed decoded literal (proportional to word-building work
  already charged), and
- an aggregate `command_has_marker` boolean on `_CommandScanState`, OR-ed in `_record_word` as each
  word is appended.

`_reject_marker_bearing_non_invocation` then reads `command_has_marker` in O(1) at flush, and a
marker-free command consumes no marker-pass cost.

Correctness constraint: the marker fact must be exact-regex-equivalent to running
`_DISPATCHER_MARKER_RE` on the composed word, not a per-fragment search. A `_ShellWord` is built
from fragments (`doc-"lattice"` is the literal `doc-` plus the quoted `lattice`), and the marker
spans them. Computing the fact on the finalized composed literal is the safe implementation;
per-fragment scanning is not, and if the detector is instead updated incrementally it must either
run while the characters are already being consumed or charge any added segment scan. Pin the
composed-fragment equivalence cases: `echo doc-"lattice"`, `echo DOC_LATTICE`, `echo doc...lattice`
(all markers), and `echo doc-lattıce` (dotless i, stays non-marker under `re.ASCII`). The
case-sensitive `"doc" in literal` shortcut is rejected: the marker is `IGNORECASE`, so it would miss
`DOC-LATTICE`, and it is an unbudgeted scan besides. A raw-authored-text marker fact for phase 2 is
deferred with phase 2; phase 1 needs only the decoded-word fact.

## 7. Deferred to a separate design (phase 2 / later #106)

Cross-command marker taint (file handoff, variable-plus-`eval`, pipeline producer/consumer, heredoc
and herestring bodies, substitution-assembled payloads). These require retaining command evidence
the scanner currently flushes. This is explicitly NOT in this spec and gets its own brainstorm and
spec built around a retained command-evidence / pipeline-summary model. The current disclosed
limitation text stands until then.

## 8. Live expectation rebaseline

Nothing frozen is re-ratified here. The frozen checkpoint (`tests/fixtures/github_ci_checkpoint/`)
and the `successor-evaluation` corpus are IMMUTABLE per the retain decision record and are neither
edited nor consulted; no evaluation harness or results artifact is restored. What changes is the
LIVE scanner expectations in `tests/test_github_ci_shell_scanner.py`. The rows below are the current
live cases whose outcome flips, identified by their existing parametrize `id` (or exact source
string where a case has no distinct id), as the audit trail for the rebaseline.

Governing rule for the full set: every current `DISPATCHER_CERTIFY_CASES` row whose command is
marker-bearing and does not resolve to a doc-lattice executable flips to REFUSE; rows that are
marker-free, marker-in-comment, or a non-ASCII near-marker stay certify. The implementation plan
enumerates the exhaustive per-id rebaseline; the representative flips, by their current parametrize
`id`, are:

- `find dot operand is not a dispatcher` (`find . -name 'doc-lattice*'`; find is not inert, `-exec`
  exists).
- `wrapper argv marker without shell head` (`xargs doc-lattice-formatter --all`) and
  `non-dispatcher head echoes marker text` (`echo doc-lattice reconcile`): marker under a
  non-invocation head.
- `external script file named for doc-lattice` (`bash ./doc-lattice-runner.sh`) and
  `wrapper before external script file` (`nohup bash ./doc-lattice-runner.sh`): script-file forms
  carrying the marker in a word.
- `versioned env requirement never resolves its arguments` (`uvx env@1.0 doc-lattice reconcile`) and
  `versioned time requirement never resolves its arguments` (`uv tool run time@2.0 doc-lattice
  reconcile`).
- The retired provably-inert shell certifications, all currently certify ids that flip:
  `eager help stop before inline command` (`bash --help -c ...`), `eager version stop before inline
  command` (`zsh --version -c ...`), `syntax check noexec before inline command` (`bash -n -c ...`)
  and its `dash noexec`/`noexec cluster`/`reversed noexec cluster`/`set option noexec`/`stacked
  noexec setters`/`dump strings mode`/`dump po strings mode`/`noexec setter after inline selection`
  siblings, `exec wrapper before plain eval head` (`exec eval ...`), `env wrapper before plain source
  head` (`env source ...`), `external time before plain eval head` (`command time -p eval ...`),
  `uv run before plain eval head` (`uv run eval ...`), and the path-qualified plain-head ids
  (`path-qualified eval/source/dot is a path execution`, `command wrapper before path-qualified
  eval`, `uppercase plain head is not the builtin`, `suffixed plain head is not the builtin`). Their
  empirical facts are preserved as expected-refuse rows so the knowledge is not lost, but they are no
  longer load-bearing.

Live certify cases that STAY certify: `marker only in trailing comment`, `marker-free inline
command`, `Unicode dotless i is not an ASCII marker`, and every current
`test_direct_doc_lattice_*_invocation` row that resolves a real doc-lattice invocation (direct,
`uv run`/`uvx`/`uv tool run` launcher forms, `env time --` chains, the wheel-path forms in section
4). Note `command query never executes marker` (`command -v doc-lattice`) DOES flip to refuse: it is
marker-bearing and resolves no doc-lattice executable, and there is no inert exemption.

Live REFUSE cases that stay refuse: every issue #105 `DISPATCHER_FAIL_CLOSED_CASES` row still fails
closed; the mechanism is now the inverted default rather than the dispatcher rule, so the expected
outcome is unchanged even though the code path differs.

## 9. Tests

- Rebuild the two dispatcher case lists in `tests/test_github_ci_shell_scanner.py` into a CERTIFY
  list (real invocations; marker-in-comment; marker-free commands) and a REFUSE list (every
  marker-bearing non-invocation, including each row flipped in section 8 and each retired inert
  shell form as an expected-refuse pin).
- MANDATORY REFUSE regression: the function-shadow form
  `echo() { eval "$CMD"; }` followed by `CMD='doc-lattice reconcile' echo done` must refuse. It is
  the central reason the allowlist was rejected; phase 1 refuses it because the marker is literally
  present in the assignment word, and the test documents that an `echo`-headed allowlist would have
  wrongly certified it.
- Composed-fragment marker equivalence pins (section 6): `echo doc-"lattice"`, `echo DOC_LATTICE`,
  and `echo doc...lattice` refuse; `echo doc-lattıce` (dotless i) stays certify.
- Finding-path pins retained from section 4: `uvx ./dist/doc_lattice-2.0.0-py3-none-any.whl
  reconcile` asserts reconcile; `uvx ./uv-0.8.0-py3-none-any.whl run doc-lattice linear` asserts
  linear; bare `doc-lattice`, `doc-lattice --help`, `doc-lattice --version` stay certified-empty.
- Keep the audit integration cases: a PR run body whose only doc-lattice reference is a
  marker-bearing non-invocation raises `ConfigError` (exit 2) end to end.
- Budget cases: a marker-free command consumes no marker-pass budget; a marker-bearing command is
  detected via the aggregate `command_has_marker` boolean, read O(1) at flush without an unbudgeted
  word walk.
- Full suite green at the repo coverage gate; corpus battery rerun against the section 8 outcomes,
  results kept in the working session, not committed as a fixture.

## 10. Docs and logistics

- README audit-limitations paragraph is rewritten to the two-sided contract: certified means the
  effective executable resolves to doc-lattice; every other marker-bearing command exits 2; and an
  explicit statement that the audit "does not model function/alias/`PATH` shadowing or cross-command
  data flow" (file handoff, variable-plus-`eval`, pipelines, heredoc bodies), both disclosed as
  limitations in those words rather than as a soundness claim.
- ARCHITECTURE.md gains a durable decision entry for the inverted default once implemented.
- No CHANGELOG entry: `ci audit` is unreleased (`[Unreleased]`), consistent with the issue #105 and
  retain-decision precedent.
- Branch off `main` (`fb7547c`) referencing #106. Implementation via subagent-driven development per
  the repo's Fable delegation policy, with the full handoff verification set (pytest, Ruff check and
  format, `ty`, typing boundaries, version sync) plus the corpus battery.
