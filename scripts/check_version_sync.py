#!/usr/bin/env python3
"""Verify __version__, pyproject.toml, and CHANGELOG.md declare the same version."""

import sys
from pathlib import Path

from game_lattice import __version__
from game_lattice.version_check import check_version_consistency

_REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    """Read the three version sources and exit non-zero on any disagreement."""
    pyproject_text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    changelog_text = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    messages = check_version_consistency(__version__, pyproject_text, changelog_text)
    for message in messages:
        print(message, file=sys.stderr)
    sys.exit(1 if messages else 0)


if __name__ == "__main__":
    main()
