# Conflict-Safe Reconcile Transactions

**Date:** 2026-07-13
**Status:** Accepted
**Issue:** #86

## Context

`reconcile` is the only command that mutates tracked documents. Its current two-phase
implementation re-reads and validates every downstream file before writing, then atomically
replaces each file in sequence. That leaves two failure modes:

- an edit made after fresh-read validation can be overwritten by the later replacement;
- a failure after one replacement leaves a partially applied batch with no durable record or
  automatic recovery path.

Reconcile, cache persistence, and `init` also maintain three different low-level temporary-file
implementations. They need common durable primitives while retaining their distinct semantics and
error policies.

## Goals

- Recheck the exact fresh-read source bytes immediately before replacement and reject a mismatch.
- Give reconcile durable all-or-nothing batch semantics through automatic rollback.
- Make an interrupted or failed batch recoverable and make repeated recovery and reconcile runs
  safe.
- Use unique same-directory temporary files and clean them up on every safely recoverable path.
- Define the durability boundary through file and parent-directory `fsync` calls.
- Emit reconcile success output only after the entire batch is durably committed.
- Share low-level replace and create-if-absent primitives with cache persistence and `init` without
  changing their caller-specific error policies.

## Non-goals

- Coordinating edits by unrelated tools through advisory locks. Reconcile detects changed bytes;
  editors do not need to participate in a locking protocol.
- Resuming a partially applied batch. Recovery always rolls the batch back to its pre-reconcile
  contents unless a later unrelated edit has already superseded a transaction-owned image.
- Providing a general-purpose database or public transaction API.
- Making stdout publication atomic with filesystem commit. The guarantee is one-way: every
  reported success is durable, although a process termination after commit and before output can
  leave a durable result that was not reported.

## Module boundaries

### `persistence.py`

This impure module owns reusable filesystem primitives:

- stage bytes in a collision-resistant temporary file created by `tempfile.mkstemp` beside the
  destination;
- flush and `fsync` staged file contents;
- `fsync` a directory after namespace changes;
- atomically replace a path with staged bytes and durably publish the directory entry;
- atomically create a path only when absent through a hard link and durably publish the directory
  entry;
- fingerprint exact bytes and current file contents with full SHA-256;
- remove transaction artifacts with caller-selectable error handling.

Every primitive either completes its durability contract or raises `OSError`. It does not decide
whether an error is fatal. Cache persistence continues to emit one stderr diagnostic and swallow
write failures. `init` and reconcile continue to convert failures into their existing typed project
errors.

### `reconcile.py`

The pure reconcile planner continues to select edges and round-trip frontmatter. Its fresh-read
rewrite record becomes a frozen data object containing:

- the document identity path;
- the exact source bytes read at validation time;
- the replacement bytes;
- the set of refs actually changed.

The byte reader decodes UTF-8 only for frontmatter transformation. The original bytes remain
available for an exact fingerprint and before-image.

### `reconcile_transaction.py`

This impure module owns the reconcile-only journal, prepare, commit, rollback, recovery, and
cleanup state machine. The CLI supplies the contained resolved destination for each identity path
and receives a recovery outcome or a committed set of rewrite records.

## Journal and staged artifacts

The journal is `.doc-lattice-reconcile.json` in the configured project root. All paths stored in it
are relative to that root and are revalidated for containment before recovery uses them. The
journal has a schema version, a state (`prepared` or `committed`), and ordered entries containing:

- the destination path;
- the before-image path and SHA-256 fingerprint;
- the after-image path and SHA-256 fingerprint.

Before mutation, reconcile stages and `fsync`s a before-image and after-image beside every
destination. Temporary names contain a descriptive prefix but rely on `mkstemp` for uniqueness.
It then atomically creates and durably publishes the `prepared` journal. A journal already present
prevents creation of another batch.

The journal is the recovery authority. Artifacts that cannot be tied to a valid contained journal
entry are never applied to a document.

## Commit protocol

For each journal entry in deterministic plan order:

1. Fingerprint the current destination immediately before replacement.
2. If it differs from the before fingerprint, abort the commit without replacing that file.
3. Atomically replace the destination with its staged after-image.
4. `fsync` the destination directory so the replacement is durable.

After all replacements and directory syncs succeed, reconcile atomically replaces the journal with
state `committed` and `fsync`s the project root. It then removes before-images, any unconsumed
after-images, and the journal, synchronizing affected directories after cleanup. The transaction
returns success only after that sequence completes.

This implements the issue's required fingerprint recheck immediately before replacement. Like any
portable path-based replace, there is still an instruction-level interval between the final read
and `os.replace`; the design intentionally makes that interval as small as the API permits without
requiring editors to honor locks or depending on a platform-specific compare-and-swap syscall.

## Rollback and recovery

Any failure before the durable `committed` marker invokes rollback immediately. A later reconcile
invocation also checks for a journal before loading the lattice:

- A `prepared` journal is rolled back, then the requested reconcile continues from a newly loaded
  lattice.
- A `committed` journal never changes document contents; recovery only finishes cleanup.
- A malformed journal, an escaping path, or missing data required to restore a transaction-owned
  after-image stops with exit 2 and preserves the available evidence.

Rollback processes entries in reverse order. For each destination:

- if its bytes match the after fingerprint, atomically replace it with the before-image and sync
  the directory;
- if its bytes match the before fingerprint, leave it unchanged;
- if it matches neither fingerprint, preserve the unrelated edit rather than overwriting it.

After document contents are safe, rollback removes unused staged artifacts and the journal, with
directory syncs. The operation is idempotent because every recovery decision is based on current
fingerprints. A second recovery observes either the restored before-image, a preserved unrelated
edit, or a committed after-image governed by a `committed` journal.

If rollback itself cannot restore a destination that still contains the transaction after-image,
the journal and required before-image remain in place. The error names the destination and
artifacts so recovery never guesses or silently loses data.

`--dry-run` never creates a new journal or staged artifacts. It still performs automatic recovery
before loading the lattice, so an interrupted earlier batch may be rolled back before the dry-run
preview.

## Reporting and errors

Human and JSON success output is deferred until transaction commit and cleanup return successfully.
A failed batch prints no `reconciled` lines and emits no JSON success payload. Its exit-2 diagnostic
states whether rollback completed or recovery artifacts remain.

Automatic startup recovery emits one concise stderr diagnostic and then proceeds with the newly
requested reconcile. JSON stdout remains a single valid payload for the new command.

Dry-run reporting continues to describe validated rewrites as `would reconcile` entries. A real
successful run reports exactly the rewrite records passed through the durable transaction.

## Shared write semantics

- Reconcile uses staged replace, file sync, directory sync, fingerprints, and cleanup as building
  blocks for its journaled batch.
- Cache persistence uses the same durable atomic-replace primitive. It still creates parent
  directories, swallows every `OSError`, emits exactly one stderr line, and never changes a command
  result.
- `init` uses the same durable create-if-absent primitive. It still refuses an existing config,
  surfaces other errors as `ConfigError`, and leaves no temporary file.

Sharing stops at the primitive boundary. Cache writes are disposable single-file replacements and
`init` is a create-only operation, so neither participates in reconcile journals.

## Fault-injection coverage

Focused persistence tests cover unique staging names, content sync, directory sync, atomic replace,
atomic create-if-absent, and cleanup after write, replace, link, and sync failures.

Transaction tests cover:

- an edit injected after fresh-read validation but before replacement;
- a second-file replacement failure and an earlier-file rollback;
- directory-sync failure after replacement;
- recovery from partially applied `prepared` journals;
- cleanup-only recovery from `committed` journals;
- repeated rollback and repeated reconcile safety;
- preservation of unrelated edits encountered during rollback;
- missing or malformed recovery data without unsafe guessing;
- collision-resistant staging and cleanup of every available artifact.

CLI integration tests assert that failed batches produce no human or JSON success entries, startup
recovery precedes lattice loading, successful output follows durable commit, and the dry-run recovery
exception is documented behavior. Existing cache and `init` tests continue to enforce their
different error policies through the shared primitives.

## Documentation changes

`ARCHITECTURE.md`, `README.md`, and `CLAUDE.md` will replace the admitted overwrite race and
non-transactional batch descriptions with the fingerprint check, journal states, automatic
rollback, durable reporting boundary, and `--dry-run` recovery caveat. The architecture decision
will also describe `persistence.py` as the shared low-level write owner and
`reconcile_transaction.py` as the reconcile batch owner.
