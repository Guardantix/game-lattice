"""Serialize reconcile processes and recover durable transaction journals."""

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints
from pydantic import ValidationError as PydanticValidationError

from .constants import RECONCILE_JOURNAL_NAME, RECONCILE_JOURNAL_VERSION
from .error_types import ReconcileInProgressError, ReconcilePersistenceError
from .path_utils import safe_resolve
from .persistence import (
    atomic_create_bytes,
    durable_unlink,
    file_sha256,
    replace_staged,
    sync_directory,
)

JournalState = Literal["prepared", "committed"]
RecoveryAction = Literal["none", "rolled_back", "cleaned_committed"]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class JournalEntry(BaseModel):
    """One destination and its staged before and after images."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    destination: str
    before_path: str
    before_sha256: Sha256Digest
    after_path: str
    after_sha256: Sha256Digest


class Journal(BaseModel):
    """A versioned reconcile recovery journal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    state: JournalState
    entries: tuple[JournalEntry, ...]


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """The action taken for a project reconcile journal."""

    action: RecoveryAction
    journal: Path


@dataclass(frozen=True, slots=True)
class _ResolvedEntry:
    """Contained filesystem paths and fingerprints for one journal entry."""

    destination: Path
    before_path: Path
    before_sha256: str
    after_path: Path
    after_sha256: str


def _invalid_journal_error(journal: Path, cause: object) -> ReconcilePersistenceError:
    """Build the deliberate manual-remediation diagnostic for an invalid journal."""
    message = (
        f"invalid reconcile journal {journal}: {cause}; inspect {journal}, its destinations, "
        "and staged files; move the invalid journal aside only after manual restoration or "
        "preservation; rerun 'doc-lattice reconcile --recover'"
    )
    return ReconcilePersistenceError(message)


def _resolve_journal_path(project_root: Path, field: str, raw_path: str) -> Path:
    """Resolve one relative journal path while enforcing project containment."""
    path = Path(raw_path)
    if path.is_absolute():
        message = f"{field} must be relative, got {raw_path}"
        raise ValueError(message)
    try:
        return safe_resolve(project_root / path, project_root)
    except ValueError as cause:
        message = f"unsafe {field} {raw_path}: {cause}"
        raise ValueError(message) from cause


def _validate_path_roles(entries: tuple[_ResolvedEntry, ...], journal_path: Path) -> None:
    """Reject aliases between journal destinations and transaction artifacts."""
    canonical_journal = journal_path.resolve()
    destinations: dict[Path, int] = {}
    for index, entry in enumerate(entries):
        if entry.destination == canonical_journal:
            message = f"entry {index} destination aliases journal path {journal_path}"
            raise ValueError(message)
        if entry.destination in destinations:
            first = destinations[entry.destination]
            message = f"destination alias across entries {first} and {index}: {entry.destination}"
            raise ValueError(message)
        destinations[entry.destination] = index

    artifacts: dict[Path, tuple[int, str]] = {}
    for index, entry in enumerate(entries):
        for role, artifact in (
            ("before_path", entry.before_path),
            ("after_path", entry.after_path),
        ):
            if artifact == canonical_journal:
                message = f"entry {index} {role} aliases journal path {journal_path}"
                raise ValueError(message)
            if artifact in destinations:
                message = f"entry {index} {role} artifact {artifact} aliases destination path"
                raise ValueError(message)
            if artifact in artifacts:
                first_index, first_role = artifacts[artifact]
                message = (
                    f"artifact alias between entry {first_index} {first_role} and "
                    f"entry {index} {role}: {artifact}"
                )
                raise ValueError(message)
            artifacts[artifact] = (index, role)


def _load_journal(
    project_root: Path,
    journal_path: Path,
) -> tuple[Journal, tuple[_ResolvedEntry, ...], bytes]:
    """Read, validate, and contain every path in a reconcile journal."""
    try:
        encoded = journal_path.read_bytes()
        decoded = encoded.decode("utf-8")
        journal = Journal.model_validate_json(decoded)
    except (OSError, UnicodeDecodeError, PydanticValidationError) as cause:
        raise _invalid_journal_error(journal_path, cause) from cause
    if journal.version != RECONCILE_JOURNAL_VERSION:
        cause = ValueError(f"unsupported version {journal.version}")
        raise _invalid_journal_error(journal_path, cause) from cause
    try:
        entries = tuple(
            _ResolvedEntry(
                destination=_resolve_journal_path(project_root, "destination", entry.destination),
                before_path=_resolve_journal_path(project_root, "before_path", entry.before_path),
                before_sha256=entry.before_sha256,
                after_path=_resolve_journal_path(project_root, "after_path", entry.after_path),
                after_sha256=entry.after_sha256,
            )
            for entry in journal.entries
        )
    except ValueError as cause:
        raise _invalid_journal_error(journal_path, cause) from cause
    try:
        _validate_path_roles(entries, journal_path)
    except ValueError as cause:
        raise _invalid_journal_error(journal_path, cause) from cause
    return journal, entries, encoded


def _recovery_operation_error(
    operation: str,
    path: Path,
    journal: Path,
    cause: object,
) -> ReconcilePersistenceError:
    """Build a retryable recovery operation diagnostic."""
    journal_status = _journal_retry_status(journal)
    message = (
        f"reconcile recovery failed while {operation} {path}: {cause}; {journal_status}; "
        "correct the filesystem problem and rerun "
        "'doc-lattice reconcile --recover'"
    )
    return ReconcilePersistenceError(message)


def _journal_retry_status(journal: Path) -> str:
    """Describe only the journal state currently observable on disk."""
    if journal.is_file():
        return f"journal {journal} remains for retry"
    return f"journal {journal} is not present; preserve all available recovery artifacts"


def _unsafe_before_error(
    entry: _ResolvedEntry,
    journal: Path,
    state: str,
) -> ReconcilePersistenceError:
    """Build a diagnostic for an after-image that cannot be safely restored."""
    journal_status = _journal_retry_status(journal)
    message = (
        f"cannot safely recover destination {entry.destination}: it still matches the "
        f"transaction after image, but before image {entry.before_path} is {state}; journal "
        f"status: {journal_status}; restore the required before image or "
        "preserve the destination manually, then rerun 'doc-lattice reconcile --recover'"
    )
    return ReconcilePersistenceError(message)


def _resync_after_unlink(path: Path, primary: OSError) -> bool:
    """Retry parent synchronization only when an unlink already removed its path."""
    if path.exists():
        return False
    try:
        sync_directory(path.parent)
    except OSError as retry_error:
        primary.add_note(f"directory resync failed after unlink of {path}: {retry_error}")
        return False
    return True


def _cleanup_staged_artifact(staged: Path, journal: Path) -> None:
    """Remove one stage, healing a one-shot post-unlink sync failure."""
    was_absent = not staged.exists()
    try:
        durable_unlink(staged)
    except OSError as primary:
        if _resync_after_unlink(staged, primary):
            return
        raise _recovery_operation_error(
            "cleaning staged artifact", staged, journal, primary
        ) from primary
    if was_absent:
        try:
            sync_directory(staged.parent)
        except OSError as cause:
            raise _recovery_operation_error(
                "synchronizing absent staged artifact parent", staged, journal, cause
            ) from cause


def _restore_journal(journal: Path, journal_bytes: bytes, primary: OSError) -> None:
    """Best-effort restore an unlinked journal after persistent sync failure."""
    if journal.is_file():
        return
    try:
        atomic_create_bytes(
            journal,
            journal_bytes,
            prefix=f"{RECONCILE_JOURNAL_NAME}.",
        )
    except OSError as restore_error:
        primary.add_note(f"journal restoration failed for {journal}: {restore_error}")
    if not journal.is_file():
        primary.add_note(f"journal restoration left no regular file at {journal}")


def _cleanup_journal(journal: Path, journal_bytes: bytes) -> None:
    """Remove the journal last, restoring it if persistent post-unlink sync fails."""
    try:
        durable_unlink(journal)
    except OSError as primary:
        if _resync_after_unlink(journal, primary):
            return
        if not journal.exists():
            _restore_journal(journal, journal_bytes, primary)
        raise _recovery_operation_error("cleaning journal", journal, journal, primary) from primary


def _cleanup_transaction_artifacts(
    entries: tuple[_ResolvedEntry, ...],
    journal: Path,
    journal_bytes: bytes,
) -> None:
    """Durably remove staged images and then remove the journal last."""
    for entry in entries:
        for staged in (entry.before_path, entry.after_path):
            _cleanup_staged_artifact(staged, journal)
    _cleanup_journal(journal, journal_bytes)


def _rollback_prepared(
    entries: tuple[_ResolvedEntry, ...],
    journal: Path,
    journal_bytes: bytes,
) -> None:
    """Restore transaction-owned after-images while preserving unrelated changes."""
    for entry in reversed(entries):
        try:
            current_sha256 = file_sha256(entry.destination)
        except FileNotFoundError:
            continue
        except OSError as cause:
            raise _recovery_operation_error(
                "fingerprinting destination", entry.destination, journal, cause
            ) from cause
        if current_sha256 != entry.after_sha256:
            continue
        try:
            before_sha256 = file_sha256(entry.before_path)
        except FileNotFoundError as cause:
            raise _unsafe_before_error(entry, journal, "missing") from cause
        except OSError as cause:
            raise _recovery_operation_error(
                "fingerprinting before image", entry.before_path, journal, cause
            ) from cause
        if before_sha256 != entry.before_sha256:
            raise _unsafe_before_error(entry, journal, "corrupt")
        try:
            replace_staged(entry.before_path, entry.destination)
        except (OSError, ValueError) as cause:
            raise _recovery_operation_error(
                "restoring destination", entry.destination, journal, cause
            ) from cause
    _cleanup_transaction_artifacts(entries, journal, journal_bytes)


def _journal_path(project_root: Path) -> Path:
    """Return the reconcile journal path for a project root."""
    return project_root / RECONCILE_JOURNAL_NAME


@contextmanager
def reconcile_lock(project_root: Path) -> Iterator[None]:
    """Hold the existing project directory's nonblocking advisory reconcile lock.

    Args:
        project_root: The existing configured project-root directory.

    Yields:
        Control while this process exclusively holds the advisory lock.

    Raises:
        ReconcileInProgressError: If another reconcile process holds the lock.
        OSError: If the project directory cannot be opened or locked.
    """
    fd = os.open(project_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            message = "another reconcile is in progress; retry after it exits"
            raise ReconcileInProgressError(message) from None
        acquired = True
        yield
    finally:
        try:
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def ensure_dry_run_safe(project_root: Path) -> None:
    """Refuse a read-only dry run while a reconcile journal needs recovery.

    Args:
        project_root: The configured project root to inspect without mutation.

    Raises:
        ReconcilePersistenceError: If a reconcile journal already exists.
    """
    journal = _journal_path(project_root)
    if journal.exists():
        message = (
            f"reconcile journal {journal} requires recovery; "
            "run 'doc-lattice reconcile --recover' first"
        )
        raise ReconcilePersistenceError(message)


def recover_transaction(project_root: Path) -> RecoveryResult:
    """Recover or finish cleanup for a durable reconcile journal.

    Args:
        project_root: The configured project root containing transaction artifacts.

    Returns:
        The recovery action and project journal path.
    """
    journal = _journal_path(project_root)
    if not journal.exists():
        return RecoveryResult(action="none", journal=journal)
    loaded, entries, journal_bytes = _load_journal(project_root, journal)
    if loaded.state == "prepared":
        _rollback_prepared(entries, journal, journal_bytes)
        return RecoveryResult(action="rolled_back", journal=journal)
    _cleanup_transaction_artifacts(entries, journal, journal_bytes)
    return RecoveryResult(action="cleaned_committed", journal=journal)
