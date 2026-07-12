"""Tests for the distributable package metadata and source contents."""

import subprocess
import tarfile
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


def test_built_sdist_contains_only_publishable_source_files(tmp_path):
    output_dir = tmp_path / "dist"
    subprocess.run(  # noqa: S603 - fixed build command and pytest-owned output path
        ["uv", "build", "--sdist", "--out-dir", str(output_dir)],  # noqa: S607
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    archives = sorted(output_dir.glob("*.tar.gz"))
    assert len(archives) == 1, f"expected one sdist, found: {archives}"

    with tarfile.open(archives[0], "r:gz") as archive:
        member_parts = [Path(member.name).parts for member in archive.getmembers()]

    top_levels = {parts[0] for parts in member_parts}
    assert len(top_levels) == 1, f"expected one sdist prefix, found: {sorted(top_levels)}"
    paths = {Path(*parts[1:]).as_posix() for parts in member_parts if len(parts) > 1}

    expected_root_files = {".gitignore", "LICENSE", "PKG-INFO", "README.md", "pyproject.toml"}
    root_files = {path for path in paths if "/" not in path and path not in {"src", "tests"}}
    assert root_files == expected_root_files, (
        f"unexpected root files: {sorted(root_files - expected_root_files)}; "
        f"missing root files: {sorted(expected_root_files - root_files)}"
    )

    unexpected_paths = sorted(
        path
        for path in paths
        if path not in expected_root_files
        and path not in {"src", "tests"}
        and not path.startswith(("src/", "tests/"))
    )
    assert unexpected_paths == [], f"unexpected sdist members: {unexpected_paths}"


def test_pypi_metadata_links_to_maintainer_resources():
    assert _PYPROJECT["project"]["urls"] == {
        "Homepage": "https://github.com/Guardantix/doc-lattice",
        "Source": "https://github.com/Guardantix/doc-lattice",
        "Issues": "https://github.com/Guardantix/doc-lattice/issues",
        "Changelog": "https://github.com/Guardantix/doc-lattice/blob/main/CHANGELOG.md",
        "Releases": "https://github.com/Guardantix/doc-lattice/releases",
    }
