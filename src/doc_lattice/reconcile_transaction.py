"""Serialize reconcile processes and recover durable transaction journals."""

import fcntl
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
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

    version: int = Field(strict=True)
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
    except (OSError, RuntimeError, ValueError) as cause:
        message = f"unsafe {field} {raw_path}: {cause}"
        raise ValueError(message) from cause


def _validate_artifact_path(
    project_root: Path,
    destination: Path,
    artifact: Path,
    role: str,
    raw_path: str,
) -> None:
    """Validate the location, name, and existing type of one staged artifact."""
    field = f"{role}_path"
    candidate = project_root / Path(raw_path)
    if artifact.parent != destination.parent:
        message = (
            f"{field} {raw_path} ({artifact}) must be in destination directory {destination.parent}"
        )
        raise ValueError(message)
    prefix = f".{destination.name}.doc-lattice-{role}."
    suffix = ".tmp"
    name = Path(raw_path).name
    component = name[len(prefix) : -len(suffix)]
    if not name.startswith(prefix) or not name.endswith(suffix) or not component:
        message = f"{field} {raw_path} ({artifact}) must match {prefix}<nonempty>{suffix} exactly"
        raise ValueError(message)
    if candidate.is_symlink():
        message = f"{field} {raw_path} ({artifact}) is a symlink, not a recovery artifact"
        raise ValueError(message)
    try:
        mode = candidate.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as cause:
        message = f"cannot inspect {field} {raw_path} ({artifact}): {cause}"
        raise ValueError(message) from cause
    if not stat.S_ISREG(mode):
        message = f"{field} {raw_path} ({artifact}) is a nonregular recovery artifact"
        raise ValueError(message)


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
        for raw_entry, entry in zip(journal.entries, entries, strict=True):
            _validate_artifact_path(
                project_root,
                entry.destination,
                entry.before_path,
                "before",
                raw_entry.before_path,
            )
            _validate_artifact_path(
                project_root,
                entry.destination,
                entry.after_path,
                "after",
                raw_entry.after_path,
            )
    except ValueError as cause:
        raise _invalid_journal_error(journal_path, cause) from cause
    return journal, entries, encoded


def _recovery_operation_error(
    operation: str,
    path: Path,
    journal: Path,
    journal_bytes: bytes,
    cause: object,
) -> ReconcilePersistenceError:
    """Build a retryable recovery operation diagnostic."""
    journal_status = _journal_retry_status(journal, journal_bytes)
    cause_details = _cause_details(cause)
    message = (
        f"reconcile recovery failed while {operation} {path}: {cause_details}; "
        f"{journal_status}; correct the filesystem problem and rerun "
        "'doc-lattice reconcile --recover'"
    )
    return ReconcilePersistenceError(message)


def _cause_details(cause: object) -> str:
    """Render an operation cause plus diagnostic notes into top-level text."""
    details = [str(cause)]
    details.extend(str(note) for note in getattr(cause, "__notes__", ()))
    return "; ".join(details)


def _exact_journal_status(journal: Path, journal_bytes: bytes) -> tuple[str, str]:
    """Classify whether the canonical journal is a regular exact-byte copy."""
    try:
        mode = journal.lstat().st_mode
    except FileNotFoundError:
        return "absent", f"journal {journal} is not present"
    except OSError as cause:
        return "invalid", f"cannot inspect journal {journal}: {cause}"
    if not stat.S_ISREG(mode):
        return "invalid", f"journal collision at {journal} is not a regular file"
    try:
        current_bytes = journal.read_bytes()
    except OSError as cause:
        return "invalid", f"cannot read journal {journal}: {cause}"
    if current_bytes != journal_bytes:
        return "invalid", f"journal collision at {journal} contains different bytes"
    return "exact", f"journal {journal} is an exact recovery copy"


def _journal_retry_status(journal: Path, journal_bytes: bytes) -> str:
    """Describe only journal bytes verified at the canonical path."""
    status, detail = _exact_journal_status(journal, journal_bytes)
    if status == "exact":
        return f"journal {journal} remains for retry"
    if status == "absent":
        return f"{detail}; preserve all available recovery artifacts"
    return f"exact recovery journal could not be restored: {detail}"


def _unsafe_before_error(
    entry: _ResolvedEntry,
    journal: Path,
    journal_bytes: bytes,
    state: str,
) -> ReconcilePersistenceError:
    """Build a diagnostic for an after-image that cannot be safely restored."""
    journal_status = _journal_retry_status(journal, journal_bytes)
    message = (
        f"cannot safely recover destination {entry.destination}: it still matches the "
        f"transaction after image, but before image {entry.before_path} is {state}; journal "
        f"status: {journal_status}; restore the required before image or "
        "preserve the destination manually, then rerun 'doc-lattice reconcile --recover'"
    )
    return ReconcilePersistenceError(message)


def _unsafe_artifact_error(
    staged: Path,
    destination: Path,
    journal: Path,
    journal_bytes: bytes,
    state: str,
) -> ReconcilePersistenceError:
    """Build a manual-recovery diagnostic for an unauthenticated stage."""
    journal_status = _journal_retry_status(journal, journal_bytes)
    message = (
        f"cannot safely clean staged artifact {staged} for destination {destination}: "
        f"{state}; {journal_status}; preserve the artifact and journal for manual inspection, "
        "correct the recovery evidence, then rerun 'doc-lattice reconcile --recover'"
    )
    return ReconcilePersistenceError(message)


def _nearest_existing_directory(path: Path, project_root: Path) -> Path:
    """Find the closest existing directory at or above a contained path."""
    current = path
    while True:
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if current == project_root:
                raise
            current = current.parent
            continue
        if not stat.S_ISDIR(mode):
            message = f"recovery synchronization ancestor is not a directory: {current}"
            raise NotADirectoryError(message)
        return current


def _sync_artifact_parent(path: Path, project_root: Path) -> None:
    """Synchronize an artifact parent or its nearest existing contained ancestor."""
    sync_directory(_nearest_existing_directory(path.parent, project_root))


def _resync_after_unlink(path: Path, project_root: Path, primary: OSError) -> bool:
    """Retry parent synchronization only when an unlink already removed its path."""
    if path.exists():
        return False
    try:
        _sync_artifact_parent(path, project_root)
    except OSError as retry_error:
        primary.add_note(f"directory resync failed after unlink of {path}: {retry_error}")
        return False
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError as retry_error:
        primary.add_note(f"cannot verify absence after resync of {path}: {retry_error}")
        return False
    primary.add_note(f"path reappeared during directory resync after unlink of {path}")
    return False


def _authenticate_staged_artifact(
    staged: Path,
    expected_sha256: str,
    destination: Path,
    journal: Path,
    journal_bytes: bytes,
) -> bool:
    """Return whether a present stage is a regular file with its recorded digest."""
    try:
        initial_stat = staged.lstat()
    except FileNotFoundError:
        return False
    except OSError as cause:
        state = f"cannot inspect artifact: {cause}"
        raise _unsafe_artifact_error(staged, destination, journal, journal_bytes, state) from cause
    if not stat.S_ISREG(initial_stat.st_mode):
        raise _unsafe_artifact_error(
            staged,
            destination,
            journal,
            journal_bytes,
            "artifact is not a regular file",
        )
    try:
        actual_sha256 = file_sha256(staged)
    except FileNotFoundError:
        return False
    except OSError as cause:
        raise _unsafe_artifact_error(
            staged,
            destination,
            journal,
            journal_bytes,
            f"cannot read artifact: {cause}",
        ) from cause
    try:
        verified_stat = staged.lstat()
    except FileNotFoundError:
        return False
    except OSError as cause:
        state = f"cannot re-inspect artifact after reading: {cause}"
        raise _unsafe_artifact_error(staged, destination, journal, journal_bytes, state) from cause
    initial_identity = (initial_stat.st_dev, initial_stat.st_ino)
    verified_identity = (verified_stat.st_dev, verified_stat.st_ino)
    if not stat.S_ISREG(verified_stat.st_mode) or verified_identity != initial_identity:
        state = "artifact changed or became nonregular during authentication"
        raise _unsafe_artifact_error(staged, destination, journal, journal_bytes, state)
    if actual_sha256 != expected_sha256:
        state = (
            f"artifact is corrupt: digest mismatch "
            f"(expected {expected_sha256}, got {actual_sha256})"
        )
        raise _unsafe_artifact_error(staged, destination, journal, journal_bytes, state)
    return True


def _cleanup_staged_artifact(
    staged: Path,
    expected_sha256: str,
    destination: Path,
    journal: Path,
    journal_bytes: bytes,
) -> None:
    """Remove one authenticated stage, healing a post-unlink sync failure."""
    is_present = _authenticate_staged_artifact(
        staged, expected_sha256, destination, journal, journal_bytes
    )
    if not is_present:
        try:
            _sync_artifact_parent(staged, journal.parent)
        except OSError as cause:
            raise _recovery_operation_error(
                "synchronizing absent staged artifact parent",
                staged,
                journal,
                journal_bytes,
                cause,
            ) from cause
        try:
            staged.lstat()
        except FileNotFoundError:
            return
        except OSError as cause:
            state = f"cannot verify artifact absence after synchronization: {cause}"
            raise _unsafe_artifact_error(
                staged, destination, journal, journal_bytes, state
            ) from cause
        state = "artifact appeared while synchronizing its previously observed absence"
        raise _unsafe_artifact_error(staged, destination, journal, journal_bytes, state)
    try:
        durable_unlink(staged)
    except OSError as primary:
        if _resync_after_unlink(staged, journal.parent, primary):
            return
        raise _recovery_operation_error(
            "cleaning staged artifact", staged, journal, journal_bytes, primary
        ) from primary


def _restore_journal(journal: Path, journal_bytes: bytes, primary: OSError) -> bool:
    """Restore exact bytes only when the canonical journal path is absent."""
    status, detail = _exact_journal_status(journal, journal_bytes)
    if status == "exact":
        return True
    if status != "absent":
        primary.add_note(
            f"exact recovery journal could not be restored: {detail}; refusing to overwrite"
        )
        return False
    try:
        atomic_create_bytes(
            journal,
            journal_bytes,
            prefix=f"{RECONCILE_JOURNAL_NAME}.",
        )
    except OSError as restore_error:
        primary.add_note(f"journal restoration failed for {journal}: {restore_error}")
    status, detail = _exact_journal_status(journal, journal_bytes)
    if status == "exact":
        return True
    primary.add_note(f"exact recovery journal could not be restored: {detail}")
    return False


def _cleanup_journal(journal: Path, journal_bytes: bytes) -> None:
    """Remove the journal last, restoring it if persistent post-unlink sync fails."""
    try:
        durable_unlink(journal)
    except OSError as primary:
        if _resync_after_unlink(journal, journal.parent, primary):
            return
        _restore_journal(journal, journal_bytes, primary)
        raise _recovery_operation_error(
            "cleaning journal", journal, journal, journal_bytes, primary
        ) from primary


def _cleanup_transaction_artifacts(
    entries: tuple[_ResolvedEntry, ...],
    journal: Path,
    journal_bytes: bytes,
) -> None:
    """Durably remove staged images and then remove the journal last."""
    staged_artifacts = _staged_artifacts(entries)
    _authenticate_transaction_artifacts(staged_artifacts, journal, journal_bytes)
    for staged, expected_sha256, destination in staged_artifacts:
        _cleanup_staged_artifact(
            staged,
            expected_sha256,
            destination,
            journal,
            journal_bytes,
        )
    _cleanup_journal(journal, journal_bytes)


def _staged_artifacts(
    entries: tuple[_ResolvedEntry, ...],
) -> tuple[tuple[Path, str, Path], ...]:
    """Return every journal stage paired with its role-specific digest."""
    return tuple(
        staged
        for entry in entries
        for staged in (
            (entry.before_path, entry.before_sha256, entry.destination),
            (entry.after_path, entry.after_sha256, entry.destination),
        )
    )


def _authenticate_transaction_artifacts(
    staged_artifacts: tuple[tuple[Path, str, Path], ...],
    journal: Path,
    journal_bytes: bytes,
) -> None:
    """Authenticate every present stage before any recovery mutation begins."""
    for staged, expected_sha256, destination in staged_artifacts:
        _authenticate_staged_artifact(
            staged,
            expected_sha256,
            destination,
            journal,
            journal_bytes,
        )


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
                "fingerprinting destination",
                entry.destination,
                journal,
                journal_bytes,
                cause,
            ) from cause
        if current_sha256 != entry.after_sha256:
            continue
        is_present = _authenticate_staged_artifact(
            entry.before_path,
            entry.before_sha256,
            entry.destination,
            journal,
            journal_bytes,
        )
        if not is_present:
            raise _unsafe_before_error(entry, journal, journal_bytes, "missing")
        try:
            replace_staged(entry.before_path, entry.destination)
        except (OSError, ValueError) as cause:
            raise _recovery_operation_error(
                "restoring destination",
                entry.destination,
                journal,
                journal_bytes,
                cause,
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
        ReconcilePersistenceError: If releasing or closing the lock fails after success.
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
        active_error = sys.exception()
        cleanup_errors: list[tuple[str, OSError]] = []
        try:
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError as cause:
            cleanup_errors.append(("lock release", cause))
        try:
            os.close(fd)
        except OSError as cause:
            cleanup_errors.append(("lock close", cause))
        if cleanup_errors:
            details = "; ".join(f"{phase} failed: {cause}" for phase, cause in cleanup_errors)
            if active_error is not None:
                active_error.add_note(f"reconcile {details}")
            else:
                message = f"reconcile {details} for project directory {project_root}"
                error = ReconcilePersistenceError(message)
                raise error from cleanup_errors[0][1]


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
    _authenticate_transaction_artifacts(_staged_artifacts(entries), journal, journal_bytes)
    if loaded.state == "prepared":
        _rollback_prepared(entries, journal, journal_bytes)
        return RecoveryResult(action="rolled_back", journal=journal)
    _cleanup_transaction_artifacts(entries, journal, journal_bytes)
    return RecoveryResult(action="cleaned_committed", journal=journal)
