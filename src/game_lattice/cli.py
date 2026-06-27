"""Command-line interface."""

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from . import __version__
from .check import check_lattice, has_drift
from .config import load_config
from .error_types import ProjectError
from .impact import impact as impact_walk
from .model import Lattice
from .orchestrate import load_lattice
from .reconcile import apply_reconcile
from .reconcile import reconcile as plan_reconcile
from .render import to_dot, to_mermaid

app = typer.Typer(no_args_is_help=True, add_completion=False)
_out = Console()
_err = Console(stderr=True)

ConfigOpt = Annotated[Path | None, typer.Option("--config", help="Path to .game-lattice.yml.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")]


def _version_callback(value: bool) -> None:
    if value:
        _out.print(__version__)
        raise typer.Exit


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """game-lattice: documentation traceability engine."""


def _load(config: Path | None) -> Lattice:
    project = load_config(config, Path.cwd())
    return load_lattice(project)


@app.command()
def check(config: ConfigOpt = None, json_out: JsonOpt = False) -> None:
    """Classify every edge; exit 1 on drift, 2 on tool error."""
    try:
        lattice = _load(config)
        statuses = check_lattice(lattice)
    except ProjectError as exc:
        _err.print(f"[red]error[/red]: {exc} ({exc.code})")
        raise typer.Exit(2) from exc
    if json_out:
        payload = {
            "edges": [
                {
                    "source_id": s.source_id,
                    "target_ref": s.target_ref,
                    "target_id": s.target_id,
                    "state": s.state,
                    "expected": s.expected,
                    "actual": s.actual,
                }
                for s in statuses
            ]
        }
        typer.echo(json.dumps(payload))
    else:
        state_colors = {"OK": "green", "STALE": "yellow", "UNRECONCILED": "yellow", "BROKEN": "red"}
        for s in statuses:
            color = state_colors[s.state]
            _out.print(f"[{color}]{s.state:<13}[/{color}] {s.source_id} -> {s.target_ref}")
    raise typer.Exit(1 if has_drift(statuses) else 0)


@app.command()
def impact(token: str, config: ConfigOpt = None, json_out: JsonOpt = False) -> None:
    """List every downstream doc affected by a change to TOKEN."""
    try:
        lattice = _load(config)
        affected = impact_walk(lattice, token)
    except ProjectError as exc:
        _err.print(f"[red]error[/red]: {exc} ({exc.code})")
        raise typer.Exit(2) from exc
    if json_out:
        payload = {
            "affected": [
                {"id": n.id, "title": n.title, "path": str(n.path), "tickets": list(n.tickets)}
                for n in affected
            ]
        }
        typer.echo(json.dumps(payload))
    else:
        for n in affected:
            tickets = ", ".join(n.tickets) if n.tickets else "-"
            _out.print(f"{n.id}  ({n.path})  tickets: {tickets}")


@app.command()
def reconcile(
    downstream_id: str,
    ref: Annotated[
        str | None, typer.Option("--ref", help="Reconcile only this upstream ref.")
    ] = None,
    reconcile_all: Annotated[
        bool, typer.Option("--all", help="Reconcile every drifting edge.")
    ] = False,
    config: ConfigOpt = None,
) -> None:
    """Set seen to current upstream hashes for the selected edges."""
    try:
        lattice = _load(config)
        plan = plan_reconcile(lattice, downstream_id, ref=ref, reconcile_all=reconcile_all)
        for path, updates in plan.items():
            fresh = path.read_text(encoding="utf-8")
            new_text = apply_reconcile(fresh, updates)
            _atomic_write(path, new_text)
            for target_ref in updates:
                _out.print(f"reconciled {path.name}: {target_ref}")
    except ProjectError as exc:
        _err.print(f"[red]error[/red]: {exc} ({exc.code})")
        raise typer.Exit(2) from exc


@app.command()
def graph(
    fmt: Annotated[str, typer.Option("--format", help="mermaid or dot.")] = "mermaid",
    config: ConfigOpt = None,
) -> None:
    """Emit the edge graph as Mermaid or DOT."""
    try:
        lattice = _load(config)
        stale = {
            (s.source_id, s.target_id)
            for s in check_lattice(lattice)
            if s.state == "STALE" and s.target_id is not None
        }
    except ProjectError as exc:
        _err.print(f"[red]error[/red]: {exc} ({exc.code})")
        raise typer.Exit(2) from exc
    rendered = to_dot(lattice, stale) if fmt == "dot" else to_mermaid(lattice, stale)
    _out.print(rendered, end="")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    """Console-script entry point."""
    app()
