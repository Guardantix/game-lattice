"""Tests for the linear query builder and identifier partition."""

import pytest

from game_lattice.error_types import ConfigError, LinearError
from game_lattice.linear_query import (
    BATCH_SIZE,
    MAX_IDENTIFIERS,
    build_query,
    chunk_identifiers,
    partition_identifiers,
)


def test_partition_splits_valid_and_malformed():
    valid, rejected = partition_identifiers(["PC-228", "not-a-ticket", "", "  "], None)
    assert valid == ["PC-228"]
    assert rejected == {"not-a-ticket": "malformed", "": "malformed", "  ": "malformed"}


def test_partition_dedupes_preserving_order():
    valid, _ = partition_identifiers(["PC-2", "PC-1", "PC-2"], None)
    assert valid == ["PC-2", "PC-1"]


def test_partition_rejects_non_ascii_digits():
    # Arabic-Indic digits must not pass the ASCII identifier guard.
    valid, rejected = partition_identifiers(["PC-٢٣"], None)
    assert valid == []
    assert rejected["PC-٢٣"] == "malformed"


def test_partition_tags_cross_team_when_team_set():
    valid, rejected = partition_identifiers(["PC-1", "SEC-9"], "PC")
    assert valid == ["PC-1"]
    assert rejected == {"SEC-9": "cross-team"}


def test_partition_queries_off_team_when_no_team_set():
    valid, rejected = partition_identifiers(["SEC-9"], None)
    assert valid == ["SEC-9"]
    assert rejected == {}


def test_partition_rejects_malformed_team_key():
    with pytest.raises(ConfigError):
        partition_identifiers(["PC-1"], "p c")


def test_partition_cap_raises_one_over_but_not_at_cap():
    at_cap = [f"PC-{i}" for i in range(MAX_IDENTIFIERS)]
    valid, _ = partition_identifiers(at_cap, None)
    assert len(valid) == MAX_IDENTIFIERS
    over = [f"PC-{i}" for i in range(MAX_IDENTIFIERS + 1)]
    with pytest.raises(LinearError):
        partition_identifiers(over, None)


def test_chunking_boundary():
    exactly = [f"PC-{i}" for i in range(BATCH_SIZE)]
    assert len(chunk_identifiers(exactly)) == 1
    one_more = [f"PC-{i}" for i in range(BATCH_SIZE + 1)]
    assert len(chunk_identifiers(one_more)) == 2


def test_build_query_is_read_only_and_parameterized():
    plan = build_query(["PC-1", "PC-2"])
    assert "query" in plan.document
    assert "mutation" not in plan.document
    # Identifiers travel as variables, never interpolated into the document text.
    assert "PC-1" not in plan.document
    assert set(plan.variables.values()) == {"PC-1", "PC-2"}
    assert set(plan.alias_to_id.values()) == {"PC-1", "PC-2"}
    assert len(set(plan.alias_to_id)) == 2  # aliases are unique
