"""Boundary: validate a raw Linear GraphQL response into typed tickets.

This is the only linear module permitted ``Any`` and ``cast``: it converts the untyped JSON
envelope into typed ``Ticket`` models keyed by the identifier that was queried.
"""

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from .error_types import LinearError
from .tickets import Ticket, TicketRef, TicketState


def parse_tickets(
    response_text: str, alias_to_id: Mapping[str, str]
) -> tuple[dict[str, Ticket], set[str]]:
    """Parse a response into a ticket map keyed by queried id, plus the unresolved ids.

    Args:
        response_text: The raw response body from the transport.
        alias_to_id: The query's alias-to-identifier map.

    Returns:
        A tuple of the resolved tickets keyed by the queried identifier and the set of
        identifiers Linear returned ``null`` for.

    Raises:
        LinearError: On invalid JSON, a GraphQL ``errors`` array, a missing ``data`` object,
            or a malformed issue node.
    """
    try:
        parsed: Any = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise LinearError(f"Linear response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LinearError("Linear response was not a JSON object")
    if parsed.get("errors"):
        messages = "; ".join(
            str(e.get("message", "<no message>")) for e in parsed["errors"] if isinstance(e, dict)
        )
        raise LinearError(f"Linear returned GraphQL errors: {messages}")
    data = parsed.get("data")
    if not isinstance(data, dict):
        raise LinearError("Linear response is missing its data object")

    tickets: dict[str, Ticket] = {}
    unresolved: set[str] = set()
    for alias, identifier in alias_to_id.items():
        node = data.get(alias)
        if node is None:
            unresolved.add(identifier)
            continue
        tickets[identifier] = _ticket_from_node(node)
    return tickets, unresolved


def _state(raw: Any) -> TicketState:
    return TicketState(name=raw["name"], type=raw["type"])


def _ref(raw: Any) -> TicketRef:
    return TicketRef(
        identifier=raw["identifier"], title=raw.get("title"), state=_state(raw["state"])
    )


def _ticket_from_node(node: Any) -> Ticket:
    """Build a typed Ticket from one issue node, ignoring fields we did not request.

    Raises:
        LinearError: If a required field is missing or the node is malformed.
    """
    try:
        children_nodes = (node.get("children") or {}).get("nodes") or []
        parent_raw = node.get("parent")
        return Ticket(
            identifier=node["identifier"],
            title=node.get("title"),
            url=node["url"],
            state=_state(node["state"]),
            parent=_ref(parent_raw) if parent_raw else None,
            children=tuple(_ref(child) for child in children_nodes),
        )
    except (KeyError, TypeError, AttributeError, ValidationError) as exc:
        raise LinearError(f"Linear issue node was malformed: {exc}") from exc
