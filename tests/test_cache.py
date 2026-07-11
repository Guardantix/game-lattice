"""Tests for the opt-in incremental load cache."""

import json
from pathlib import Path

import pytest

from game_lattice import __version__
from game_lattice.cache import (
    CacheFile,
    Entry,
    LoadCache,
    NodePayload,
    SectionRecordModel,
    StatRecord,
    cache_home,
    cache_path,
)
from game_lattice.constants import CACHE_FILE_NAME, CACHE_VERSION
from game_lattice.model import NodeMeta


def _sample_cache_file() -> CacheFile:
    return CacheFile(
        version=CACHE_VERSION,
        tool_version=__version__,
        roots=["/abs/root"],
        entries={
            "docs/a.md": Entry(
                file_sha256="a" * 64,
                stats={"/abs/root": StatRecord(size=10, mtime_ns=123)},
                node=NodePayload(
                    meta=NodeMeta.model_validate({"id": "a"}),
                    body="# A\n",
                    total_lines=1,
                    sections=[SectionRecordModel(anchor="a-top", start=1, end=1)],
                ),
            ),
            "docs/plain.md": Entry(
                file_sha256="b" * 64,
                stats={"/abs/root": StatRecord(size=3, mtime_ns=456)},
                node=None,
            ),
        },
    )


def test_cache_file_round_trips_through_json():
    original = _sample_cache_file()
    dumped = original.model_dump_json()
    reloaded = CacheFile.model_validate_json(dumped)
    assert reloaded == original
    # The nested NodeMeta reloads as a validated NodeMeta, not a raw dict.
    reloaded_node = reloaded.entries["docs/a.md"].node
    assert reloaded_node is not None
    assert isinstance(reloaded_node.meta, NodeMeta)


def test_cache_home_uses_absolute_xdg():
    home = cache_home({"XDG_CACHE_HOME": "/custom/cache", "HOME": "/home/u"})
    assert home == Path("/custom/cache")


def test_cache_home_ignores_relative_xdg():
    home = cache_home({"XDG_CACHE_HOME": "relative/cache", "HOME": "/home/u"})
    assert home == Path("/home/u/.cache")


def test_cache_home_falls_back_to_home_dot_cache_when_xdg_unset():
    home = cache_home({"HOME": "/home/u"})
    assert home == Path("/home/u/.cache")


def test_cache_path_composes_slot_and_file_name():
    path = cache_path("my-docs", {"XDG_CACHE_HOME": "/c", "HOME": "/home/u"})
    assert path == Path("/c") / "game-lattice" / "my-docs" / CACHE_FILE_NAME


def _write_cache(path: Path, cache_file: CacheFile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cache_file.model_dump_json(), encoding="utf-8")


def _open(tmp_path: Path, *, trust_stat=False, require_verified=False) -> LoadCache:
    return LoadCache.open(
        cache_key="slot",
        project_root=tmp_path,
        env={"XDG_CACHE_HOME": str(tmp_path / "xdg")},
        trust_stat=trust_stat,
        require_verified=require_verified,
    )


def test_open_missing_file_is_empty(tmp_path: Path):
    cache = _open(tmp_path)
    assert cache.is_empty


def test_open_valid_file_loads_entries(tmp_path: Path):
    path = cache_path("slot", {"XDG_CACHE_HOME": str(tmp_path / "xdg")})
    _write_cache(path, _sample_cache_file())
    cache = _open(tmp_path)
    assert not cache.is_empty


@pytest.mark.parametrize(
    "text",
    [
        "",  # truncated / empty
        "{ not json",  # invalid JSON
        '{"version": 1}',  # schema violation (missing fields)
    ],
)
def test_open_corrupt_file_is_empty(tmp_path: Path, text: str):
    path = cache_path("slot", {"XDG_CACHE_HOME": str(tmp_path / "xdg")})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    assert _open(tmp_path).is_empty


def test_open_wrong_version_is_empty(tmp_path: Path):
    bad = _sample_cache_file().model_copy(update={"version": 999})
    path = cache_path("slot", {"XDG_CACHE_HOME": str(tmp_path / "xdg")})
    _write_cache(path, bad)
    assert _open(tmp_path).is_empty


def test_open_wrong_tool_version_is_empty(tmp_path: Path):
    bad = _sample_cache_file().model_copy(update={"tool_version": "0.0.0-other"})
    path = cache_path("slot", {"XDG_CACHE_HOME": str(tmp_path / "xdg")})
    _write_cache(path, bad)
    assert _open(tmp_path).is_empty


def test_open_invalid_meta_is_empty(tmp_path: Path):
    # A structurally valid file whose node.meta violates NodeMeta must discard wholesale.
    path = cache_path("slot", {"XDG_CACHE_HOME": str(tmp_path / "xdg")})
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _sample_cache_file().model_dump(mode="json")
    payload["entries"]["docs/a.md"]["node"]["meta"]["id"] = "bad#id"  # '#' is rejected by NodeMeta
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _open(tmp_path).is_empty
