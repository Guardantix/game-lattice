"""Shared test fixtures."""

import os
from pathlib import Path

import pytest

# Strip FORCE_COLOR before any source module is imported. cli.py builds module-level rich Consoles
# at import time, so a color-forcing dev shell (FORCE_COLOR set) would make them emit ANSI escapes
# that break contiguous-substring assertions on human output. CI runs without FORCE_COLOR; this
# just matches the CI environment. Runs at conftest import, ahead of test modules importing cli.py.
os.environ.pop("FORCE_COLOR", None)


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """Provide a clean working directory."""
    return tmp_path


@pytest.fixture
def lattice_dir(tmp_path: Path) -> Path:
    """Write a small synthetic lattice and return the project root.

    Layout under docs/:
      art-direction.md  -> sections {#accent} and {#motion}
      pc-design.md       -> derives_from accent (STALE) and motion (UNRECONCILED)
      gdd.md             -> derives_from a ghost ref (BROKEN)
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "art-direction.md").write_text(
        "---\nid: art-direction\nlayer: design\n---\n"
        "# Art Direction {#art-direction-top}\n\n"
        "## Accent {#accent}\naccent body v2\n\n"
        "## Motion {#motion}\nmotion body\n",
        encoding="utf-8",
    )
    (docs / "pc-design.md").write_text(
        "---\nid: pc-design\nlayer: design\n"
        "derives_from:\n"
        "  - ref: art-direction#accent\n    seen: staleseenhashstaleseenhashstale00\n"
        "  - ref: art-direction#motion\n"
        "tickets: [PC-228]\n---\n# PC Design\nbody\n",
        encoding="utf-8",
    )
    (docs / "gdd.md").write_text(
        "---\nid: gdd\nlayer: design\nderives_from:\n  - ref: ghost\n---\n# GDD\nbody\n",
        encoding="utf-8",
    )
    return tmp_path
