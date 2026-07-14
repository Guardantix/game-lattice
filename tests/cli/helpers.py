"""Shared fixtures and helpers for CLI integration tests."""

import os
import stat
from hashlib import sha256
from pathlib import Path

from typer.testing import CliRunner

from doc_lattice.cli import app
from doc_lattice.constants import RECONCILE_JOURNAL_NAME, RECONCILE_JOURNAL_VERSION
from doc_lattice.reconcile_transaction import Journal, JournalEntry, JournalState
from doc_lattice.tickets import Ticket, TicketState

runner = CliRunner()


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes]]:
    """Capture every namespace entry without following symlinks or reading special files."""
    snapshot: dict[str, tuple[str, bytes]] = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            entry = ("symlink", os.fsencode(path.readlink()))
        elif stat.S_ISREG(mode):
            entry = ("file", path.read_bytes())
        elif stat.S_ISDIR(mode):
            entry = ("directory", b"")
        else:
            entry = ("special", b"")
        snapshot[path.relative_to(root).as_posix()] = entry
    return snapshot


def _write_cli_transaction(
    root: Path,
    destination: Path,
    before_bytes: bytes,
    after_bytes: bytes,
    *,
    state: JournalState = "prepared",
) -> tuple[Path, Path, Path]:
    """Write a valid single-entry recovery transaction for CLI integration tests."""
    before = destination.with_name(f".{destination.name}.doc-lattice-before.test.tmp")
    after = destination.with_name(f".{destination.name}.doc-lattice-after.test.tmp")
    journal = root / RECONCILE_JOURNAL_NAME
    before.write_bytes(before_bytes)
    after.write_bytes(after_bytes)
    entry = JournalEntry(
        destination=destination.relative_to(root).as_posix(),
        before_path=before.relative_to(root).as_posix(),
        before_sha256=sha256(before_bytes).hexdigest(),
        after_path=after.relative_to(root).as_posix(),
        after_sha256=sha256(after_bytes).hexdigest(),
    )
    journal.write_text(
        Journal(
            version=RECONCILE_JOURNAL_VERSION,
            state=state,
            entries=(entry,),
        ).model_dump_json(),
        encoding="utf-8",
    )
    return journal, before, after


def _run(args: list[str], cwd: Path, env: dict[str, str]):
    """Invoke the CLI with cwd and env set for the duration of the call, then restore cwd."""
    old = Path.cwd()
    os.chdir(cwd)
    try:
        return runner.invoke(app, args, env=env)
    finally:
        os.chdir(old)


def _chain_docs(tmp_path: Path) -> Path:
    # a <- b <- c: c derives from b, b derives from a.
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("---\nid: a\n---\n# A {#a}\nx\n", encoding="utf-8")
    (docs / "b.md").write_text(
        "---\nid: b\nderives_from:\n  - ref: a\n---\n# B {#b}\nx\n", encoding="utf-8"
    )
    (docs / "c.md").write_text(
        "---\nid: c\nderives_from:\n  - ref: b\n---\n# C {#c}\nx\n", encoding="utf-8"
    )
    return tmp_path


def _two_downstream_project(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "up.md").write_text("---\nid: up\n---\n# Up {#s}\nupstream body\n", encoding="utf-8")
    for name in ("down-a", "down-b"):
        (docs / f"{name}.md").write_text(
            f"---\nid: {name}\nderives_from:\n  - ref: up#s\n---\n# {name}\nbody\n",
            encoding="utf-8",
        )
    return tmp_path


def _clean_docs(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "up.md").write_text("---\nid: up\n---\n# Up {#sec}\nsec body\n", encoding="utf-8")
    (docs / "down.md").write_text(
        "---\nid: down\nderives_from:\n  - ref: up#sec\n---\n# Down\nbody\n",
        encoding="utf-8",
    )


def _fake_fetch(tickets):
    def fetch(_identifiers, _team, _client=None):
        return tickets, {}

    return fetch


def _ticket(state: TicketState) -> Ticket:
    return Ticket(
        identifier="PC-228",
        title="t",
        url="https://x/PC-228",
        state=state,
        parent=None,
        children=(),
    )


def _write_lint_docs(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir()
    # "down" is binding but derives from "up" (derived): a ladder inversion.
    (docs / "up.md").write_text(
        "---\nid: up\nauthority: derived\n---\n# Up\nbody\n", encoding="utf-8"
    )
    (docs / "down.md").write_text(
        "---\nid: down\nauthority: binding\nderives_from:\n  - ref: up\n---\n# Down\nbody\n",
        encoding="utf-8",
    )
