# README Rewrite: Design Spec

**Date:** 2026-07-13
**Status:** Design (post brainstorm). Ready for implementation planning.
**Scope:** `README.md` only. No source, test, or config changes. A full top-to-bottom editorial
pass that removes the unexplained game-dev framing left over from the game-lattice era, adds a
domain gallery that positions doc-lattice as general docs-as-code tooling, and replaces the worked
example with a domain-neutral one whose console output is captured from the real CLI.

## Problem

The README was written when the project was game-lattice, a game-dev support tool. After the
rename to doc-lattice (v0.9.0, PR #59) the tool's positioning is broader, but the README still
assumes a game studio's doc set without ever saying so. "Someone retunes the economy, edits the
art direction, or rewrites the core loop" reads as a non sequitur to a reader who arrived at a
generic documentation-traceability tool. The worked example (art-direction, pc-design, accent
color, PC-228) has the same problem: the mechanics are right, the framing is unexplained.

## Decisions (locked during brainstorm)

1. **Example mix: neutral primary plus a domain gallery.** The primary worked example becomes
   domain-neutral (software/API). A new "Where it fits" section presents three one-paragraph
   scenarios, one of which is game studio design docs, so the origin domain stays
   present but labeled as one use case among several. Game dev is context, not default.
2. **Primary example domain: API contract to integration guide.** Upstream: an API design doc
   with an anchored section. Downstream: an integration guide deriving from that section. This is
   instantly relatable to any software team and maps one-to-one onto the current accent-color
   mechanics (marker vs. slug, `seen` hash, STALE, exit 1, reconcile).
3. **Scope: full top-to-bottom pass.** Narrative sections are rewritten; the reference half
   (Commands, Frontmatter reference, Configuration, Load cache, Adopting, Linear, Exit codes,
   Troubleshooting, Documentation, Project structure) keeps its content, which is accurate, but
   gets a tone and flow edit plus a scrub of any lingering game-era strings.

## New structure and content

Section order is unchanged except for one insertion ("Where it fits"). Concept, then worked
example, then quick start, then reference remains the right order for a concept-heavy tool.

### Intro

Keep the one-line pitch ("A deterministic, offline traceability engine for design and production
documentation.") and the pure-tooling paragraph. Replace the parenthetical game examples with
neutral ones: an integration guide built on an API design, an engineering design built on a
product brief.

### The problem it solves

Replace the game-era drift triggers with domain-neutral ones: someone changes the API contract,
revises a requirement, or reverses an architecture decision, and the documents downstream keep
citing the old version. The drift/reconcile framing (nothing breaks loudly; `check` fails CI
until a human reconciles) is retained as-is.

### Where it fits (new section, after the problem statement)

Three one-paragraph scenarios:

1. **Software product docs.** Product briefs feeding engineering designs feeding runbooks and
   integration guides; a requirement change should surface every downstream doc that cited it.
2. **Game studio design docs.** The origin domain, framed explicitly: art direction, economy
   tuning, and core-loop docs, where a dozen downstream specs hang off one creative decision and
   drift surfaces as a bug or a redo weeks later.
3. **Policy and compliance doc sets.** A controls document or policy that procedures and
   checklists derive from; unacknowledged drift there is an audit finding waiting to happen.

### A worked example (rewritten)

- Upstream `docs/api-design.md`: `id: api-design`, `layer: design`, `authority: binding`, with a
  section `## Pagination {#pagination}` describing cursor pagination.
- Downstream `docs/billing-integration-guide.md`: `id: billing-integration-guide`,
  `layer: technical`, `authority: derived`, `derives_from: [{ref: api-design#pagination,
  seen: <real hash>}]`, `tickets: [ENG-412]`.
- Story beats, identical mechanics to the current example: the ref resolves file-scoped; the
  `{#pagination}` marker pins a stable id (and the marker-vs-GitHub-slug explanation is kept);
  someone switches the pagination scheme; `check` reports STALE and exits 1; `impact` lists the
  guide with its ticket; a human reviews and runs `reconcile`; `check` is green.
- The edit -> check -> review -> reconcile loop paragraph is retained.

### Reference half

Content-preserving editorial pass. Specifically:

- Scrub remaining game-era strings (`pc-design` in console snippets, `PC-228` in the frontmatter
  example) as a side effect of the worked-example rewrite; verify nothing else remains via a
  grep for the old vocabulary (economy, art direction, player, PC-, core loop, game).
- Tone and flow edits only; no factual or structural changes to Commands, reconcile selectors,
  Frontmatter reference, Configuration, Load cache, Adopting, Linear, Exit codes,
  Troubleshooting, Documentation, or Project structure.

## Verification

1. **Real CLI output.** Build the two example docs in a scratchpad project and run the released
   workflow against them: `check` (STALE), `impact api-design#pagination`, `reconcile
   billing-integration-guide`, `check` (OK). Paste genuine output, including the real `seen`
   hash the tool computes, so the README never shows output the CLI does not produce.
2. **Version pin.** Confirm the `doc-lattice==X.Y.Z` pin in the Adopting section matches the
   currently released version (1.0.0 at time of writing; re-verify at implementation time).
3. **Vocabulary sweep.** Grep the final README for game-era vocabulary outside the "Where it
   fits" game-studio paragraph (the only place it should appear).
4. **Rendering.** Markdown tables and fenced blocks render correctly (spot-check with a preview
   or lint pass); repo pre-commit hooks pass.

## Non-goals

- No changes to ARCHITECTURE.md, CLAUDE.md, roadmap.md, or the specs.
- No new commands, flags, or behavior claims; the README documents what ships in 1.0.0.
- No restructuring of the reference sections' order or content beyond wording.
