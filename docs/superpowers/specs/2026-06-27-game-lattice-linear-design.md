# game-lattice Linear Slice: Design Spec

**Date:** 2026-06-27
**Status:** Design (post brainstorm). Ready for implementation planning.
**Scope:** The first network-touching slice. Resolve referenced Linear tickets to live status
and surface shipped-against-stale-spec drift. No mutations, no committed status, no LLM.
**Source decision record:** `~/.claude/LCARS/decisions/2026-06-27-game-lattice-doc-traceability.md`
**Builds on:** `docs/superpowers/specs/2026-06-27-game-lattice-local-core-design.md` (the local core).

This spec turns the deferred `linear` item from the local-core deferral map (section 12) into a
buildable design. It does not re-open any locked decision from the decision record. Decision 6
(direct GraphQL, a standalone client copied from `gx-linear-skills`, no hard dependency on it, no
MCP) and decision 11 (the tool ships zero secrets; credentials live in the consuming repo's env)
are taken as given and realized precisely below.

## 1. Scope

In scope:

- A single `linear` command that resolves the `PC-*` tickets referenced in lattice frontmatter to
  live Linear status, then reports the dangerous intersection of doc drift and ticket progress.
- The headline finding is shipped-against-stale-spec: a downstream doc carries a STALE edge while a
  ticket that implements it is already Done. That is code built against a spec that has since moved.
- Two trigger modes over one shared analysis: a standing audit of current drift, and a
  forward-looking `--from <id>` blast-radius for a change not yet made.
- Findings graded DANGER / WARNING / INFO by the implementing ticket's workflow state.

Explicitly out of scope, deferred to a later spec or enhancement (see section 13):

- Any Linear mutation. This slice only reads.
- Persisting ticket status into frontmatter or any committed file. Status is live and volatile;
  it is never written back.
- The full Linear relation graph (blocks, blocked-by, related). This slice pulls parent and
  child links only, for context.
- `init` scaffolding, pre-commit, and CI codegen (already deferred by the local-core spec).
- Any gitignored status cache. One batched query per run is cheap at this corpus size.

## 2. The determinism boundary

game-lattice's identity is deterministic and offline. This slice introduces network and
credentials for the first time, so the boundary is drawn sharply and stated as an invariant:

- `linear` is the only command that touches the network. `check`, `impact`, `graph`, and
  `reconcile` stay byte-for-byte offline and deterministic, and are not modified by this slice.
- `linear` reuses the pure layers it needs rather than changing them. It calls `check`'s edge
  classifier to find STALE edges and `impact`'s pure walk for `--from`, and adds no behavior to
  either module.
- The analysis that produces findings is pure and network-free. Only fetching the ticket status
  map is impure. This is the same pure-core, impure-edge discipline the local core already uses.

## 3. Operating model and command surface

```
game-lattice linear [TARGET]          # whole-lattice audit; optional id narrows to one subtree
game-lattice linear --from <id>       # forward-looking: impact-walk from a doc about to change
game-lattice linear ... --json        # machine-readable findings, consistent with check and impact
game-lattice linear ... --exit-code   # opt-in gate: any DANGER finding exits 1
game-lattice linear ... --warn-exit   # with --exit-code, WARNING findings also exit 1
game-lattice linear ... --config PATH # same config override as the other commands
```

The two modes differ only in which downstream nodes are eligible to produce findings. The grading
and rendering are identical.

- **Audit (default).** The trigger set is every node that currently carries a STALE edge, as
  classified by `check`. This answers "what is dangerous right now." An optional positional
  `TARGET` narrows the trigger set to the currently-STALE nodes that also fall in the impact set of
  `TARGET`, for a focused look at drift downstream of one id.
- **Forward-looking (`--from <id>`).** The trigger set is the impact set of `<id>` computed by
  `impact`'s pure walk, regardless of current stale state. This answers "if I change `<id>`, which
  shipped or in-flight tickets does that endanger." It runs before the edit, so the edges are not
  STALE yet; membership in the impact set is the trigger.

`--from` and a positional `TARGET` are mutually exclusive; supplying both is a usage error.

## 4. Data model

Four immutable types, all network-free once built.

- `TicketState(name: str, type: LinearStateType)`. The Linear workflow state. `type` is one of the
  six Linear state types and drives grading; `name` is the display label (for example "In Review").
- `TicketRef(identifier: str, title: str | None, state: TicketState)`. A lightweight reference used
  for a ticket's parent and children, so context can be shown without a second fetch.
- `Ticket(identifier, title, url, state: TicketState, parent: TicketRef | None,
  children: tuple[TicketRef, ...])`. One resolved Linear issue.
- `Finding(severity: Severity, node_id, node_title, node_path, drifted_refs: tuple[str, ...],
  ticket: Ticket)`. One reportable result.

`LinearStateType = Literal["triage", "backlog", "unstarted", "started", "completed", "canceled"]`
and `Severity = Literal["DANGER", "WARNING", "INFO"]` are added to `constants.py` with the existing
`Literal` plus `get_args()` plus `frozenset` pattern, and imported wherever those values are used.

`Ticket` types live in a new `tickets.py`, kept separate from `model.py` so the lattice graph types
stay free of any network-derived domain.

## 5. The stale-shipped join

`stale_shipped.py` is pure. It takes the built `Lattice`, the trigger node set (from `check` for
audit, from `impact` for `--from`), and a `Mapping[identifier, Ticket]`, and returns graded findings.

### 5.1 Finding identity and grading

A finding is keyed on the pair `(downstream_node_id, ticket_identifier)`, not on the edge. A node
with several drifted upstream refs lists all of them in `drifted_refs`; it does not fan out into one
finding per edge. The severity comes from the implementing ticket's own state type:

| Ticket state type | Severity | Meaning |
|---|---|---|
| `completed` | DANGER | Shipped work built against a spec that has since drifted. |
| `started` | WARNING | In-flight work (In Progress or In Review) against a spec that just drifted. |
| `unstarted`, `backlog` | INFO | Not started; the worker will pick up the current spec. |
| `canceled`, `triage` | omitted | Not a real risk; produces no finding. |

Consequences worth stating: a node with a STALE edge but no tickets produces nothing, because no
shipped work is endangered. A node whose tickets are all canceled produces nothing. A node with an
OK edge and a Done ticket is the healthy case and produces nothing. A completed ticket's still-open
children are attached to its DANGER finding as context, since a "done" parent with open children is
itself a signal.

### 5.2 What the two modes feed in

The join logic is one function. Only its trigger node set changes:

- Audit passes the set of source node ids whose edges `check` classified as STALE.
- `--from <id>` passes the impact set of `<id>`, the downstream nodes that would go STALE if `<id>`
  changed, computed by `impact`'s reverse-walk over `dependents`, the same one the local core
  already ships.

## 6. Fetching ticket status

`linear_fetch.py` is the thin impure wiring that turns a set of identifiers into the ticket map. It
deduplicates identifiers first, so a ticket referenced by several docs is fetched once.

`linear_query.py` is pure. It builds one GraphQL `query` document with one aliased `issue(id:)`
field per identifier, sharing a single fragment for the ticket fields including `parent` and
`children(first: 50)`. Identifier sets larger than a fixed batch size (for example 50) are chunked
into several documents whose results are merged. Identifiers are passed as GraphQL variables, never
interpolated into the document text.

`linear_client.py` is the transport, copied in shape from the proven `gx-linear-skills` client:
synchronous `urllib.request` POST to `https://api.linear.app/graphql`, the API key read lazily from
`LINEAR_API_KEY` on each request, the URL scheme validated up front, a bounded timeout, and HTTP or
URL errors mapped to `LinearError`. It returns the raw response text and interprets none of it.

`linear_parser.py` is the boundary. It is the only new module permitted `Any` and `cast`, because
its name ends in `_parser` and `scripts/check_typing_boundaries.py` allows the untyped-to-typed
conversion there. It parses the JSON, rejects a GraphQL `errors` array or a missing `data` object
as a `LinearError`, caps the response size before parsing, and validates each issue node into a
typed `Ticket` with strict pydantic.

An identifier that Linear returns `null` for (a typo, or a deleted ticket) is recorded as
**unresolved** and surfaced as a soft note. It is not a fatal error, mirroring the local core's
decision that a BROKEN edge is a normal reported state rather than a crash.

## 7. Configuration

No new config keys. `linear_team`, already parsed and forward-compat in the local core, becomes
active here:

```yaml
linear_team: PC          # optional; when set, validates and scopes referenced tickets
```

When `linear_team` is set, an identifier whose team prefix does not match is flagged as a
cross-team reference (a soft note) rather than silently queried. When it is null, identifiers are
validated only against the generic shape and queried as written. Credentials never live in config;
`LINEAR_API_KEY` is read from the environment, per decision 11.

## 8. Error handling

Extends the `ProjectError` hierarchy with one coded error, consistent with the local core and the
`gx-linear-skills` precedent:

- `LinearError` (code `LINEAR_ERROR`): a missing or empty `LINEAR_API_KEY`, an HTTP or network
  failure, a GraphQL `errors` array, or an unparseable or malformed response. Every message names
  the cause and the fix, and never includes the API key or the `Authorization` header.

Exit codes:

- 0: success, including when findings exist. The command is informational by default.
- 1: only under `--exit-code`, when a DANGER finding exists (or a WARNING finding too, under the
  additional `--warn-exit`).
- 2: a `LinearError` (missing credential, auth failure, network failure, bad response), or any
  local load error already defined by the core (missing or invalid config, duplicate id, unreadable
  doc). A missing `LINEAR_API_KEY` is an actionable exit 2, not a silent degrade; its message points
  at setting the key or at running `impact` for the offline raw-ticket view.

No bare `except Exception`. No `datetime.now()` outside `datetime_utils.py`.

## 9. Security

This is the first slice with a real security surface, so it carries the dedicated pass the roadmap
promised. The untrusted inputs are the local frontmatter (its `tickets:` values) and the network
response.

- **Credentials.** `LINEAR_API_KEY` is read from the environment only, lazily, per request. It is
  never sourced from config, CLI arguments, or files, and never logged, echoed, or placed in any
  error message, `--json` output, or surfaced Linear error body. No error includes the
  `Authorization` header.
- **Read-only.** `linear_query.py` emits only `query` documents. There is no mutation path in this
  slice, and a test asserts the generated document contains no `mutation`.
- **Injection safety.** Ticket identifiers travel as GraphQL variables, never interpolated into the
  document, so a repo-controlled `tickets:` value cannot change query structure.
- **Identifier validation.** Each identifier is validated against `^[A-Z][A-Z0-9]*-\d+$` (narrowed
  to the `linear_team` prefix when configured) before being sent. A malformed value is reported as
  invalid and never put on the wire.
- **Transport hardening.** HTTPS only, enforced by the URL-scheme guard. A bounded timeout. The
  response body is length-capped before parsing so a hostile or oversized response cannot exhaust
  memory. Each ticket node is strictly validated by pydantic.
- **Zero secrets in the repo.** Every test mocks the transport: no real network, no real key, only
  synthetic ticket JSON. No fixture, config, or CI file carries a token. The public repo's own CI
  does not run `linear`; `check` remains its CI gate. The pure layers (`stale_shipped`, `tickets`,
  `linear_query`, `linear_render`) touch neither network nor secrets.

## 10. Testing

Test-driven, per project conventions, tests mirroring sources one to one, all offline.

- **Pure unit tests.**
  - `test_stale_shipped.py`: grading by state type; canceled and triage omitted; one finding per
    `(node, ticket)`; `drifted_refs` aggregation across multiple stale edges on a node; a completed
    ticket's open children attached as context; the audit stale-trigger versus the `--from`
    impact-trigger; a node with no tickets yields nothing.
  - `test_linear_query.py`: the document is a `query` and never a `mutation`; identifiers are passed
    as variables, not interpolated; aliases are unique; chunking at the batch boundary; dedupe.
  - `test_tickets.py`: model construction and the state-type literal enforcement.
  - `test_linear_render.py`: severity grouping in the human table, the `--json` shape, and that the
    API key never appears in any output.
- **Boundary test.** `test_linear_parser.py`: a valid response yields typed `Ticket`s including
  parent and children; a GraphQL `errors` array raises `LinearError`; a missing `data` raises
  `LinearError`; a null issue is reported unresolved; a malformed or oversized response raises
  `LinearError`.
- **Transport test (mocked HTTP, no real network).** `test_linear_client.py`: the Authorization
  header carries the key; a POST with JSON content type; the HTTPS scheme guard; the timeout is
  passed; `HTTPError` and `URLError` map to `LinearError`; the key never appears in any raised
  message; a missing `LINEAR_API_KEY` raises an actionable `LinearError`.
- **CLI tests (mocked fetch).** The `linear` audit table; `--json` shape; `--from` mode; the exit
  codes (0 by default even with findings, 1 on DANGER under `--exit-code`, WARNING also under
  `--warn-exit`, 2 on auth or network error); the no-key actionable error; the unresolved-ticket
  soft note; `--from` and a positional target together as a usage error.
- Coverage at or above the existing 80 percent gate. `test_conventions.py` stays green: the new
  modules carry module docstrings and Google-style docstrings, use the constants pattern, and keep
  `Any` and `cast` confined to `linear_parser.py`.

Fixtures extend `tests/conftest.py` with a node whose STALE edge also carries `tickets:`, plus a
synthetic ticket-map fixture covering completed, started, unstarted, and canceled states, a parent
with open children, and an unresolved identifier. Zero secrets, zero network.

## 11. Dependencies

None new. The transport is stdlib `urllib.request`, copied in shape from `gx-linear-skills`.
`pydantic`, `rich`, `typer`, and `ruamel.yaml` are already present. The network slice adds zero
third-party dependencies.

## 12. Module decomposition

| Module | Purpose | Pure? |
|---|---|---|
| `tickets.py` | `TicketState`, `TicketRef`, `Ticket`, `Finding` types | pure |
| `linear_query.py` | Build the batched, aliased `issue(id:)` GraphQL document and variables | pure |
| `linear_client.py` | Transport: stdlib POST, lazy key, scheme guard, timeout, error mapping | impure I/O |
| `linear_parser.py` | Boundary: JSON to typed `Ticket`, envelope and shape validation | boundary |
| `linear_fetch.py` | Thin wiring: dedupe, query, client, parser, into a ticket map | impure |
| `stale_shipped.py` | Pure join: lattice plus trigger set plus ticket map to graded findings | pure |
| `linear_render.py` | Severity-grouped human table and the `--json` shape | pure |

Edits: `error_types.py` adds `LinearError`; `constants.py` adds `LinearStateType` and `Severity`;
`cli.py` adds the `linear` command. `model`, `check`, `impact`, `graph`, `reconcile`, and
`orchestrate` are unchanged.

## 13. Non-goals and deferral map

| Deferred item | Where it lands |
|---|---|
| Any Linear mutation | out of scope by design; this slice only reads |
| Persisting ticket status into frontmatter | out of scope by design; status is live, never committed |
| Full Linear relation graph (blocks, blocked-by, related) | later enhancement; this slice pulls parent and children only |
| `init` scaffolding, pre-commit and CI codegen | later spec (already deferred by the local core) |
| Gitignored status cache | not needed at this corpus size |
| Display-prefix lint | optional future enhancement |

## 14. Acceptance

| Goal | Solved by | Verifiable when |
|---|---|---|
| Surface shipped-against-stale-spec drift | the audit mode's DANGER findings | a STALE edge whose ticket is Done appears as a DANGER finding |
| Pre-edit blast-radius on shipped work | the `--from <id>` mode | `--from` on an upstream id lists downstream Done and in-flight tickets |
| Keep the core deterministic | the determinism boundary | `check`, `impact`, `graph`, `reconcile` run offline and unchanged |
| Ship zero secrets safely | the security pass | no token in repo; missing key is an actionable exit 2, not a leak |
