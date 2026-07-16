"""Local filesystem operations for fixed managed GitHub CI artifacts."""

import difflib
import stat
from pathlib import Path, PurePosixPath

from doc_lattice.error_types import ConfigError, copy_exception_notes
from doc_lattice.path_utils import safe_resolve
from doc_lattice.persistence import atomic_create_bytes, atomic_replace_bytes

from .identity import parse_repository, validate_final_release_version
from .model import (
    ArtifactChange,
    ArtifactRole,
    ManagedArtifact,
    ManagedMarker,
)
from .render import BOOTSTRAP_PATH, LINEAR_WORKFLOW_PATH, OFFLINE_WORKFLOW_PATH

_CANONICAL_PATHS: dict[ArtifactRole, PurePosixPath] = {
    "offline": OFFLINE_WORKFLOW_PATH,
    "linear": LINEAR_WORKFLOW_PATH,
    "bootstrap": BOOTSTRAP_PATH,
}
_MARKER_PREFIXES = (
    "# doc-lattice-managed:",
    "# doc-lattice-artifact:",
    "# doc-lattice-version:",
    "# doc-lattice-repository:",
)
_MANAGED_SCHEMA_LINE = "# doc-lattice-managed: github-ci-v1"
_PARTIAL_STATE_NOTE = (
    "managed artifacts are applied in canonical order without rollback; earlier changes, "
    "if any, remain in place, so inspect the reported path and rerun to converge"
)


def preflight_create(
    root: Path,
    artifacts: tuple[ManagedArtifact, ...],
) -> tuple[ArtifactChange, ...]:
    """Inspect managed artifact destinations for a create operation.

    Args:
        root: Repository root containing the fixed artifact destinations.
        artifacts: Rendered artifacts in the order they should be inspected and applied.

    Returns:
        One exact planned change per artifact in input order.

    Raises:
        ConfigError: If a destination escapes the root, has an unsafe type, cannot be read,
            or contains bytes different from the requested artifact.
    """
    return _preflight(root, artifacts, refresh=False)


def preflight_refresh(
    root: Path,
    artifacts: tuple[ManagedArtifact, ...],
) -> tuple[ArtifactChange, ...]:
    """Inspect managed artifact destinations for a refresh operation.

    Args:
        root: Repository root containing the fixed artifact destinations.
        artifacts: Rendered artifacts in the order they should be inspected and applied.

    Returns:
        One exact planned change per artifact in input order.

    Raises:
        ConfigError: If a destination is unsafe or differing bytes do not contain a valid
            compatible ownership marker.
    """
    return _preflight(root, artifacts, refresh=True)


def render_diff(changes: tuple[ArtifactChange, ...]) -> str:
    """Render stable unified diffs for create and replace changes.

    Args:
        changes: Preflight changes in canonical presentation order.

    Returns:
        Unified diff text with exactly one trailing newline, or an empty string when every
        artifact is current.

    Raises:
        ConfigError: If replacement before-bytes are absent or are not UTF-8.
    """
    rendered_lines: list[str] = []
    for change in changes:
        if change.action == "current":
            continue
        relative_path = change.artifact.relative_path.as_posix()
        if change.action == "create":
            before_text = ""
            old_label = "/dev/null"
        else:
            if change.before is None:
                raise ConfigError(
                    f"replace diff is missing prior bytes for managed artifact {relative_path}"
                )
            try:
                before_text = change.before.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ConfigError(
                    f"prior bytes are not UTF-8 for managed artifact {relative_path}"
                ) from exc
            old_label = f"a/{relative_path}"
        diff = difflib.unified_diff(
            before_text.splitlines(keepends=True),
            change.artifact.text.splitlines(keepends=True),
            fromfile=old_label,
            tofile=f"b/{relative_path}",
            lineterm="",
        )
        rendered_lines.extend(_strip_diff_line_ending(line) for line in diff)
    return "\n".join(rendered_lines) + "\n" if rendered_lines else ""


def apply_changes(changes: tuple[ArtifactChange, ...]) -> None:
    """Apply preflighted managed artifact changes in input order.

    Args:
        changes: Exact preflight results to apply with contained durable writes.

    Raises:
        ConfigError: If containment, path type, or prior bytes changed after preflight, or
            if a durable create or replacement fails. Earlier successful writes are not
            rolled back and a later rerun can converge them.
    """
    for change in changes:
        if change.action == "current":
            continue
        try:
            if change.action == "create":
                _apply_create(change)
            else:
                _apply_replace(change)
        except ConfigError as error:
            if _PARTIAL_STATE_NOTE not in getattr(error, "__notes__", ()):
                error.add_note(_PARTIAL_STATE_NOTE)
            raise


def _preflight(
    root: Path,
    artifacts: tuple[ManagedArtifact, ...],
    *,
    refresh: bool,
) -> tuple[ArtifactChange, ...]:
    """Build exact changes without creating directories or writing files."""
    changes: list[ArtifactChange] = []
    for artifact in artifacts:
        _validate_artifact_path(artifact)
        logical_destination = root / artifact.relative_path
        destination = _resolve_destination(logical_destination, root, artifact, "inspect")
        before = _read_preflight_bytes(logical_destination, destination, root, artifact)
        desired = artifact.text.encode("utf-8")
        if before is None:
            action = "create"
        elif before == desired:
            action = "current"
        elif not refresh:
            path = artifact.relative_path.as_posix()
            raise ConfigError(
                "managed artifact already has different content and will not be "
                f"overwritten: {path}"
            )
        else:
            desired_marker = _parse_managed_marker(desired, artifact)
            prior_marker = _parse_managed_marker(before, artifact)
            desired_version = validate_final_release_version(desired_marker.version)
            prior_version = validate_final_release_version(prior_marker.version)
            if prior_version > desired_version:
                path = artifact.relative_path.as_posix()
                raise _marker_error(
                    path,
                    f"version {prior_marker.version!r} is newer than requested "
                    f"{desired_marker.version!r}",
                )
            action = "replace"
        changes.append(
            ArtifactChange(
                artifact=artifact,
                root=root,
                destination=destination,
                action=action,
                before=before,
            )
        )
    return tuple(changes)


def _validate_artifact_path(artifact: ManagedArtifact) -> None:
    """Require each artifact role to use its single fixed canonical path."""
    expected = _CANONICAL_PATHS.get(artifact.role)
    if expected is None:
        raise ConfigError(f"managed artifact has unsupported role {artifact.role!r}")
    if artifact.relative_path != expected:
        raise ConfigError(
            f"managed artifact role {artifact.role!r} must use canonical path "
            f"{expected.as_posix()}, not {artifact.relative_path.as_posix()}"
        )


def _resolve_destination(
    logical_destination: Path,
    root: Path,
    artifact: ManagedArtifact,
    operation: str,
) -> Path:
    """Resolve one fixed destination with typed path context."""
    path = artifact.relative_path.as_posix()
    try:
        return safe_resolve(logical_destination, root)
    except ValueError as exc:
        raise ConfigError(
            f"path resolves outside the repository root for managed artifact {path}: {exc}"
        ) from exc
    except (OSError, RuntimeError) as exc:
        error = ConfigError(f"cannot {operation} managed artifact: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc


def _read_preflight_bytes(
    logical_destination: Path,
    destination: Path,
    root: Path,
    artifact: ManagedArtifact,
) -> bytes | None:
    """Read exact existing bytes after rejecting symlinks and non-regular files."""
    path = artifact.relative_path.as_posix()
    try:
        target_stat = logical_destination.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        error = ConfigError(f"cannot inspect managed artifact: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc
    _require_regular_not_symlink(target_stat.st_mode, path)
    try:
        before = destination.read_bytes()
    except OSError as exc:
        error = ConfigError(f"cannot read managed artifact: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc

    resolved_after_read = _resolve_destination(
        logical_destination,
        root,
        artifact,
        "recheck",
    )
    if resolved_after_read != destination:
        raise ConfigError(f"managed artifact path changed during preflight: {path}")
    try:
        target_stat = logical_destination.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ConfigError(f"managed artifact path changed during preflight: {path}") from exc
    except OSError as exc:
        error = ConfigError(f"cannot recheck managed artifact: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc
    _require_regular_not_symlink(target_stat.st_mode, path)
    return before


def _require_regular_not_symlink(mode: int, path: str) -> None:
    """Reject final-component symlinks and every non-regular target type."""
    if stat.S_ISLNK(mode):
        raise ConfigError(f"symlink target is not allowed for managed artifact {path}")
    if not stat.S_ISREG(mode):
        raise ConfigError(f"existing target must be a regular file for managed artifact {path}")


def _parse_managed_marker(data: bytes, artifact: ManagedArtifact) -> ManagedMarker:
    """Parse the exact ownership header from existing managed artifact bytes."""
    path = artifact.relative_path.as_posix()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(
            f"UTF-8 ownership marker is required for managed artifact {path}"
        ) from exc
    lines = text.splitlines()
    offset = 1 if lines and lines[0] == "#!/usr/bin/env bash" else 0
    if len(lines) < offset + 4:
        raise _marker_error(path, "the four required ownership lines are missing")

    header = lines[offset : offset + 4]
    if header[0] != _MANAGED_SCHEMA_LINE:
        raise _marker_error(path, "managed schema must be exactly github-ci-v1")

    role_prefix = f"{_MARKER_PREFIXES[1]} "
    if not header[1].startswith(role_prefix):
        raise _marker_error(path, "artifact role line is missing or malformed")
    role = _parse_artifact_role(header[1][len(role_prefix) :], path)
    if role != artifact.role:
        raise _marker_error(
            path,
            f"artifact role {role!r} does not match canonical role {artifact.role!r}",
        )

    version_prefix = f"{_MARKER_PREFIXES[2]} "
    if not header[2].startswith(version_prefix):
        raise _marker_error(path, "version line is missing or malformed")
    version = header[2][len(version_prefix) :]
    try:
        validate_final_release_version(version)
    except ConfigError as exc:
        raise _marker_error(path, str(exc)) from exc

    repository_prefix = f"{_MARKER_PREFIXES[3]} "
    if not header[3].startswith(repository_prefix):
        raise _marker_error(path, "repository line is missing or malformed")
    repository_text = header[3][len(repository_prefix) :]
    try:
        repository = parse_repository(repository_text)
    except ConfigError as exc:
        raise _marker_error(path, str(exc)) from exc

    if any(line.startswith(prefix) for line in lines[offset + 4 :] for prefix in _MARKER_PREFIXES):
        raise _marker_error(path, "duplicate ownership line appears after the header")
    return ManagedMarker(role=role, version=version, repository=repository)


def _parse_artifact_role(value: str, path: str) -> ArtifactRole:
    """Validate and narrow one ownership marker artifact role."""
    if value == "offline":
        return "offline"
    if value == "linear":
        return "linear"
    if value == "bootstrap":
        return "bootstrap"
    raise _marker_error(path, f"artifact role {value!r} is not recognized")


def _marker_error(path: str, detail: str) -> ConfigError:
    """Build one path-specific ownership marker error."""
    return ConfigError(f"invalid ownership marker for managed artifact {path}: {detail}")


def _strip_diff_line_ending(line: str) -> str:
    """Normalize difflib line records for stable joined output."""
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\r", "\n")):
        return line[:-1]
    return line


def _apply_create(change: ArtifactChange) -> None:
    """Create one absent artifact without replacing a concurrent winner."""
    artifact = change.artifact
    _validate_artifact_path(artifact)
    path = artifact.relative_path.as_posix()
    logical_destination, destination = _resolve_change(change)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        error = ConfigError(f"cannot create managed artifact parent: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc
    logical_destination, destination = _resolve_change(change)
    try:
        target_stat = logical_destination.stat(follow_symlinks=False)
    except FileNotFoundError:
        pass
    except OSError as exc:
        error = ConfigError(f"cannot inspect create destination: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc
    else:
        if stat.S_ISLNK(target_stat.st_mode):
            raise ConfigError(f"symlink appeared after preflight for managed artifact {path}")
        raise ConfigError(f"destination appeared after preflight for managed artifact {path}")
    try:
        atomic_create_bytes(
            destination,
            artifact.text.encode("utf-8"),
            prefix=f".{destination.name}.doc-lattice-create.",
        )
    except FileExistsError as exc:
        error = ConfigError(f"destination appeared after preflight for managed artifact {path}")
        copy_exception_notes(error, exc)
        raise error from exc
    except OSError as exc:
        error = ConfigError(f"cannot write managed artifact: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc


def _apply_replace(change: ArtifactChange) -> None:
    """Replace one artifact only while its exact preflight bytes remain current."""
    artifact = change.artifact
    _validate_artifact_path(artifact)
    path = artifact.relative_path.as_posix()
    if change.before is None:
        raise ConfigError(f"replace change is missing prior bytes for managed artifact {path}")
    logical_destination, destination = _resolve_change(change)
    current = _read_apply_bytes(logical_destination, destination, artifact)
    if current != change.before:
        raise ConfigError(f"destination changed after preflight for managed artifact {path}")

    logical_destination, destination = _resolve_change(change)
    current = _read_apply_bytes(logical_destination, destination, artifact)
    if current != change.before:
        raise ConfigError(f"destination changed after preflight for managed artifact {path}")
    try:
        atomic_replace_bytes(
            destination,
            artifact.text.encode("utf-8"),
            prefix=f".{destination.name}.doc-lattice-replace.",
        )
    except OSError as exc:
        error = ConfigError(f"cannot write managed artifact: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc


def _resolve_change(change: ArtifactChange) -> tuple[Path, Path]:
    """Re-resolve and authenticate one preflight destination before mutation."""
    artifact = change.artifact
    logical_destination = change.root / artifact.relative_path
    destination = _resolve_destination(
        logical_destination,
        change.root,
        artifact,
        "resolve",
    )
    if destination != change.destination:
        path = artifact.relative_path.as_posix()
        raise ConfigError(f"managed artifact path changed after preflight: {path}")
    return logical_destination, destination


def _read_apply_bytes(
    logical_destination: Path,
    destination: Path,
    artifact: ManagedArtifact,
) -> bytes:
    """Read exact replacement bytes while enforcing the current target type."""
    path = artifact.relative_path.as_posix()
    try:
        target_stat = logical_destination.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ConfigError(
            f"destination changed after preflight for managed artifact {path}"
        ) from exc
    except OSError as exc:
        error = ConfigError(f"cannot inspect replacement destination: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc
    _require_regular_not_symlink(target_stat.st_mode, path)
    try:
        return destination.read_bytes()
    except OSError as exc:
        error = ConfigError(f"cannot read replacement destination: {exc}; path {path}")
        copy_exception_notes(error, exc)
        raise error from exc
