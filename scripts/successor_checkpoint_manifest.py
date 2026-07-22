"""Write the SHA-256 manifest for the successor evaluation predeclaration checkpoint.

The manifest freezes every checkpoint input under
``tests/fixtures/github_ci_successor_checkpoint/`` and never covers gate evidence (spec
S8). This script regenerates ``MANIFEST.sha256`` during checkpoint authoring; the frozen
file is then verified by the ``test_manifest_matches_checkpoint_inputs`` validator in
``tests/test_successor_checkpoint.py``. The walk and line format are imported from that test
module so the manifest and its validator can never disagree.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"


def main() -> int:
    """Write ``MANIFEST.sha256`` from the checkpoint input walk shared with the test."""
    if str(TESTS_DIR) not in sys.path:
        sys.path.insert(0, str(TESTS_DIR))
    from test_successor_checkpoint import (  # noqa: PLC0415  # ty: ignore[unresolved-import]
        CHECKPOINT,
        _manifest_lines,
    )

    manifest = CHECKPOINT / "MANIFEST.sha256"
    manifest.write_text("\n".join(_manifest_lines()) + "\n", encoding="utf-8")
    print(f"wrote {manifest.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
