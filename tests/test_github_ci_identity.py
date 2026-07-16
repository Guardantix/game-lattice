"""Tests for GitHub repository identity and generator-version validation."""

import pytest

from doc_lattice.error_types import ConfigError
from doc_lattice.github_ci.identity import (
    parse_origin_repository,
    parse_repository,
    validate_final_release_version,
)


@pytest.mark.parametrize(
    "value",
    [
        "Guardantix/doc-lattice",
        "guardantix/DOC-LATTICE",
        "a/a",
        "owner/repo.name_with-punctuation",
    ],
)
def test_parse_repository_accepts_ascii_github_identity(value):
    identity = parse_repository(value)

    assert identity.display == value
    assert identity.comparison_key == value.lower()


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:Guardantix/doc-lattice.git",
        "git@GITHUB.COM:Guardantix/doc-lattice",
        "ssh://git@github.com/Guardantix/doc-lattice.git",
        "https://github.com/Guardantix/doc-lattice",
        "https://GITHUB.COM/Guardantix/doc-lattice.git",
    ],
)
def test_parse_origin_repository_accepts_supported_github_urls(url):
    identity = parse_origin_repository(url)

    assert identity.display == "Guardantix/doc-lattice"
    assert identity.comparison_key == "guardantix/doc-lattice"


@pytest.mark.parametrize(
    "value",
    [
        "owner",
        "owner/repo/extra",
        "owner/repo?ref=main",
        "owner/repo#fragment",
        "owner/repo name",
        "owner/repo\nname",
        "-owner/repo",
        "owner-/repo",
    ],
)
def test_parse_repository_rejects_invalid_identity(value):
    with pytest.raises(ConfigError):
        parse_repository(value)


@pytest.mark.parametrize(
    "url",
    [
        "git@gitlab.com:Guardantix/doc-lattice.git",
        "git://github.com/Guardantix/doc-lattice.git",
        "http://github.com/Guardantix/doc-lattice.git",
        "ssh://root@github.com/Guardantix/doc-lattice.git",
        "https://user@github.com/Guardantix/doc-lattice.git",
        "https://github.com/Guardantix/doc-lattice/extra",
        "https://github.com/Guardantix/doc-lattice.git?ref=main",
        "https://github.com/Guardantix/doc-lattice.git#fragment",
    ],
)
def test_parse_origin_repository_rejects_unsupported_urls(url):
    with pytest.raises(ConfigError):
        parse_origin_repository(url)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.1.0", (0, 1, 0)),
        ("2.0.0", (2, 0, 0)),
        ("10.24.301", (10, 24, 301)),
    ],
)
def test_validate_final_release_version_accepts_three_numeric_components(version, expected):
    assert validate_final_release_version(version) == expected


@pytest.mark.parametrize(
    "version",
    ["2.0", "2.0.0.dev1", "2.1.0rc1", "2.0.0+local", "v2.0.0", "latest"],
)
def test_validate_final_release_version_rejects_non_final_versions(version):
    with pytest.raises(ConfigError, match="final release version"):
        validate_final_release_version(version)
