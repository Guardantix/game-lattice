"""The opt-in incremental load cache: read, tier selection, and atomic write.

The only module that touches the cache file. It resolves the cache path from an environment
mapping, validates the versioned single-file JSON schema as pydantic models, serves stat-tier
and verify-tier hits, and writes atomically after a successful load. It never raises on its own
behalf: a read failure yields an empty cache and a write failure emits one stderr diagnostic.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from . import __version__
from .constants import CACHE_FILE_NAME, CACHE_VERSION
from .model import NodeMeta


class StatRecord(BaseModel):
    """One checkout's stat hint for a file: byte size and nanosecond mtime."""

    model_config = ConfigDict(extra="forbid")

    size: int
    mtime_ns: int


class SectionRecordModel(BaseModel):
    """The serialized form of one anchored section span."""

    model_config = ConfigDict(extra="forbid")

    anchor: str
    start: int
    end: int


class NodePayload(BaseModel):
    """The cached derivation of a lattice node: validated meta, body, and section spans."""

    model_config = ConfigDict(extra="forbid")

    meta: NodeMeta
    body: str
    total_lines: int
    sections: list[SectionRecordModel]


class Entry(BaseModel):
    """One cached file: its content hash, per-root stat hints, and node payload (or null)."""

    model_config = ConfigDict(extra="forbid")

    file_sha256: str
    stats: dict[str, StatRecord]
    node: NodePayload | None


class CacheFile(BaseModel):
    """The whole cache document, version 1."""

    model_config = ConfigDict(extra="forbid")

    version: int
    tool_version: str
    roots: list[str]
    entries: dict[str, Entry]


def cache_home(env: Mapping[str, str]) -> Path:
    """Return the base cache directory per the XDG base directory spec.

    Args:
        env: The environment mapping to read ``XDG_CACHE_HOME`` and ``HOME`` from.

    Returns:
        ``$XDG_CACHE_HOME`` when it is set to an absolute path (a relative value is ignored
        per the spec), otherwise ``$HOME/.cache``, falling back to the user home directory.
    """
    xdg = env.get("XDG_CACHE_HOME", "")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg)
    home = env.get("HOME")
    base = Path(home) if home else Path.home()
    return base / ".cache"


def cache_path(cache_key: str, env: Mapping[str, str]) -> Path:
    """Return the cache file path for a slot.

    Args:
        cache_key: The validated single-segment cache slot name.
        env: The environment mapping used to resolve the cache home.

    Returns:
        ``<cache_home>/game-lattice/<cache_key>/load-cache.json``.
    """
    return cache_home(env) / "game-lattice" / cache_key / CACHE_FILE_NAME


class LoadCache:
    """Mutable in-memory cache state for one load run, backed by a single JSON file.

    Constructed by ``open``, mutated per discovered file by ``lookup`` and ``record_miss``,
    and persisted by ``finalize``. Never raises on its own behalf.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        path: Path,
        current_root: str,
        trust_stat: bool,
        require_verified: bool,
        entries: dict[str, Entry],
        roots: list[str],
        original: dict[str, object] | None,
    ) -> None:
        self._path = path
        self._current_root = current_root
        self._trust_stat = trust_stat and not require_verified
        self._entries = entries
        self._roots = roots
        self._original = original

    @property
    def is_empty(self) -> bool:
        """True when no valid cache file was loaded and no entries are held."""
        return not self._entries and self._original is None

    @classmethod
    def open(
        cls,
        *,
        cache_key: str,
        project_root: Path,
        env: Mapping[str, str],
        trust_stat: bool,
        require_verified: bool,
    ) -> "LoadCache":
        """Read and validate the cache file, returning an empty cache on any failure.

        The current project root is recorded as this run's stat key (its realpath). A missing,
        unreadable, invalid, wrong-version, or wrong-tool-version file is treated as empty:
        everything recomputes and the file is rewritten by ``finalize``.

        Args:
            cache_key: The validated cache slot name.
            project_root: The project root, used as this run's per-root stat key.
            env: The environment mapping for cache-path resolution.
            trust_stat: Whether the stat fast tier is enabled by config.
            require_verified: Whether this call forces the verify tier (the reconcile path).

        Returns:
            A LoadCache holding the loaded (or empty) state.
        """
        path = cache_path(cache_key, env)
        current_root = str(project_root.resolve())
        loaded = cls._read(path)
        if loaded is None:
            entries: dict[str, Entry] = {}
            roots: list[str] = []
            original: dict[str, object] | None = None
        else:
            entries = dict(loaded.entries)
            roots = list(loaded.roots)
            original = loaded.model_dump(mode="json")
        return cls(
            path=path,
            current_root=current_root,
            trust_stat=trust_stat,
            require_verified=require_verified,
            entries=entries,
            roots=roots,
            original=original,
        )

    @staticmethod
    def _read(path: Path) -> CacheFile | None:
        """Return the validated cache file, or None if it is missing, invalid, or stale."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        try:
            parsed = CacheFile.model_validate(data)
        except ValidationError:
            return None
        if parsed.version != CACHE_VERSION or parsed.tool_version != __version__:
            return None
        return parsed
