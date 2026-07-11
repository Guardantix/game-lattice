"""The opt-in incremental load cache: read, tier selection, and atomic write.

The only module that touches the cache file. It resolves the cache path from an environment
mapping, validates the versioned single-file JSON schema as pydantic models, serves stat-tier
and verify-tier hits, and writes atomically after a successful load. It never raises on its own
behalf: a read failure yields an empty cache and a write failure emits one stderr diagnostic.
"""

from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .constants import CACHE_FILE_NAME
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
