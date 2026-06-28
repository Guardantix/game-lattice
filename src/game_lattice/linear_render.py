"""Render stale-shipped findings as a severity-grouped table or a JSON payload."""

from collections.abc import Sequence

from rich.console import Console
from rich.markup import escape

from .text_utils import strip_control_chars
from .tickets import Finding, Ticket, TicketRef


def render_safe(text: str) -> str:
    """Make any external string safe to print: strip control bytes, then escape markup.

    Args:
        text: A string from a repo or a Linear response.

    Returns:
        The string with control bytes removed and rich markup escaped.
    """
    return escape(strip_control_chars(text))


def _ref_json(ref: TicketRef) -> dict:
    return {
        "identifier": ref.identifier,
        "title": ref.title,
        "state": {"name": ref.state.name, "type": ref.state.type},
    }


def _ticket_json(ticket: Ticket) -> dict:
    return {
        "identifier": ticket.identifier,
        "title": ticket.title,
        "url": ticket.url,
        "state": {"name": ticket.state.name, "type": ticket.state.type},
        "parent": _ref_json(ticket.parent) if ticket.parent is not None else None,
        "children": [_ref_json(child) for child in ticket.children],
    }


def findings_json(findings: Sequence[Finding]) -> dict:
    """Build the ``--json`` payload.

    Args:
        findings: The ordered findings.

    Returns:
        An object with a single ``findings`` key, each entry matching the spec 4.1
        shape.
    """
    return {
        "findings": [
            {
                "severity": finding.severity,
                "node_id": finding.node_id,
                "node_title": finding.node_title,
                "node_path": str(finding.node_path),
                "drifted_refs": list(finding.drifted_refs),
                "ticket_ref": finding.ticket_ref,
                "reason": finding.reason,
                "ticket": (_ticket_json(finding.ticket) if finding.ticket is not None else None),
            }
            for finding in findings
        ]
    }


def render_findings(console: Console, findings: Sequence[Finding]) -> None:
    """Print the findings grouped by severity, escaping every external string.

    Args:
        console: The output console.
        findings: The ordered findings.
    """
    if not findings:
        console.print("no stale-shipped findings")
        return
    colors = {
        "DANGER": "red",
        "BLOCKED": "magenta",
        "WARNING": "yellow",
        "INFO": "cyan",
    }
    for finding in findings:
        color = colors[finding.severity]
        refs = ", ".join(render_safe(ref) for ref in finding.drifted_refs)
        if finding.ticket is not None:
            detail = render_safe(f"{finding.ticket_ref} [{finding.ticket.state.name}]")
        else:
            detail = render_safe(f"{finding.ticket_ref} ({finding.reason})")
        console.print(
            f"[{color}]{finding.severity:<8}[/{color}] "
            f"{render_safe(finding.node_id)}  {detail}  drift: {refs}"
        )
