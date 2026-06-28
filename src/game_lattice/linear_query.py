"""Pure construction of the batched Linear GraphQL query and identifier partition."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .constants import BlockedReason
from .error_types import ConfigError, LinearError

BATCH_SIZE = 50
MAX_IDENTIFIERS = 500

# Anchored with \A...\Z, not ^...$: in Python ``$`` also matches just before a trailing
# newline, so a value like "PC-1\n" would slip past ``^...$``. \Z matches only the very end.
_IDENTIFIER_RE = re.compile(r"\A[A-Z][A-Z0-9]*-[0-9]+\Z", re.ASCII)
_TEAM_RE = re.compile(r"\A[A-Z][A-Z0-9]*\Z", re.ASCII)

_TICKET_FRAGMENT = """
fragment T on Issue {
  identifier
  title
  url
  state { name type }
  parent { identifier title state { name type } }
  children(first: 50) { nodes { identifier title state { name type } } }
}
"""


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """A built query: the document, its variables, and the alias-to-identifier map."""

    document: str
    variables: dict[str, str]
    alias_to_id: dict[str, str]


def partition_identifiers(
    identifiers: Iterable[str], linear_team: str | None
) -> tuple[list[str], dict[str, BlockedReason]]:
    """Split identifiers into the set to query and the refs refused before any fetch.

    Args:
        identifiers: Raw ``tickets:`` values, possibly with duplicates.
        linear_team: The configured team key, or None for no team boundary.

    Returns:
        A tuple of the valid identifiers (deduplicated, order preserved) and a map of each
        refused ref to ``"malformed"`` or ``"cross-team"``.

    Raises:
        ConfigError: If ``linear_team`` is set but is not a valid team key.
        LinearError: If the distinct identifier count exceeds ``MAX_IDENTIFIERS``.
    """
    if linear_team is not None and not _TEAM_RE.match(linear_team):
        msg = f"linear_team {linear_team!r} is not a valid team key; fix .game-lattice.yml"
        raise ConfigError(msg)
    distinct = list(dict.fromkeys(identifiers))
    if len(distinct) > MAX_IDENTIFIERS:
        msg = (
            f"too many referenced tickets ({len(distinct)} > {MAX_IDENTIFIERS}); "
            "narrow the scope with a positional target or --from"
        )
        raise LinearError(msg)
    valid: list[str] = []
    rejected: dict[str, BlockedReason] = {}
    for ref in distinct:
        if not _IDENTIFIER_RE.match(ref):
            rejected[ref] = "malformed"
        elif linear_team is not None and ref.split("-", 1)[0] != linear_team:
            rejected[ref] = "cross-team"
        else:
            valid.append(ref)
    return valid, rejected


def chunk_identifiers(identifiers: Sequence[str], size: int = BATCH_SIZE) -> list[list[str]]:
    """Split identifiers into batches of at most ``size``.

    Args:
        identifiers: The valid identifiers to query.
        size: The maximum batch size.

    Returns:
        A list of batches; empty input yields an empty list.
    """
    return [list(identifiers[i : i + size]) for i in range(0, len(identifiers), size)]


def build_query(identifiers: Sequence[str]) -> QueryPlan:
    """Build one aliased batched query for the given identifiers.

    Args:
        identifiers: The identifiers in a single batch (at most ``BATCH_SIZE``).

    Returns:
        A QueryPlan whose document fetches each identifier under an index alias, passes the
        identifiers as variables, and records the alias-to-identifier map for keying results.
    """
    var_decls: list[str] = []
    fields: list[str] = []
    variables: dict[str, str] = {}
    alias_to_id: dict[str, str] = {}
    for index, identifier in enumerate(identifiers):
        var = f"id{index}"
        alias = f"i{index}"
        var_decls.append(f"${var}: String!")
        fields.append(f"  {alias}: issue(id: ${var}) {{ ...T }}")
        variables[var] = identifier
        alias_to_id[alias] = identifier
    document = "query Batch(" + ", ".join(var_decls) + ") {\n" + "\n".join(fields) + "\n}\n"
    document += _TICKET_FRAGMENT
    return QueryPlan(document=document, variables=variables, alias_to_id=alias_to_id)
