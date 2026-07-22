# Successor Go Helper Implementation Plan (Plan A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dormant Go syntax-certifier helper (`helper/doc-lattice-shell-parser/`)
that parses a batch of Bash sources with the pinned `mvdan.cc/sh/v3` and emits the frozen
doc-lattice wire protocol, verified end to end against the frozen checkpoint fixtures.

**Architecture:** A single static Go binary reads one JSON request on stdin and writes one
JSON response on stdout. It parses each source with `mvdan.cc/sh/v3` under `LangBash`, walks
the AST with a context-carrying walker driven by the frozen certified-construct table,
emits ordered `command_site` and `refusal` events with byte spans, and fails closed on any
syntax it cannot certify. All product policy (launchers, markers, dispatcher, precedence)
stays out of this helper and lands in Plan B's Python engine. This plan produces only the
helper and its Go-side conformance tests; nothing here is wired into the doc-lattice CLI.

**Tech Stack:** Go 1.26.5 (installed at `/usr/local/go/bin/go`, not on PATH; always use the
absolute path), `mvdan.cc/sh/v3@v3.13.1`, Go standard library only otherwise.

**Spec:** `docs/superpowers/specs/2026-07-21-mvdan-helper-evaluation-design.md` (sections
cited as S3.1, S4.2, etc.). **Checkpoint (frozen, read-only):**
`tests/fixtures/github_ci_successor_checkpoint/` (cited as CP). Read the cited spec sections
and CP artifacts before each task; the CP tables and fixtures are the executable contract.

## Global Constraints

- Go module path `doc-lattice.local/shell-parser`; all code under
  `helper/doc-lattice-shell-parser/` at the repo root, outside `src/` (Hatch never ships it).
- Parser pinned exactly: `mvdan.cc/sh/v3 v3.13.1`; `go.sum` hashes must equal
  `CP/pins/parser_pin.json` `sum` and `gomod_sum`. Never bump the pin in this plan.
- Build with `CGO_ENABLED=0`. No goroutines, no clock reads, no environment reads, no
  filesystem or network access in the helper: identical input bytes produce byte-identical
  output (S3.5).
- `RecoverErrors` is prohibited (S3.1): a recovered tree is the clean-wrong-tree channel.
- The helper emits only syntax facts. It never applies the direct-marker regex, resolves
  launchers or subcommands, or evaluates dispatcher or precedence policy (those are Plan B).
- Wire shape is frozen by `CP/protocol/schema.json`; field names and the two event kinds
  (`command_site`, `refusal`) are contract. Never add wire fields not in the schema.
- Reason codes and their scopes come from `CP/tables/reason_codes.json`. The helper emits
  only `terminal` and `subtree-local` scoped codes; `command-local` codes are Python's.
- All numeric bounds come from `CP/limits.json`; never hardcode a bound that disagrees.
- The checkpoint directory is frozen: this plan reads it and never modifies any file under
  `tests/fixtures/github_ci_successor_checkpoint/`. A permanent Python test already asserts
  this; do not touch it.
- No production module under `src/doc_lattice/` changes in this plan. Version stays `2.0.0`.
- Go source: every file has a package comment; exported identifiers have doc comments. No em
  dashes in any drafted content (Go comments, Markdown). Run `gofmt` and `go vet` clean.
- Run Go commands as `/usr/local/go/bin/go ...` from `helper/doc-lattice-shell-parser/`.
- Do not push and do not open a PR; the branch stays local (Plan C opens the PR).
- Baseline commit for this plan: `84c7f4f` (the ratified checkpoint).

## File Structure

```
helper/doc-lattice-shell-parser/
  go.mod                      # module + pinned require
  go.sum                      # pinned hashes (== parser_pin.json)
  main.go                     # stdin/stdout driver, top-level batch loop
  wire.go                     # request/response/event structs + strict JSON
  identity.go                 # parser_version (ReadBuildInfo) + semantic digest
  limits.go                   # bounds loaded from a generated constants file
  gen_limits.go               # //go:generate helper: emits limits_gen.go from CP/limits.json
  limits_gen.go               # generated: numeric bounds (committed)
  gen_tables.go               # //go:generate helper: emits tables_gen.go from CP tables
  tables_gen.go               # generated: certified-construct + reason-code tables (committed)
  parse.go                    # NewParser + StmtsSeq drain-and-dedup
  walk.go                     # context-carrying walker + disposition dispatch
  emit.go                     # command_site + refusal event construction, spans, work_units
  guard.go                    # AST-anchored raw-source heredoc guard
  conformance_test.go         # runs CP/protocol/{conformance,negative,boundary} fixtures
  determinism_test.go         # byte-identical output on repeated runs
  wire_test.go, parse_test.go, walk_test.go, ...  # unit tests per file
scripts/
  build_successor_helper.sh   # builds the CGO_ENABLED=0 binary to a temp path
  check_helper_digest.py      # CI completeness assertion over digest_manifest
```

---

### Task 1: Go module scaffold, wire types, strict request decoding

**Files:**
- Create: `helper/doc-lattice-shell-parser/go.mod`, `go.sum`
- Create: `helper/doc-lattice-shell-parser/wire.go`
- Create: `helper/doc-lattice-shell-parser/main.go`
- Create: `helper/doc-lattice-shell-parser/wire_test.go`
- Create: `scripts/build_successor_helper.sh`

**Interfaces:**
- Produces: `type Request struct{ ProtocolVersion int; Sources []Source }`,
  `type Source struct{ ID int; Source string }`,
  `type Response struct{ ProtocolVersion int; HelperVersion, ParserVersion string; Results []Result }`,
  `type Result struct{ ID int; Events []Event; WorkUnits int }`,
  `type Event` (a tagged union marshaled per the schema; see Task 5/6 for its fields).
- Produces: `func DecodeRequest(data []byte) (*Request, error)` enforcing the S4.2 strict
  rules. Later tasks call it from `main`.

- [ ] **Step 1: Scaffold the module**

```bash
cd helper/doc-lattice-shell-parser
/usr/local/go/bin/go mod init doc-lattice.local/shell-parser
/usr/local/go/bin/go get mvdan.cc/sh/v3@v3.13.1
```

Then verify the hashes match the pin exactly:

```bash
python3 - <<'EOF'
import json
pin = json.load(open("../../tests/fixtures/github_ci_successor_checkpoint/pins/parser_pin.json"))
sums = open("go.sum").read()
assert f"mvdan.cc/sh/v3 {pin['version']} {pin['sum']}" in sums, "ziphash mismatch"
assert f"mvdan.cc/sh/v3 {pin['version']}/go.mod {pin['gomod_sum']}" in sums, "gomod mismatch"
print("go.sum matches parser_pin.json")
EOF
```

If either assertion fails, stop: the environment resolved a different artifact than the pin.

- [ ] **Step 2: Write the failing decoder test**

Create `wire_test.go` (package `main`):

```go
package main

import "testing"

func TestDecodeRequestRejectsBadInputs(t *testing.T) {
	cases := map[string]string{
		"wrong version":     `{"protocol_version":2,"sources":[{"id":0,"source":"true"}]}`,
		"unknown field":     `{"protocol_version":1,"extra":1,"sources":[]}`,
		"duplicate field":   `{"protocol_version":1,"protocol_version":1,"sources":[]}`,
		"empty batch":       `{"protocol_version":1,"sources":[]}`,
		"non-contiguous id": `{"protocol_version":1,"sources":[{"id":0,"source":"a"},{"id":2,"source":"b"}]}`,
		"trailing document": `{"protocol_version":1,"sources":[{"id":0,"source":"a"}]} {}`,
		"bool as int id":    `{"protocol_version":1,"sources":[{"id":true,"source":"a"}]}`,
	}
	for name, body := range cases {
		if _, err := DecodeRequest([]byte(body)); err == nil {
			t.Errorf("%s: expected rejection, got nil", name)
		}
	}
}

func TestDecodeRequestAcceptsValid(t *testing.T) {
	req, err := DecodeRequest([]byte(`{"protocol_version":1,"sources":[{"id":0,"source":"true"},{"id":1,"source":"x"}]}`))
	if err != nil {
		t.Fatalf("valid request rejected: %v", err)
	}
	if req.ProtocolVersion != 1 || len(req.Sources) != 2 || req.Sources[1].ID != 1 {
		t.Fatalf("decoded request wrong: %+v", req)
	}
}
```

- [ ] **Step 3: Run it to verify it fails**

Run: `/usr/local/go/bin/go test ./... -run TestDecodeRequest`
Expected: compile failure (DecodeRequest undefined), which counts as failing.

- [ ] **Step 4: Implement `wire.go`**

Implement the structs and `DecodeRequest`. Requirements enforced by the S4.2 contract, using
`encoding/json` with `Decoder.DisallowUnknownFields()` plus manual passes for what the stdlib
does not catch:

- Reject invalid UTF-8 and lone surrogates before unmarshalling (`utf8.Valid` on the whole
  input; and reject an escaped `\uD800`-style lone surrogate by scanning the decoded string
  values for `0xFFFD` that did not appear literally, or more simply: after decoding, re-encode
  each source string and require `utf8.ValidString`).
- Reject duplicate object keys: wrap the stdlib decode with a check using
  `json.Decoder.Token()` streaming to detect any repeated key at the request and source
  object level (the stdlib silently takes the last).
- Reject `NaN`/`Infinity` (the stdlib already errors on these in JSON; keep a test).
- Require `protocol_version == 1`, `len(Sources) >= 1`, contiguous ids `0..n-1` in order.
- Reject any trailing non-whitespace after the single document (`Decoder.More()` must be
  false after the first decode).
- Enforce `len(Sources) <= max_sources_per_batch` and per-source byte length
  `<= helper_source_cap_bytes` and total request bytes `<= aggregate_request_cap_bytes`
  (numbers come from Task 2's `limits_gen.go`; until then, inline the four values from
  `CP/limits.json` with a `// TODO(task2): source from limits_gen` comment, and remove the
  inline in Task 2). Reject `bool` where `int` is expected by decoding ids into `json.Number`
  and rejecting non-integer or boolean tokens.

Return a plain `error` with a stable message; the driver maps it to exit code 2 with no
stdout (Step 5). Do not leak the offending bytes into the message.

- [ ] **Step 5: Implement the `main.go` driver skeleton**

```go
// Command shell-parser certifies Bash sources for the doc-lattice GitHub CI audit.
package main

import (
	"io"
	"os"
)

func main() {
	os.Exit(run(os.Stdin, os.Stdout, os.Stderr))
}

// run reads one request from in, writes one response to out, and returns the process exit
// code. A malformed request or any internal failure yields exit code 2 and no stdout bytes.
func run(in io.Reader, out, errOut io.Writer) int {
	data, err := io.ReadAll(io.LimitReader(in, aggregateRequestCapBytes+1))
	if err != nil {
		return 2
	}
	req, err := DecodeRequest(data)
	if err != nil {
		return 2
	}
	resp, err := Certify(req) // implemented across later tasks; stub returns empty results now
	if err != nil {
		return 2
	}
	payload, err := EncodeResponse(resp)
	if err != nil {
		return 2
	}
	if _, err := out.Write(payload); err != nil {
		return 2
	}
	return 0
}
```

For this task, stub `Certify` to return a `Response` with one empty-`Events` result per
source (work_units 1) and `EncodeResponse` to marshal compact JSON; both get real bodies in
later tasks. Add `EncodeResponse` in `wire.go` using `json.Marshal` (compact, no BOM).

- [ ] **Step 6: Run tests and gofmt/vet**

Run:
```bash
/usr/local/go/bin/go test ./... -run TestDecodeRequest
/usr/local/go/bin/gofmt -l . && /usr/local/go/bin/go vet ./...
```
Expected: tests PASS; `gofmt -l` prints nothing; vet clean.

- [ ] **Step 7: Write the build script and build once**

Create `scripts/build_successor_helper.sh`:

```bash
#!/usr/bin/env bash
# Build the successor shell-parser helper as a static binary to a caller-provided path.
set -euo pipefail
out="${1:?usage: build_successor_helper.sh OUTPUT_PATH}"
cd "$(dirname "$0")/../helper/doc-lattice-shell-parser"
CGO_ENABLED=0 /usr/local/go/bin/go build -trimpath -o "$out" .
```

Run: `chmod +x scripts/build_successor_helper.sh && scripts/build_successor_helper.sh /tmp/claude-1000/shell-parser && /tmp/claude-1000/shell-parser < /dev/null; echo "exit $?"`
Expected: empty stdin yields exit 2 (empty batch rejected).

- [ ] **Step 8: Commit**

```bash
git add helper/doc-lattice-shell-parser/go.mod helper/doc-lattice-shell-parser/go.sum \
  helper/doc-lattice-shell-parser/wire.go helper/doc-lattice-shell-parser/main.go \
  helper/doc-lattice-shell-parser/wire_test.go scripts/build_successor_helper.sh
git commit -m "feat: scaffold the successor shell-parser helper and strict request decoder"
```

---

### Task 2: Generated bounds and tables

**Files:**
- Create: `helper/doc-lattice-shell-parser/gen_limits.go`, `limits_gen.go`
- Create: `helper/doc-lattice-shell-parser/gen_tables.go`, `tables_gen.go`
- Create: `helper/doc-lattice-shell-parser/tables_test.go`
- Modify: `helper/doc-lattice-shell-parser/wire.go` (remove the Task 1 inline bound TODO)

**Interfaces:**
- Produces: package constants `aggregateRequestCapBytes`, `helperSourceCapBytes`,
  `maxSourcesPerBatch`, `jsonMaxDepth`, `statementCap`, `visitorNodeCap`, `visitorDepthCap`,
  `eventCap`, `maxArgvWordsPerSite`, `maxAssignmentsPerSite` (all `int`, from `CP/limits.json`).
- Produces: `var certifiedConstructs map[constructKey]string` (disposition per `(node, role)`)
  and `var reasonScopes map[string]string` (code to scope), plus `traversalContainerRule`
  and `wildcardRule` docstrings embedded as the generator's provenance. Walk/emit tasks consume
  these.

- [ ] **Step 1: Write the failing table test**

Create `tables_test.go`:

```go
package main

import "testing"

func TestGeneratedBoundsMatchCheckpoint(t *testing.T) {
	if aggregateRequestCapBytes != 8388608 || helperSourceCapBytes != 4194304 {
		t.Fatalf("byte caps drifted: %d %d", aggregateRequestCapBytes, helperSourceCapBytes)
	}
	if maxSourcesPerBatch != 4096 || jsonMaxDepth != 64 {
		t.Fatalf("count/depth caps drifted: %d %d", maxSourcesPerBatch, jsonMaxDepth)
	}
	if statementCap != 65536 || visitorNodeCap != 100000 || visitorDepthCap != 200 || eventCap != 10000 {
		t.Fatalf("visitor caps drifted")
	}
}

func TestReasonScopesAreHelperEmittable(t *testing.T) {
	// The helper may only emit terminal and subtree-local codes; command-local is Python's.
	for code, scope := range reasonScopes {
		if scope != "terminal" && scope != "subtree-local" && scope != "command-local" {
			t.Fatalf("unknown scope %q for %q", scope, code)
		}
	}
	if reasonScopes["syntax-error"] != "terminal" {
		t.Fatalf("syntax-error must be terminal")
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `/usr/local/go/bin/go test ./... -run 'TestGeneratedBounds|TestReasonScopes'`
Expected: compile failure (identifiers undefined).

- [ ] **Step 3: Write the generators**

`gen_limits.go` and `gen_tables.go` are `//go:build ignore` programs invoked by
`//go:generate`. Each reads the frozen JSON from
`../../tests/fixtures/github_ci_successor_checkpoint/...` and writes a `_gen.go` file with a
`// Code generated by go generate; DO NOT EDIT.` header. `gen_limits.go` maps every
`limits.json` key used above to a typed `const`. `gen_tables.go` builds:

- `certifiedConstructs`: from `tables/certified_constructs.json` `rows`, keyed by a
  `constructKey{node, role string}`, value the disposition string. Include the
  `exported_node_types` count in a generated `const certifiedNodeTypeCount` for the walk test
  to assert exhaustiveness.
- `reasonScopes`: from `tables/reason_codes.json`, `code -> scope`.
- Embed `traversal_convention.container_rule` and `.wildcard_rule` as generated string
  consts `traversalContainerRuleDoc` and `wildcardRuleDoc` so the walker's behavior can cite
  them in comments and a test can assert they are non-empty.

Add the directive to a normal (built) file, e.g. top of `tables_gen.go` is generated, so put
the `//go:generate` lines in `main.go`:

```go
//go:generate /usr/local/go/bin/go run gen_limits.go
//go:generate /usr/local/go/bin/go run gen_tables.go
```

Run: `/usr/local/go/bin/go generate ./... && /usr/local/go/bin/gofmt -w limits_gen.go tables_gen.go`

- [ ] **Step 4: Remove the Task 1 inline bounds**

In `wire.go`, replace the four inlined bound literals with the generated constants and delete
the `// TODO(task2)` comment.

- [ ] **Step 5: Run tests, generate-is-clean check, vet**

Run:
```bash
/usr/local/go/bin/go test ./... -run 'TestGeneratedBounds|TestReasonScopes'
/usr/local/go/bin/go generate ./... && git diff --exit-code limits_gen.go tables_gen.go
/usr/local/go/bin/go vet ./...
```
Expected: tests PASS; `git diff --exit-code` clean (regeneration is a no-op); vet clean.

- [ ] **Step 6: Commit**

```bash
git add helper/doc-lattice-shell-parser/gen_limits.go helper/doc-lattice-shell-parser/limits_gen.go \
  helper/doc-lattice-shell-parser/gen_tables.go helper/doc-lattice-shell-parser/tables_gen.go \
  helper/doc-lattice-shell-parser/tables_test.go helper/doc-lattice-shell-parser/wire.go \
  helper/doc-lattice-shell-parser/main.go
git commit -m "feat: generate frozen bounds and certifier tables into the helper"
```

---

### Task 3: Parse strategy and StmtsSeq drain-and-dedup

**Files:**
- Create: `helper/doc-lattice-shell-parser/parse.go`, `parse_test.go`

**Interfaces:**
- Produces: `func parseStatements(src string) (stmts []*syntax.Stmt, refusal *rawRefusal)`
  where `rawRefusal` is `struct{ code string; startByte, endByte int }`. On a parse error it
  returns the statements completed before the error plus a terminal `syntax-error` refusal at
  the first error position; on clean parse it returns all statements and a nil refusal.

- [ ] **Step 1: Write the failing test (the S3.1 canonical fixture)**

Create `parse_test.go`:

```go
package main

import "testing"

func TestParseCanonicalDrainAndDedup(t *testing.T) {
	stmts, refusal := parseStatements(`doc-lattice check; echo "$(`)
	if len(stmts) != 1 {
		t.Fatalf("want 1 completed statement, got %d", len(stmts))
	}
	if refusal == nil || refusal.code != "syntax-error" {
		t.Fatalf("want a terminal syntax-error refusal, got %+v", refusal)
	}
	if refusal.startByte < 0 || refusal.endByte < refusal.startByte {
		t.Fatalf("refusal span invalid: %+v", refusal)
	}
}

func TestParseCleanHasNoRefusal(t *testing.T) {
	stmts, refusal := parseStatements(`doc-lattice check; doc-lattice lint`)
	if len(stmts) != 2 || refusal != nil {
		t.Fatalf("clean parse wrong: %d stmts, refusal %+v", len(stmts), refusal)
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `/usr/local/go/bin/go test ./... -run TestParse`
Expected: compile failure (parseStatements undefined).

- [ ] **Step 3: Implement `parse.go`**

```go
package main

import (
	"strings"

	"mvdan.cc/sh/v3/syntax"
)

type rawRefusal struct {
	code               string
	startByte, endByte int
}

// parseStatements parses src as Bash and returns the statements completed before any parse
// error, plus a terminal refusal at the first error when parsing fails. RecoverErrors is
// never used (S3.1): a recovered tree is a clean-looking wrong tree. The iterator is drained
// to completion after the first error and the error is deduplicated, because the pinned
// parser can yield (stmt, err) and then (nil, err) again, and calling yield after it returns
// false panics.
func parseStatements(src string) ([]*syntax.Stmt, *rawRefusal) {
	parser := syntax.NewParser(syntax.Variant(syntax.LangBash))
	var stmts []*syntax.Stmt
	var refusal *rawRefusal
	reader := strings.NewReader(src)
	for stmt, err := range parser.StmtsSeq(reader) {
		if err != nil {
			if refusal == nil {
				start, end := errorSpan(err, len(src))
				refusal = &rawRefusal{code: "syntax-error", startByte: start, endByte: end}
			}
			continue // drain without accepting the co-yielded statement
		}
		if refusal != nil {
			continue // never accept a statement yielded after the first error
		}
		stmts = append(stmts, stmt)
	}
	return stmts, refusal
}

// errorSpan extracts the byte offset of a parse error, clamped to the source length.
func errorSpan(err error, srcLen int) (int, int) {
	var pos syntax.Pos
	switch e := err.(type) {
	case syntax.ParseError:
		pos = e.Pos
	case syntax.LangError:
		pos = e.Pos
	}
	off := int(pos.Offset())
	if !pos.IsValid() || off < 0 || off > srcLen {
		off = srcLen
	}
	return off, off
}
```

Verify against the pinned API that `StmtsSeq` returns a `func(func(*syntax.Stmt, error) bool)`
range-over-func iterator (Go 1.23+ range-over-func). If the pinned version exposes
`Stmts(r, fn)` callback style instead, adapt: call `parser.Stmts(reader, func(s) bool{...})`
and capture the terminal error via `parser.Err` semantics; keep the same drain-and-dedup
contract and the same canonical-fixture test. Confirm the exact signature with
`/usr/local/go/bin/go doc mvdan.cc/sh/v3/syntax.Parser.StmtsSeq` before writing.

- [ ] **Step 4: Run tests**

Run: `/usr/local/go/bin/go test ./... -run TestParse`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add helper/doc-lattice-shell-parser/parse.go helper/doc-lattice-shell-parser/parse_test.go
git commit -m "feat: parse with the pinned bash grammar and drain-and-dedup on error"
```

---

### Task 4: Context-carrying walker and disposition dispatch

**Files:**
- Create: `helper/doc-lattice-shell-parser/walk.go`, `walk_test.go`

**Interfaces:**
- Consumes: `certifiedConstructs`, `visitorNodeCap`, `visitorDepthCap`, `eventCap` (Task 2);
  `[]*syntax.Stmt` (Task 3).
- Produces: `func walk(stmts []*syntax.Stmt, src string) (sites []commandSite, refusals []rawRefusal, work int)`
  where `commandSite` and its word/assignment sub-structs are defined here (fields finalized
  in Task 5). The walker collects events during traversal and the caller stable-sorts by span.

- [ ] **Step 1: Write the failing walk test**

Create `walk_test.go`:

```go
package main

import "testing"

func TestWalkCertifiesSimpleCommand(t *testing.T) {
	stmts, refusal := parseStatements(`doc-lattice check`)
	if refusal != nil {
		t.Fatalf("unexpected refusal: %+v", refusal)
	}
	sites, refusals, _ := walk(stmts, `doc-lattice check`)
	if len(sites) != 1 || len(refusals) != 0 {
		t.Fatalf("want 1 site 0 refusals, got %d sites %d refusals", len(sites), len(refusals))
	}
	if len(sites[0].argv) != 2 {
		t.Fatalf("want 2 argv words, got %d", len(sites[0].argv))
	}
}

func TestWalkRefusesUnmodeledConstruct(t *testing.T) {
	// A process substitution hosts an execution source the floor does not model: refuse.
	stmts, refusal := parseStatements(`cat <(doc-lattice check)`)
	if refusal != nil {
		t.Fatalf("unexpected parse refusal: %+v", refusal)
	}
	_, refusals, _ := walk(stmts, `cat <(doc-lattice check)`)
	if len(refusals) == 0 {
		t.Fatalf("want a refusal for the unmodeled ProcSubst")
	}
}

func TestWalkTraversesCommandSubstInArgv(t *testing.T) {
	// A CmdSubst reached as a direct argv word-part is traversed, not refused.
	src := `echo "$(doc-lattice lint)"`
	stmts, _ := parseStatements(src)
	sites, refusals, _ := walk(stmts, src)
	if len(refusals) != 0 {
		t.Fatalf("argv-embedded CmdSubst must not refuse, got %+v", refusals)
	}
	// echo ... plus the nested doc-lattice lint == two command sites.
	if len(sites) != 2 {
		t.Fatalf("want 2 sites (echo, nested doc-lattice lint), got %d", len(sites))
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `/usr/local/go/bin/go test ./... -run TestWalk`
Expected: compile failure (walk undefined).

- [ ] **Step 3: Implement `walk.go`**

Implement a custom recursive walker (not `syntax.Walk`, whose visit order is AST order, not
source order). Honor the two frozen rules embedded in Task 2 (`traversalContainerRuleDoc`,
`wildcardRuleDoc`):

- A node with a `traverse` disposition consumes its child words, word-parts, and role-covered
  children directly in role, and recurses into nested statement-bearing parts (a `CmdSubst`
  inside a `Word`) without re-dispatching those children through the table.
- A `(node, "*")` wildcard row applies only when the node is encountered in a role no explicit
  `(node, role)` row covers.

Structure: a `walker` struct carrying `src string`, accumulating `sites`, `refusals`, `work`,
and `depth`. Dispatch on `(nodeTypeName, role)` against `certifiedConstructs`:
- `traverse`: descend per the container rule; for a `*syntax.CallExpr` emit a `commandSite`
  (built in Task 5) from its `Args` and `Assigns`, then recurse into each arg word's parts to
  find nested statement-bearing constructs.
- `ignore`: stop; the subtree provably hosts no execution source.
- `refuse`: append a refusal at the node's span; its scope comes from `reasonScopes` for the
  mapped code (Task 6 finalizes the code selection; for this task use `"unsupported-construct"`
  for every refuse row and refine in Task 6).

Charge `work++` per visited node and per emitted event; if `work > visitorNodeCap` or
`depth > visitorDepthCap` or `len(events) > eventCap`, append a terminal cap refusal
(`code "visitor-node-cap"` etc. per `reasonScopes`) and stop the whole walk. Determine a
node's Go type name via a type switch; map it to the table's node names (e.g. `*syntax.CallExpr`
to `"CallExpr"`). Roles are assigned by the parent as it descends (argv, value, redirect-target,
heredoc-body, condition, etc.), matching the `role` column of the table.

After the walk, the caller (Task 5's `Certify`) stable-sorts `sites` and `refusals` together by
`(startByte, kindOrdinal, ordinal)` so emission is source-ordered even though `syntax.Walk`
order would not be.

- [ ] **Step 4: Run tests**

Run: `/usr/local/go/bin/go test ./... -run TestWalk`
Expected: all three PASS.

- [ ] **Step 5: Commit**

```bash
git add helper/doc-lattice-shell-parser/walk.go helper/doc-lattice-shell-parser/walk_test.go
git commit -m "feat: walk the AST in source order with table-driven dispositions"
```

---

### Task 5: Command-site emission with word and assignment facts

**Files:**
- Create: `helper/doc-lattice-shell-parser/emit.go`, `emit_test.go`
- Modify: `helper/doc-lattice-shell-parser/wire.go` (finalize `Event` marshaling)
- Modify: `helper/doc-lattice-shell-parser/main.go` (wire `Certify` to walk + emit)

**Interfaces:**
- Consumes: `commandSite` (Task 4), `parseStatements` (Task 3).
- Produces: the finalized wire `Event` (command_site form) with `ordinal`, `start_byte`,
  `end_byte`, `assignments []Assignment`, `argv []Word`; `Word{Text *string; Single bool;
  StartByte, EndByte int}`; `Assignment{Name string; ValueKnown bool; StartByte, EndByte int}`.
  `Certify(*Request) (*Response, error)` fully implemented for the non-refusal path.

- [ ] **Step 1: Write the failing emission test**

Create `emit_test.go` asserting exact facts for a multi-prefix command, matching the frozen
`CP/protocol/conformance/multi-prefix.json` values:

```go
package main

import "testing"

func TestEmitMultiPrefix(t *testing.T) {
	resp, err := Certify(mustRequest(t, `A=1 B=$X doc-lattice check`))
	if err != nil {
		t.Fatal(err)
	}
	events := resp.Results[0].Events
	site := findCommandSite(t, events)
	if site.StartByte != 0 || site.EndByte != 26 {
		t.Fatalf("site span %d..%d", site.StartByte, site.EndByte)
	}
	if len(site.Assignments) != 2 {
		t.Fatalf("want 2 assignments, got %d", len(site.Assignments))
	}
	if site.Assignments[0].Name != "A" || !site.Assignments[0].ValueKnown ||
		site.Assignments[0].StartByte != 0 || site.Assignments[0].EndByte != 3 {
		t.Fatalf("assignment A wrong: %+v", site.Assignments[0])
	}
	if site.Assignments[1].Name != "B" || site.Assignments[1].ValueKnown ||
		site.Assignments[1].StartByte != 4 || site.Assignments[1].EndByte != 8 {
		t.Fatalf("assignment B wrong: %+v", site.Assignments[1])
	}
	if site.Argv[0].Text == nil || *site.Argv[0].Text != "doc-lattice" || !site.Argv[0].Single {
		t.Fatalf("argv[0] wrong: %+v", site.Argv[0])
	}
	if site.Argv[1].Text == nil || *site.Argv[1].Text != "check" {
		t.Fatalf("argv[1] wrong: %+v", site.Argv[1])
	}
}
```

(`mustRequest`, `findCommandSite` are small test helpers you write in `emit_test.go`.)

- [ ] **Step 2: Run to verify it fails**

Run: `/usr/local/go/bin/go test ./... -run TestEmit`
Expected: fail (Certify still stubbed / spans wrong).

- [ ] **Step 3: Implement `emit.go` and finalize `Certify`**

Emit a `commandSite` from a `*syntax.CallExpr`:
- `ordinal`: a per-source counter in emission order.
- span: `expr.Pos().Offset()` to `expr.End().Offset()`, validated with `Pos.IsValid()` and
  `0 <= start <= end <= len(src)`; an invalid position aborts the whole batch as a protocol
  error (return a non-nil error from `Certify`, which the driver maps to exit 2).
- assignments: for each `*syntax.Assign` in `expr.Assigns`, `Name = assign.Name.Value`,
  `ValueKnown = wordIsStaticLiteral(assign.Value)`, span from the assign node.
- argv: for each `*syntax.Word` in `expr.Args`, build a `Word`:
  - `Text`: the exact final single argv string when statically provable, else nil. Compute
    with a helper `literalWord(word) (string, bool)` that returns the concatenation of
    `*syntax.Lit` and single-quoted parts and false if any part is a parameter/command/arith
    expansion, unquoted glob, brace, tilde, or process substitution.
  - `Single`: whether the word yields exactly one field. A double-quoted word is single; an
    unquoted word containing a glob/brace or an unquoted `$@`/`${arr[@]}` is not. Enforce the
    IR invariant: `Text != nil` implies `Single == true`.
  - spans from the word node, validated as above.

Marshal `Event` in `wire.go` as a tagged object: command_site emits
`{"kind":"command_site","ordinal":..,"start_byte":..,"end_byte":..,"assignments":[..],"argv":[..]}`;
`Word.Text` marshals as JSON null when nil (use `*string`). Wire `Certify` to iterate sources,
call `parseStatements` then `walk`, stable-sort events by span, and assemble `Result`s with a
positive `work_units` from the walk's `work` counter (plus a per-source base of 1).

- [ ] **Step 4: Run tests**

Run: `/usr/local/go/bin/go test ./... -run TestEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helper/doc-lattice-shell-parser/emit.go helper/doc-lattice-shell-parser/emit_test.go \
  helper/doc-lattice-shell-parser/wire.go helper/doc-lattice-shell-parser/main.go
git commit -m "feat: emit command sites with word and assignment facts"
```

---

### Task 6: Refusal emission with owned codes and scopes

**Files:**
- Modify: `helper/doc-lattice-shell-parser/walk.go` (map refuse dispositions to owned codes)
- Modify: `helper/doc-lattice-shell-parser/emit.go` (refusal event marshaling)
- Create: `helper/doc-lattice-shell-parser/refusal_test.go`

**Interfaces:**
- Produces: the refusal wire form `{"kind":"refusal","code":..,"start_byte":..,"end_byte":..}`
  where `code` is a `terminal` or `subtree-local` scoped code from `reasonScopes`. The helper
  never emits a `command-local` code.

- [ ] **Step 1: Write the failing refusal test**

Create `refusal_test.go`:

```go
package main

import "testing"

func TestRefusalCodesAreHelperScoped(t *testing.T) {
	src := `cat <(doc-lattice check)` // ProcSubst: unmodeled construct
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	got := refusalCodes(t, resp.Results[0].Events)
	if len(got) == 0 {
		t.Fatalf("want a refusal event")
	}
	for _, code := range got {
		if reasonScopes[code] == "command-local" {
			t.Fatalf("helper emitted a command-local code %q", code)
		}
		if reasonScopes[code] == "" {
			t.Fatalf("helper emitted an unknown code %q", code)
		}
	}
}

func TestTerminalRefusalIsLast(t *testing.T) {
	src := `doc-lattice check; echo "$(`
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	events := resp.Results[0].Events
	last := events[len(events)-1]
	if last.Kind != "refusal" || last.Code != "syntax-error" {
		t.Fatalf("terminal refusal must be last, got %+v", last)
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `/usr/local/go/bin/go test ./... -run 'TestRefusal|TestTerminal'`
Expected: fail (refuse rows still all emit the Task 4 placeholder code, or marshaling missing).

- [ ] **Step 3: Map refuse dispositions to their owned codes**

Extend the certified-construct table generation (Task 2 `gen_tables.go`) so each `refuse` row
carries the reason `code` the walker should emit, then regenerate. Add a `reason_code` field
per refuse row in the generated `certifiedConstructs` value (change it from a bare disposition
string to a small struct `{disposition, code string}`). Map:
- unmodeled statement-bearing constructs (ProcSubst, ArithmCmd, etc.) to `unsupported-construct`
  (terminal).
- redirect/expansion subtree-local cases to their `redirect-unsupported` / `expansion-unsupported`
  codes (subtree-local) per `reason_codes.json`.
- cap breaches to `source-cap` / `statement-cap` / `depth-cap` / `work-cap` / `event-cap`
  (terminal).
Confirm each chosen code exists in `reason_codes.json` with the expected scope; the test above
enforces "never command-local". Marshal the refusal `Event` form in `emit.go`.

- [ ] **Step 4: Run tests, regenerate-clean, vet**

Run:
```bash
/usr/local/go/bin/go generate ./... && git diff --exit-code tables_gen.go
/usr/local/go/bin/go test ./... -run 'TestRefusal|TestTerminal|TestWalk|TestEmit'
/usr/local/go/bin/go vet ./...
```
Expected: regeneration clean; tests PASS; vet clean.

- [ ] **Step 5: Commit**

```bash
git add helper/doc-lattice-shell-parser/walk.go helper/doc-lattice-shell-parser/emit.go \
  helper/doc-lattice-shell-parser/gen_tables.go helper/doc-lattice-shell-parser/tables_gen.go \
  helper/doc-lattice-shell-parser/refusal_test.go
git commit -m "feat: emit fail-closed refusals with owned codes and scopes"
```

---

### Task 7: AST-anchored raw-source heredoc guard

**Files:**
- Create: `helper/doc-lattice-shell-parser/guard.go`, `guard_test.go`
- Modify: `helper/doc-lattice-shell-parser/emit.go` (invoke the guard before certifying a source)

**Interfaces:**
- Produces: `func heredocGuard(src string, stmts []*syntax.Stmt) *rawRefusal` returning a
  terminal `parser-divergence-guard` refusal when an unquoted-delimiter heredoc body contains a
  backslash-newline continuation that changes tokenization, else nil.

- [ ] **Step 1: Write the failing guard test (the permanent regression)**

Create `guard_test.go`, pinning the benchmark false-safe verbatim:

```go
package main

import "testing"

func TestHeredocGuardCatchesBackslashNewline(t *testing.T) {
	src := "cat <<EOF\n$\\\n(doc-lattice linear)\nEOF\n"
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	// The forbidden outcome is a clean-empty certify. Require either a refusal or a
	// correctly-emitted site; never zero events with zero refusals.
	events := resp.Results[0].Events
	if len(events) == 0 {
		t.Fatalf("clean-empty certification of the heredoc false-safe is forbidden")
	}
	if !hasRefusalCode(events, "parser-divergence-guard") {
		t.Fatalf("want a parser-divergence-guard refusal, got %+v", events)
	}
}

func TestHeredocGuardAllowsQuotedDelimiter(t *testing.T) {
	// A quoted delimiter is inert data; the guard must not fire.
	src := "cat <<'EOF'\n$\\\n(doc-lattice linear)\nEOF\n"
	if got := heredocGuard(src, mustParse(t, src)); got != nil {
		t.Fatalf("quoted-delimiter heredoc must not trip the guard, got %+v", got)
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `/usr/local/go/bin/go test ./... -run TestHeredoc`
Expected: fail.

- [ ] **Step 3: Implement `guard.go`**

After a source parses, locate confirmed unquoted-delimiter heredoc bodies from the AST
(`*syntax.Redirect` with `Op == syntax.Hdoc` or `syntax.DashHdoc` and an unquoted `Hdoc`
delimiter word), take each body's byte span, and inspect the original `src` bytes within it for
a backslash immediately followed by a newline. A global textual scan is rejected: it would
recreate a shell lexer and over-refuse comments and quoted data. On a hit, return a terminal
`parser-divergence-guard` refusal anchored at the backslash offset. `heredocGuard` runs in
`emit.go` before the walk certifies a source; if it fires, the source's only event is that
terminal refusal.

Confirm the pinned API's heredoc representation with
`/usr/local/go/bin/go doc mvdan.cc/sh/v3/syntax.Redirect` and
`... syntax.Redirect.Hdoc` before writing; adjust the field/op names to the pinned version.

- [ ] **Step 4: Run tests**

Run: `/usr/local/go/bin/go test ./... -run TestHeredoc`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add helper/doc-lattice-shell-parser/guard.go helper/doc-lattice-shell-parser/guard_test.go \
  helper/doc-lattice-shell-parser/emit.go
git commit -m "feat: add the AST-anchored heredoc backslash-newline guard"
```

---

### Task 8: Layered bounds enforcement

**Files:**
- Modify: `helper/doc-lattice-shell-parser/emit.go` (per-source byte cap; statement cap)
- Modify: `helper/doc-lattice-shell-parser/walk.go` (node/depth/event caps, if not already)
- Create: `helper/doc-lattice-shell-parser/bounds_test.go`

**Interfaces:**
- Produces: a per-source pre-parse byte cap check emitting a terminal `source-cap` refusal, and
  a statement-cap check emitting `statement-cap`, both from `limits_gen.go`.

- [ ] **Step 1: Write the failing bounds test**

```go
package main

import (
	"strings"
	"testing"
)

func TestSourceOverByteCapRefuses(t *testing.T) {
	big := strings.Repeat("a", helperSourceCapBytes+1)
	resp, err := Certify(mustRequest(t, big))
	if err != nil {
		t.Fatal(err)
	}
	if !hasRefusalCode(resp.Results[0].Events, "source-cap") {
		t.Fatalf("want a source-cap refusal for an over-cap source")
	}
}

func TestStatementStormRefuses(t *testing.T) {
	src := strings.Repeat("true\n", statementCap+1)
	resp, err := Certify(mustRequest(t, src))
	if err != nil {
		t.Fatal(err)
	}
	if !hasRefusalCode(resp.Results[0].Events, "statement-cap") {
		t.Fatalf("want a statement-cap refusal")
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `/usr/local/go/bin/go test ./... -run 'TestSourceOver|TestStatementStorm'`
Expected: fail.

- [ ] **Step 3: Implement the layered checks**

In `Certify`, before parsing a source, if `len(src) > helperSourceCapBytes` emit only a
terminal `source-cap` refusal for that source and skip parsing. After parsing, if
`len(stmts) > statementCap` emit only a terminal `statement-cap` refusal. Confirm the walk's
node/depth/event caps (Task 4) already emit their terminal cap codes; if any is missing, add
it here. Every cap breach yields a single terminal refusal and no sites for that source.

Note honestly in a comment (per S3.5): the visitor node/depth caps bound the walk, not the
parser's construction of one deeply nested AST; the byte cap plus the process-level deadline
and memory ceiling (Plan B's supervisor and Plan C's RSS gate) are what bound parser
construction. Do not claim otherwise.

- [ ] **Step 4: Run tests**

Run: `/usr/local/go/bin/go test ./... -run 'TestSourceOver|TestStatementStorm'`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helper/doc-lattice-shell-parser/emit.go helper/doc-lattice-shell-parser/walk.go \
  helper/doc-lattice-shell-parser/bounds_test.go
git commit -m "feat: enforce layered source, statement, and visitor bounds"
```

---

### Task 9: Helper identity digest and completeness check

**Files:**
- Create: `helper/doc-lattice-shell-parser/identity.go`, `identity_test.go`
- Create: `scripts/check_helper_digest.py`
- Create: `tests/test_helper_digest.py`

**Interfaces:**
- Produces: `func helperVersion() string` (a build-embedded semantic digest over the
  `digest_manifest.json` include set) and `func parserVersion() string` (from
  `runtime/debug.ReadBuildInfo`, formatted `mvdan.cc/sh/v3@v3.13.1`). `Certify` fills both into
  the `Response`.

- [ ] **Step 1: Write the failing identity tests**

Go side, `identity_test.go`:

```go
package main

import (
	"regexp"
	"testing"
)

func TestParserVersionMatchesPin(t *testing.T) {
	if got := parserVersion(); got != "mvdan.cc/sh/v3@v3.13.1" {
		t.Fatalf("parser version %q", got)
	}
}

func TestHelperVersionIsHex(t *testing.T) {
	if !regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(helperVersion()) {
		t.Fatalf("helper version not a 64-hex digest: %q", helperVersion())
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `/usr/local/go/bin/go test ./... -run 'TestParserVersion|TestHelperVersion'`
Expected: fail.

- [ ] **Step 3: Implement `identity.go`**

`parserVersion` reads `runtime/debug.ReadBuildInfo`, finds the `mvdan.cc/sh/v3` dependency, and
returns `module + "@" + version`; if absent (e.g. `go run` without module info), fall back to
the pinned literal so tests pass, with a comment that release builds always carry build info.
`helperVersion` computes a sha256 over the digest-input manifest: at build time the digest is
computed by the `check_helper_digest.py` generator and embedded via `-ldflags -X`. For the
in-repo build, compute it deterministically from the manifest's include set at init using
`embed` is not possible for arbitrary repo paths, so instead: embed a generated constant
`helperDigest` produced by a new `//go:generate` step that runs `check_helper_digest.py --emit-go`.
Keep it simple: generate `digest_gen.go` with `const helperDigest = "<64hex>"`, and
`helperVersion()` returns it.

- [ ] **Step 4: Implement `scripts/check_helper_digest.py`**

A maintained Python script (module docstring, Google-style docstrings, Ruff-clean, no
`typing.Any`) that:
- reads `CP/protocol/digest_manifest.json`;
- expands `include` minus `exclude_globs` over the repo, in path-lexicographic order;
- computes the sha256 over newline-joined `(path, file-sha256)` pairs (the manifest's `digest`
  definition);
- `--emit-go` writes `helper/doc-lattice-shell-parser/digest_gen.go` with the constant;
- default mode asserts every non-test `.go` file under `helper/doc-lattice-shell-parser/` is
  covered by `include` minus `exclude_globs` (the frozen `completeness_rule`), exiting nonzero
  with the uncovered path list otherwise.

- [ ] **Step 5: Write `tests/test_helper_digest.py`**

```python
"""The helper identity digest covers every compiled Go source (S4.3 completeness_rule)."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_digest_manifest_covers_all_compiled_go():
    """Every non-test .go file under the helper module is inside the digest include set."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_helper_digest.py")],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 6: Generate, run both test sides, regenerate-clean**

Run:
```bash
cd helper/doc-lattice-shell-parser && /usr/local/go/bin/go generate ./... && cd ../..
git diff --exit-code helper/doc-lattice-shell-parser/digest_gen.go
cd helper/doc-lattice-shell-parser && /usr/local/go/bin/go test ./... -run 'TestParserVersion|TestHelperVersion' && cd ../..
env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest tests/test_helper_digest.py -q --no-cov
```
Expected: regeneration clean; Go tests PASS; Python test PASS.

- [ ] **Step 7: Commit**

```bash
git add helper/doc-lattice-shell-parser/identity.go helper/doc-lattice-shell-parser/digest_gen.go \
  helper/doc-lattice-shell-parser/identity_test.go scripts/check_helper_digest.py tests/test_helper_digest.py \
  helper/doc-lattice-shell-parser/main.go
git commit -m "feat: compute the helper identity digest and enforce source coverage"
```

---

### Task 10: End-to-end conformance, negative, and boundary harness

**Files:**
- Create: `helper/doc-lattice-shell-parser/conformance_test.go`, `determinism_test.go`

**Interfaces:**
- Consumes: every fixture under `CP/protocol/conformance/`, `CP/protocol/negative/`,
  `CP/protocol/boundary/`; `run` and `Certify` (Tasks 1, 5).

- [ ] **Step 1: Write the conformance harness**

`conformance_test.go` reads each `conformance/*.json` (`{"request":..,"response":..}`), feeds
`request.sources` through `Certify`, and compares the emitted events per result to
`response.results` for the fields the helper owns: event kinds, ordinals, spans, word
`text`/`single`, assignment `name`/`value_known`/spans, and refusal `code`. It ignores
`helper_version` and `work_units` values (placeholders per the frozen README), asserting only
that `work_units > 0`. Load fixtures via a relative path to the frozen checkpoint:

```go
package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

const checkpointProtocol = "../../tests/fixtures/github_ci_successor_checkpoint/protocol"

func TestConformanceFixtures(t *testing.T) {
	dir := filepath.Join(checkpointProtocol, "conformance")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		e := e
		t.Run(e.Name(), func(t *testing.T) {
			var fixture struct {
				Request  json.RawMessage `json:"request"`
				Response Response        `json:"response"`
			}
			data, err := os.ReadFile(filepath.Join(dir, e.Name()))
			if err != nil {
				t.Fatal(err)
			}
			if err := json.Unmarshal(data, &fixture); err != nil {
				t.Fatal(err)
			}
			req, err := DecodeRequest(fixture.Request)
			if err != nil {
				t.Fatalf("fixture request rejected: %v", err)
			}
			got, err := Certify(req)
			if err != nil {
				t.Fatalf("certify failed: %v", err)
			}
			assertResultsEqual(t, fixture.Response.Results, got.Results) // helper-owned fields only
		})
	}
}
```

Write `assertResultsEqual` to compare only the helper-owned fields listed above. It must fail
if any span, kind, ordinal, word fact, assignment fact, or refusal code differs.

- [ ] **Step 2: Write the negative and boundary harness**

Add to `conformance_test.go`: iterate `negative/*.json` and `negative/*.bin`, feed the raw
bytes through `run` (via an in-memory reader), and require exit code 2 (rejected). Iterate
`boundary/*.json` and require exit code 0 with a well-formed response (accepted at limit).
`escaped-lone-surrogate.json` must be rejected; `max-length-four-byte-source.json` and
`source-count-at-limit.json` must be accepted.

- [ ] **Step 3: Write the determinism test**

`determinism_test.go`: run `Certify` twice on a representative multi-source request (pull a few
sources from the conformance fixtures) and assert the two marshaled responses are byte-identical.

- [ ] **Step 4: Run to verify they fail-then-pass**

Run: `/usr/local/go/bin/go test ./... -run 'TestConformance|TestNegative|TestBoundary|TestDeterminism' -v`
Expected: initially any mismatch fails; fix real emission bugs the fixtures surface (not the
frozen fixtures, which are immutable) until all PASS. If a fixture reveals a genuine helper
defect, fix the helper; if it reveals a spec/fixture contradiction you cannot resolve in the
helper, STOP and escalate rather than editing the frozen checkpoint.

- [ ] **Step 5: Full Go verification**

Run:
```bash
cd helper/doc-lattice-shell-parser
/usr/local/go/bin/go test ./...
/usr/local/go/bin/gofmt -l . && /usr/local/go/bin/go vet ./...
CGO_ENABLED=0 /usr/local/go/bin/go build -trimpath -o /tmp/claude-1000/shell-parser .
cd ../.. && env -u VIRTUAL_ENV -u FORCE_COLOR uv run --group dev python -m pytest tests/test_helper_digest.py -q --no-cov
```
Expected: all Go tests PASS; gofmt clean; vet clean; binary builds; digest test PASS.

- [ ] **Step 6: Commit**

```bash
git add helper/doc-lattice-shell-parser/conformance_test.go helper/doc-lattice-shell-parser/determinism_test.go
git commit -m "test: verify the helper end to end against the frozen protocol fixtures"
```
