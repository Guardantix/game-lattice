"""Tests for the successor helper's manifest-derived build identity."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.check_helper_digest import compute_digest, covered_paths

REPO = Path(__file__).resolve().parents[1]
CHECKPOINT_MANIFEST = Path(
    "tests/fixtures/github_ci_successor_checkpoint/protocol/digest_manifest.json"
)
HELPER = Path("helper/doc-lattice-shell-parser")


def _copy_digest_inputs(destination: Path) -> None:
    """Copy the frozen manifest and its current input set into a temporary repository."""
    manifest_target = destination / CHECKPOINT_MANIFEST
    manifest_target.parent.mkdir(parents=True)
    shutil.copy2(REPO / CHECKPOINT_MANIFEST, manifest_target)
    for relative in covered_paths(REPO):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, target)


def test_digest_manifest_covers_all_non_test_go_sources() -> None:
    """Every non-test Go source under the helper module is a digest input."""
    covered = set(covered_paths(REPO))
    helper_root = REPO / HELPER
    expected = {
        path.relative_to(REPO)
        for path in helper_root.rglob("*.go")
        if not path.name.endswith("_test.go")
    }

    assert expected <= covered


def test_digest_is_deterministic_and_matches_pair_encoding() -> None:
    """The digest uses sorted path-NUL-file-hash pairs without a trailing newline."""
    paths = covered_paths(REPO)
    payload = "\n".join(
        f"{path.as_posix()}\0{hashlib.sha256((REPO / path).read_bytes()).hexdigest()}"
        for path in paths
    ).encode()

    expected = hashlib.sha256(payload).hexdigest()
    assert compute_digest(REPO) == expected
    assert compute_digest(REPO) == expected


def test_digest_changes_when_a_covered_file_changes(tmp_path: Path) -> None:
    """Changing one covered helper source changes the semantic digest."""
    _copy_digest_inputs(tmp_path)
    before = compute_digest(tmp_path)
    changed = tmp_path / HELPER / "wire.go"
    changed.write_bytes(changed.read_bytes() + b"\n")

    assert compute_digest(tmp_path) != before


def test_cli_rejects_an_uncovered_non_test_go_source(tmp_path: Path) -> None:
    """The CLI fails before printing a digest when manifest coverage is incomplete."""
    _copy_digest_inputs(tmp_path)
    manifest_path = tmp_path / CHECKPOINT_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["include"] = [
        "helper/doc-lattice-shell-parser/main.go",
        "tests/fixtures/github_ci_successor_checkpoint/protocol/schema.json",
        "tests/fixtures/github_ci_successor_checkpoint/protocol/encoder.json",
        "tests/fixtures/github_ci_successor_checkpoint/tables/",
        "tests/fixtures/github_ci_successor_checkpoint/limits.json",
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [
            sys.executable,
            str(REPO / "scripts/check_helper_digest.py"),
            "--repo-root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "helper/doc-lattice-shell-parser/wire.go" in result.stderr


def test_build_wrapper_injects_computed_digest(tmp_path: Path) -> None:
    """A real wrapper-built helper reports the exact manifest digest."""
    binary = tmp_path / "shell-parser"
    environment = os.environ.copy()
    environment.update(
        {
            "GOCACHE": str(tmp_path / "gocache"),
            "GOTOOLCHAIN": "local",
            "GOWORK": "off",
        }
    )
    build = subprocess.run(  # noqa: S603 - fixed repository build wrapper
        [str(REPO / "scripts/build_successor_helper.sh"), str(binary)],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO,
        env=environment,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    request = b'{"protocol_version":1,"sources":[{"id":0,"source":"true"}]}'
    completed = subprocess.run(  # noqa: S603 - pytest-owned binary path
        [str(binary)],
        input=request,
        check=False,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    response = json.loads(completed.stdout)
    assert response["helper_version"] == compute_digest(REPO)
    assert response["parser_version"] == "mvdan.cc/sh/v3@v3.13.1"
