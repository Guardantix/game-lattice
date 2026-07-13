"""Tests for durable reconcile transaction recovery."""

import json
from dataclasses import FrozenInstanceError, dataclass
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from doc_lattice import persistence, reconcile_transaction
from doc_lattice.constants import RECONCILE_JOURNAL_NAME, RECONCILE_JOURNAL_VERSION
from doc_lattice.error_types import (
    ProjectError,
    ReconcileConflictError,
    ReconcileInProgressError,
    ReconcilePersistenceError,
)
from doc_lattice.reconcile_transaction import (
    Journal,
    JournalEntry,
    JournalState,
    RecoveryResult,
    ensure_dry_run_safe,
    reconcile_lock,
    recover_transaction,
)


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    """Capture relative file names and exact bytes under a test root."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@dataclass(frozen=True)
class SyntheticTransaction:
    """Paths belonging to one synthetic recovery journal."""

    destination: Path
    before: Path
    after: Path
    journal: Path


def _write_synthetic_transaction(  # noqa: PLR0913
    root: Path,
    *,
    state: JournalState = "prepared",
    destination_bytes: bytes | None = b"after image\n",
    before_bytes: bytes = b"before image\n",
    after_bytes: bytes = b"after image\n",
    before_present: bool = True,
    after_present: bool = True,
) -> SyntheticTransaction:
    """Write a valid synthetic journal plus caller-selected current artifacts."""
    docs = root / "docs"
    docs.mkdir()
    destination = docs / "doc.md"
    before = docs / ".doc.md.before.tmp"
    after = docs / ".doc.md.after.tmp"
    journal = root / RECONCILE_JOURNAL_NAME
    if destination_bytes is not None:
        destination.write_bytes(destination_bytes)
    if before_present:
        before.write_bytes(before_bytes)
    if after_present:
        after.write_bytes(after_bytes)
    entry = JournalEntry(
        destination=destination.relative_to(root).as_posix(),
        before_path=before.relative_to(root).as_posix(),
        before_sha256=sha256(before_bytes).hexdigest(),
        after_path=after.relative_to(root).as_posix(),
        after_sha256=sha256(after_bytes).hexdigest(),
    )
    journal.write_text(
        Journal(version=RECONCILE_JOURNAL_VERSION, state=state, entries=(entry,)).model_dump_json(),
        encoding="utf-8",
    )
    return SyntheticTransaction(destination, before, after, journal)


def test_reconcile_constants_are_pinned():
    assert RECONCILE_JOURNAL_NAME == ".doc-lattice-reconcile.json"
    assert RECONCILE_JOURNAL_VERSION == 1


@pytest.mark.parametrize(
    ("factory", "code"),
    [
        (ReconcileInProgressError, "RECONCILE_IN_PROGRESS"),
        (ReconcileConflictError, "RECONCILE_CONFLICT"),
        (ReconcilePersistenceError, "RECONCILE_PERSISTENCE"),
    ],
)
def test_reconcile_errors_carry_message_and_code(factory, code):
    error = factory("transaction failed")

    assert isinstance(error, ProjectError)
    assert str(error) == "transaction failed"
    assert error.code == code


def test_second_live_reconcile_holder_is_refused(tmp_path: Path):
    journal = tmp_path / RECONCILE_JOURNAL_NAME
    journal_bytes = b"sentinel journal bytes\n"
    journal.write_bytes(journal_bytes)

    with reconcile_lock(tmp_path):
        with (
            pytest.raises(ReconcileInProgressError) as caught,
            reconcile_lock(tmp_path),
        ):
            pytest.fail("nested holder unexpectedly acquired the directory lock")
        assert journal.read_bytes() == journal_bytes

    assert str(caught.value) == "another reconcile is in progress; retry after it exits"
    assert journal.read_bytes() == journal_bytes
    with reconcile_lock(tmp_path):
        assert journal.read_bytes() == journal_bytes


def test_dry_run_refuses_existing_journal_without_mutation(tmp_path: Path):
    document = tmp_path / "doc.md"
    journal = tmp_path / RECONCILE_JOURNAL_NAME
    document.write_bytes(b"document bytes\x00\xff")
    journal.write_bytes(b'{"incomplete": true}\n')
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ReconcilePersistenceError) as caught:
        ensure_dry_run_safe(tmp_path)

    message = str(caught.value)
    assert str(journal) in message
    assert "run 'doc-lattice reconcile --recover' first" in message
    assert _tree_snapshot(tmp_path) == before


def test_dry_run_allows_project_without_journal(tmp_path: Path):
    ensure_dry_run_safe(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_journal_models_are_frozen():
    entry = JournalEntry(
        destination="docs/doc.md",
        before_path="docs/.doc.md.before.tmp",
        before_sha256="a" * 64,
        after_path="docs/.doc.md.after.tmp",
        after_sha256="b" * 64,
    )
    journal = Journal(version=RECONCILE_JOURNAL_VERSION, state="prepared", entries=(entry,))

    assert journal.entries == (entry,)
    with pytest.raises(ValidationError):
        entry.destination = "other.md"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unexpected", True),
        ("before_sha256", "A" * 64),
        ("after_sha256", "short"),
    ],
)
def test_journal_entry_rejects_unknown_field_or_invalid_digest(field: str, value: object):
    payload = {
        "destination": "docs/doc.md",
        "before_path": "docs/.doc.md.before.tmp",
        "before_sha256": "a" * 64,
        "after_path": "docs/.doc.md.after.tmp",
        "after_sha256": "b" * 64,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        JournalEntry.model_validate(payload)


def test_journal_rejects_unknown_state():
    with pytest.raises(ValidationError):
        Journal.model_validate({"version": 1, "state": "unknown", "entries": []})


def test_recovery_result_is_frozen_and_slotted(tmp_path: Path):
    result = RecoveryResult(action="none", journal=tmp_path / RECONCILE_JOURNAL_NAME)

    assert result.__slots__ == ("action", "journal")
    with pytest.raises(FrozenInstanceError):
        result.action = "rolled_back"  # ty: ignore[invalid-assignment]


def test_recovery_without_journal_returns_none_without_writes(tmp_path: Path):
    document = tmp_path / "doc.md"
    document.write_bytes(b"unchanged")
    before = _tree_snapshot(tmp_path)

    result = recover_transaction(tmp_path)

    assert result == RecoveryResult(
        action="none",
        journal=tmp_path / RECONCILE_JOURNAL_NAME,
    )
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("journal_bytes", "cause"),
    [
        (b'{"version":', "Invalid JSON"),
        (b"\xff\xfe", "utf-8"),
    ],
)
def test_malformed_journal_is_rejected_with_evidence_and_remediation(
    tmp_path: Path, journal_bytes: bytes, cause: str
):
    transaction = _write_synthetic_transaction(tmp_path, state="committed")
    transaction.journal.write_bytes(journal_bytes)
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    message = str(caught.value)
    assert str(transaction.journal) in message
    assert cause.lower() in message.lower()
    assert "inspect" in message
    assert "destinations" in message
    assert "staged files" in message
    assert "move the invalid journal aside only after manual" in message
    assert "rerun 'doc-lattice reconcile --recover'" in message
    assert caught.value.__cause__ is not None
    assert _tree_snapshot(tmp_path) == before


def test_unsupported_journal_version_is_rejected_without_cleanup(tmp_path: Path):
    transaction = _write_synthetic_transaction(tmp_path, state="committed")
    payload = json.loads(transaction.journal.read_text(encoding="utf-8"))
    payload["version"] = RECONCILE_JOURNAL_VERSION + 1
    transaction.journal.write_text(json.dumps(payload), encoding="utf-8")
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    assert f"unsupported version {RECONCILE_JOURNAL_VERSION + 1}" in str(caught.value)
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "unsafe_path",
    ["../escape.md", str(Path("/") / "tmp" / "absolute-escape.md")],
)
def test_unsafe_relative_or_absolute_journal_path_is_rejected(tmp_path: Path, unsafe_path: str):
    transaction = _write_synthetic_transaction(tmp_path, state="committed")
    payload = json.loads(transaction.journal.read_text(encoding="utf-8"))
    payload["entries"][0]["before_path"] = unsafe_path
    transaction.journal.write_text(json.dumps(payload), encoding="utf-8")
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    assert "before_path" in str(caught.value)
    assert unsafe_path in str(caught.value)
    assert _tree_snapshot(tmp_path) == before


def test_symlink_escape_in_journal_path_is_rejected(tmp_path: Path):
    transaction = _write_synthetic_transaction(tmp_path, state="committed")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    escaped = outside / "before.tmp"
    escaped.write_bytes(b"outside evidence")
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    payload = json.loads(transaction.journal.read_text(encoding="utf-8"))
    payload["entries"][0]["before_path"] = "escape/before.tmp"
    transaction.journal.write_text(json.dumps(payload), encoding="utf-8")
    journal_bytes = transaction.journal.read_bytes()

    with pytest.raises(ReconcilePersistenceError, match="outside"):
        recover_transaction(tmp_path)

    assert transaction.journal.read_bytes() == journal_bytes
    assert escaped.read_bytes() == b"outside evidence"
    assert transaction.destination.read_bytes() == b"after image\n"


@pytest.mark.parametrize("artifact_field", ["before_path", "after_path"])
def test_committed_journal_artifact_cannot_alias_destination(tmp_path: Path, artifact_field: str):
    transaction = _write_synthetic_transaction(tmp_path, state="committed")
    payload = json.loads(transaction.journal.read_text(encoding="utf-8"))
    payload["entries"][0][artifact_field] = payload["entries"][0]["destination"]
    transaction.journal.write_text(json.dumps(payload), encoding="utf-8")
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    assert "alias" in str(caught.value)
    assert "move the invalid journal aside only after manual" in str(caught.value)
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("role", ["destination", "before_path", "after_path"])
def test_journal_path_cannot_alias_destination_or_artifact(tmp_path: Path, role: str):
    transaction = _write_synthetic_transaction(tmp_path, state="committed")
    payload = json.loads(transaction.journal.read_text(encoding="utf-8"))
    payload["entries"][0][role] = RECONCILE_JOURNAL_NAME
    transaction.journal.write_text(json.dumps(payload), encoding="utf-8")
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    assert role in str(caught.value)
    assert "journal path" in str(caught.value)
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("duplicate_role", ["destination", "artifact"])
def test_paths_cannot_alias_across_journal_entries(tmp_path: Path, duplicate_role: str):
    transaction = _write_synthetic_transaction(tmp_path, state="committed")
    payload = json.loads(transaction.journal.read_text(encoding="utf-8"))
    first = payload["entries"][0]
    second = dict(first)
    second_destination = tmp_path / "docs" / "second.md"
    second_before = tmp_path / "docs" / ".second.md.before.tmp"
    second_after = tmp_path / "docs" / ".second.md.after.tmp"
    second_destination.write_bytes(b"second destination\n")
    second_before.write_bytes(b"second before\n")
    second_after.write_bytes(b"second after\n")
    second["destination"] = second_destination.relative_to(tmp_path).as_posix()
    second["before_path"] = second_before.relative_to(tmp_path).as_posix()
    second["before_sha256"] = sha256(second_before.read_bytes()).hexdigest()
    second["after_path"] = second_after.relative_to(tmp_path).as_posix()
    second["after_sha256"] = sha256(second_after.read_bytes()).hexdigest()
    if duplicate_role == "destination":
        second["destination"] = first["destination"]
    else:
        second["before_path"] = first["after_path"]
    payload["entries"].append(second)
    transaction.journal.write_text(json.dumps(payload), encoding="utf-8")
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    assert duplicate_role in str(caught.value)
    assert "alias" in str(caught.value)
    assert _tree_snapshot(tmp_path) == before


def test_prepared_after_image_is_rolled_back_and_artifacts_are_cleaned(tmp_path: Path):
    transaction = _write_synthetic_transaction(tmp_path)

    result = recover_transaction(tmp_path)

    assert result == RecoveryResult(action="rolled_back", journal=transaction.journal)
    assert transaction.destination.read_bytes() == b"before image\n"
    assert not transaction.before.exists()
    assert not transaction.after.exists()
    assert not transaction.journal.exists()


def test_prepared_destination_already_at_before_image_is_left_unchanged(tmp_path: Path):
    transaction = _write_synthetic_transaction(tmp_path, destination_bytes=b"before image\n")

    result = recover_transaction(tmp_path)

    assert result.action == "rolled_back"
    assert transaction.destination.read_bytes() == b"before image\n"
    assert not transaction.before.exists()
    assert not transaction.after.exists()
    assert not transaction.journal.exists()


@pytest.mark.parametrize("destination_bytes", [b"unrelated editor change\n", None])
def test_prepared_unrelated_edit_or_deletion_is_preserved_while_artifacts_are_cleaned(
    tmp_path: Path, destination_bytes: bytes | None
):
    transaction = _write_synthetic_transaction(
        tmp_path,
        destination_bytes=destination_bytes,
    )

    result = recover_transaction(tmp_path)

    assert result.action == "rolled_back"
    if destination_bytes is None:
        assert not transaction.destination.exists()
    else:
        assert transaction.destination.read_bytes() == destination_bytes
    assert not transaction.before.exists()
    assert not transaction.after.exists()
    assert not transaction.journal.exists()


def test_committed_recovery_never_reads_or_changes_destination(tmp_path: Path, monkeypatch):
    transaction = _write_synthetic_transaction(
        tmp_path,
        state="committed",
        destination_bytes=b"newer unrelated bytes\n",
    )

    def _unexpected_digest(path: Path) -> str:
        pytest.fail(f"committed recovery unexpectedly read destination {path}")

    monkeypatch.setattr(reconcile_transaction, "file_sha256", _unexpected_digest)

    result = recover_transaction(tmp_path)

    assert result == RecoveryResult(action="cleaned_committed", journal=transaction.journal)
    assert transaction.destination.read_bytes() == b"newer unrelated bytes\n"
    assert not transaction.before.exists()
    assert not transaction.after.exists()
    assert not transaction.journal.exists()


def test_committed_recovery_allows_both_staged_artifacts_to_be_absent(tmp_path: Path):
    transaction = _write_synthetic_transaction(
        tmp_path,
        state="committed",
        before_present=False,
        after_present=False,
    )

    result = recover_transaction(tmp_path)

    assert result.action == "cleaned_committed"
    assert transaction.destination.read_bytes() == b"after image\n"
    assert not transaction.journal.exists()


@pytest.mark.parametrize("destination_bytes", [b"before image\n", b"unrelated edit\n"])
def test_prepared_recovery_allows_unneeded_staged_artifacts_to_be_absent(
    tmp_path: Path, destination_bytes: bytes
):
    transaction = _write_synthetic_transaction(
        tmp_path,
        destination_bytes=destination_bytes,
        before_present=False,
        after_present=False,
    )

    result = recover_transaction(tmp_path)

    assert result.action == "rolled_back"
    assert transaction.destination.read_bytes() == destination_bytes
    assert not transaction.journal.exists()


def test_repeated_recovery_is_safe(tmp_path: Path):
    transaction = _write_synthetic_transaction(tmp_path)

    first = recover_transaction(tmp_path)
    second = recover_transaction(tmp_path)

    assert first.action == "rolled_back"
    assert second == RecoveryResult(action="none", journal=transaction.journal)
    assert transaction.destination.read_bytes() == b"before image\n"


@pytest.mark.parametrize("before_state", ["missing", "corrupt"])
def test_required_before_image_missing_or_corrupt_preserves_recovery_evidence(
    tmp_path: Path, before_state: str
):
    transaction = _write_synthetic_transaction(
        tmp_path,
        before_present=before_state != "missing",
    )
    if before_state == "corrupt":
        transaction.before.write_bytes(b"corrupt before image\n")
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    message = str(caught.value)
    assert str(transaction.destination) in message
    assert str(transaction.before) in message
    assert before_state in message
    assert "rerun 'doc-lattice reconcile --recover'" in message
    assert _tree_snapshot(tmp_path) == before


def test_unsafe_recovery_does_not_claim_an_externally_removed_journal_remains(
    tmp_path: Path, monkeypatch
):
    transaction = _write_synthetic_transaction(tmp_path, before_present=False)
    real_file_sha256 = reconcile_transaction.file_sha256

    def _remove_journal_before_digest(path: Path) -> str:
        if path == transaction.destination:
            transaction.journal.unlink()
        return real_file_sha256(path)

    monkeypatch.setattr(reconcile_transaction, "file_sha256", _remove_journal_before_digest)

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    assert f"journal {transaction.journal} remains" not in str(caught.value)
    assert f"journal {transaction.journal} is not present" in str(caught.value)


def test_prepared_rollback_processes_destinations_in_reverse_order(tmp_path: Path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    entries: list[JournalEntry] = []
    destinations: list[Path] = []
    for name in ("first.md", "second.md"):
        destination = docs / name
        before = docs / f".{name}.before.tmp"
        after = docs / f".{name}.after.tmp"
        before_bytes = f"before {name}\n".encode()
        after_bytes = f"after {name}\n".encode()
        destination.write_bytes(after_bytes)
        before.write_bytes(before_bytes)
        after.write_bytes(after_bytes)
        destinations.append(destination)
        entries.append(
            JournalEntry(
                destination=destination.relative_to(tmp_path).as_posix(),
                before_path=before.relative_to(tmp_path).as_posix(),
                before_sha256=sha256(before_bytes).hexdigest(),
                after_path=after.relative_to(tmp_path).as_posix(),
                after_sha256=sha256(after_bytes).hexdigest(),
            )
        )
    journal = tmp_path / RECONCILE_JOURNAL_NAME
    journal.write_text(
        Journal(
            version=RECONCILE_JOURNAL_VERSION, state="prepared", entries=tuple(entries)
        ).model_dump_json(),
        encoding="utf-8",
    )
    real_replace = reconcile_transaction.replace_staged
    replacement_order: list[Path] = []

    def _observe_replace(staged: Path, destination: Path) -> None:
        replacement_order.append(destination)
        real_replace(staged, destination)

    monkeypatch.setattr(reconcile_transaction, "replace_staged", _observe_replace)

    result = recover_transaction(tmp_path)

    assert result.action == "rolled_back"
    assert replacement_order == list(reversed(destinations))


def test_replace_failure_keeps_journal_and_can_be_retried(tmp_path: Path, monkeypatch):
    transaction = _write_synthetic_transaction(tmp_path)
    before = _tree_snapshot(tmp_path)
    real_replace = reconcile_transaction.replace_staged

    def _fail_replace(staged: Path, destination: Path) -> None:  # noqa: ARG001
        raise OSError("injected replace failure")

    monkeypatch.setattr(reconcile_transaction, "replace_staged", _fail_replace)

    with pytest.raises(ReconcilePersistenceError, match="injected replace failure") as caught:
        recover_transaction(tmp_path)

    assert str(transaction.destination) in str(caught.value)
    assert "rerun 'doc-lattice reconcile --recover'" in str(caught.value)
    assert _tree_snapshot(tmp_path) == before

    monkeypatch.setattr(reconcile_transaction, "replace_staged", real_replace)
    result = recover_transaction(tmp_path)

    assert result.action == "rolled_back"
    assert transaction.destination.read_bytes() == b"before image\n"
    assert not transaction.journal.exists()


def test_cleanup_failure_after_restore_keeps_journal_for_idempotent_retry(
    tmp_path: Path, monkeypatch
):
    transaction = _write_synthetic_transaction(tmp_path)
    real_unlink = reconcile_transaction.durable_unlink

    def _fail_after_cleanup(path: Path) -> None:
        if path == transaction.after:
            raise OSError("injected cleanup failure")
        real_unlink(path)

    monkeypatch.setattr(reconcile_transaction, "durable_unlink", _fail_after_cleanup)

    with pytest.raises(ReconcilePersistenceError, match="injected cleanup failure") as caught:
        recover_transaction(tmp_path)

    assert str(transaction.after) in str(caught.value)
    assert transaction.destination.read_bytes() == b"before image\n"
    assert not transaction.before.exists()
    assert transaction.after.exists()
    assert transaction.journal.exists()

    monkeypatch.setattr(reconcile_transaction, "durable_unlink", real_unlink)
    result = recover_transaction(tmp_path)

    assert result.action == "rolled_back"
    assert transaction.destination.read_bytes() == b"before image\n"
    assert not transaction.after.exists()
    assert not transaction.journal.exists()


def test_one_shot_post_unlink_stage_sync_failure_is_healed(tmp_path: Path, monkeypatch):
    transaction = _write_synthetic_transaction(
        tmp_path,
        destination_bytes=b"before image\n",
    )
    real_sync = persistence.sync_directory
    sync_calls = 0

    def _fail_first_sync(path: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            raise OSError("one-shot stage cleanup sync failure")
        real_sync(path)

    monkeypatch.setattr(persistence, "sync_directory", _fail_first_sync)

    result = recover_transaction(tmp_path)

    assert result.action == "rolled_back"
    assert sync_calls >= 3
    assert transaction.destination.read_bytes() == b"before image\n"
    assert not transaction.before.exists()
    assert not transaction.after.exists()
    assert not transaction.journal.exists()


def test_persistent_post_unlink_stage_sync_failure_preserves_journal_for_retry(
    tmp_path: Path, monkeypatch
):
    transaction = _write_synthetic_transaction(
        tmp_path,
        destination_bytes=b"before image\n",
    )
    journal_bytes = transaction.journal.read_bytes()
    real_sync = persistence.sync_directory
    durable_sync_calls: list[Path] = []
    retry_sync_calls: list[Path] = []

    def _fail_durable_sync(path: Path) -> None:
        durable_sync_calls.append(path)
        raise OSError("persistent stage cleanup sync failure")

    def _fail_retry_sync(path: Path) -> None:
        retry_sync_calls.append(path)
        raise OSError("persistent stage cleanup resync failure")

    monkeypatch.setattr(persistence, "sync_directory", _fail_durable_sync)
    monkeypatch.setattr(
        reconcile_transaction,
        "sync_directory",
        _fail_retry_sync,
        raising=False,
    )

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    assert "persistent stage cleanup sync failure" in str(caught.value)
    assert durable_sync_calls == [transaction.before.parent]
    assert retry_sync_calls == [transaction.before.parent]
    assert not transaction.before.exists()
    assert transaction.after.exists()
    assert transaction.journal.is_file()
    assert transaction.journal.read_bytes() == journal_bytes

    monkeypatch.setattr(persistence, "sync_directory", real_sync)
    monkeypatch.setattr(reconcile_transaction, "sync_directory", real_sync)
    result = recover_transaction(tmp_path)

    assert result.action == "rolled_back"
    assert not transaction.after.exists()
    assert not transaction.journal.exists()


def test_one_shot_post_unlink_journal_sync_failure_is_healed(tmp_path: Path, monkeypatch):
    transaction = _write_synthetic_transaction(
        tmp_path,
        state="committed",
        before_present=False,
        after_present=False,
    )
    real_sync = persistence.sync_directory
    sync_calls = 0

    def _fail_first_sync(path: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            raise OSError("one-shot journal cleanup sync failure")
        real_sync(path)

    monkeypatch.setattr(persistence, "sync_directory", _fail_first_sync)

    result = recover_transaction(tmp_path)

    assert result.action == "cleaned_committed"
    assert sync_calls == 1
    assert transaction.destination.read_bytes() == b"after image\n"
    assert not transaction.journal.exists()


def test_persistent_post_unlink_journal_sync_failure_restores_exact_journal_for_retry(
    tmp_path: Path, monkeypatch
):
    transaction = _write_synthetic_transaction(
        tmp_path,
        state="committed",
        before_present=False,
        after_present=False,
    )
    journal_bytes = b" \r\n" + transaction.journal.read_bytes() + b"\r\n "
    transaction.journal.write_bytes(journal_bytes)
    real_sync = persistence.sync_directory
    sync_calls = 0

    def _fail_twice_then_sync(path: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls <= 2:
            raise OSError(f"persistent journal cleanup sync failure {sync_calls}")
        real_sync(path)

    monkeypatch.setattr(persistence, "sync_directory", _fail_twice_then_sync)
    monkeypatch.setattr(
        reconcile_transaction,
        "sync_directory",
        _fail_twice_then_sync,
        raising=False,
    )

    with pytest.raises(ReconcilePersistenceError) as caught:
        recover_transaction(tmp_path)

    assert "persistent journal cleanup sync failure 1" in str(caught.value)
    assert sync_calls >= 5
    assert transaction.journal.is_file()
    assert transaction.journal.read_bytes() == journal_bytes
    assert "remains for retry" in str(caught.value)
    primary = caught.value.__cause__
    assert isinstance(primary, OSError)
    assert str(primary) == "persistent journal cleanup sync failure 1"
    assert any("resync" in note for note in getattr(primary, "__notes__", []))

    monkeypatch.setattr(persistence, "sync_directory", real_sync)
    monkeypatch.setattr(reconcile_transaction, "sync_directory", real_sync)
    result = recover_transaction(tmp_path)

    assert result.action == "cleaned_committed"
    assert not transaction.journal.exists()
    assert list(tmp_path.glob(f"{RECONCILE_JOURNAL_NAME}.*.tmp")) == []
