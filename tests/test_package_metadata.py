"""Tests for the distributable package metadata and source contents."""

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_sdist_has_an_explicit_minimal_include_set():
    sdist = _PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert sdist["include"] == [
        "/src",
        "/tests",
        "/LICENSE",
        "/README.md",
        "/pyproject.toml",
    ]


def test_pypi_metadata_links_to_maintainer_resources():
    assert _PYPROJECT["project"]["urls"] == {
        "Homepage": "https://github.com/Guardantix/doc-lattice",
        "Source": "https://github.com/Guardantix/doc-lattice",
        "Issues": "https://github.com/Guardantix/doc-lattice/issues",
        "Changelog": "https://github.com/Guardantix/doc-lattice/blob/main/CHANGELOG.md",
        "Releases": "https://github.com/Guardantix/doc-lattice/releases",
    }
