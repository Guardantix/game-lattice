"""Tests for the linear renderer."""

import io
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from rich.console import Console

from game_lattice.linear_render import findings_json, render_findings, render_safe
from game_lattice.tickets import Finding, Ticket, TicketState


def _ticket():
    return Ticket(
        identifier="PC-1",
        title="Accent",
        url="https://x/PC-1",
        state=TicketState(name="Done", type="completed"),
        parent=None,
        children=(),
    )


def _danger():
    return Finding(
        severity="DANGER",
        node_id="pc-design",
        node_title="PC Design",
        node_path=Path("docs/pc-design.md"),
        drifted_refs=("art-direction#accent",),
        ticket_ref="PC-1",
        reason=None,
        ticket=_ticket(),
    )


def _blocked():
    return Finding(
        severity="BLOCKED",
        node_id="pc-design",
        node_title="PC Design",
        node_path=Path("docs/pc-design.md"),
        drifted_refs=("art-direction#motion",),
        ticket_ref="PC-999",
        reason="not-found",
        ticket=None,
    )


def test_json_shape_for_graded_and_blocked():
    payload = findings_json([_danger(), _blocked()])
    assert list(payload) == ["findings"]
    danger, blocked = payload["findings"]
    assert danger["ticket"]["state"]["type"] == "completed"
    assert danger["ticket_ref"] == "PC-1"
    assert blocked["ticket"] is None
    assert blocked["reason"] == "not-found"


@given(st.text())
def test_render_safe_is_idempotent_and_control_free(text: str):
    once = render_safe(text)
    assert render_safe(once) == once
    assert all(ord(ch) >= 0x20 and ord(ch) != 0x7F for ch in once)


def test_render_table_escapes_and_shows_severity():
    finding = Finding(
        severity="DANGER",
        node_id="node[/]",
        node_title=None,
        node_path=Path("docs/x.md"),
        drifted_refs=("ref\x1bx",),
        ticket_ref="PC-1",
        reason=None,
        ticket=_ticket(),
    )
    output = io.StringIO()
    console = Console(file=output, width=200)
    render_findings(console, [finding])
    out = output.getvalue()
    assert "DANGER" in out
    assert "\x1b" not in out  # control byte stripped
    assert "node[/]" in out  # markup-escaped, rendered literally


def test_render_does_not_let_state_name_inject_markup():
    ticket = Ticket(
        identifier="PC-1",
        title="t",
        url="https://x/PC-1",
        state=TicketState(name="bold red", type="completed"),  # a real rich style
        parent=None,
        children=(),
    )
    finding = Finding(
        severity="DANGER",
        node_id="n",
        node_title=None,
        node_path=Path("docs/x.md"),
        drifted_refs=("a#b",),
        ticket_ref="PC-1",
        reason=None,
        ticket=ticket,
    )
    output = io.StringIO()
    console = Console(file=output, width=200)
    render_findings(console, [finding])
    out = output.getvalue()
    assert "[bold red]" in out  # rendered literally, not consumed as a style tag
    assert "bold red" in out  # the state-name text is not lost
