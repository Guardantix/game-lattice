"""Deterministic rendering for managed GitHub Actions artifacts."""

from pathlib import PurePosixPath

from .identity import parse_repository, validate_final_release_version
from .model import ArtifactRole, ManagedArtifact

OFFLINE_WORKFLOW_PATH = PurePosixPath(".github/workflows/doc-lattice.yml")
LINEAR_WORKFLOW_PATH = PurePosixPath(".github/workflows/doc-lattice-linear.yml")
BOOTSTRAP_PATH = PurePosixPath(".github/doc-lattice-bootstrap.sh")

CHECKOUT_REF = "34e114876b0b11c390a56381ad16ebd13914f8d5"  # pragma: allowlist secret
SETUP_UV_REF = "d0cc045d04ccac9d8b7881df0226f9e82c39688e"  # pragma: allowlist secret

_OFFLINE_TEMPLATE = (
    """name: doc-lattice
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  check:
    name: Offline doc-lattice gates
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@__CHECKOUT_REF__ # v4.3.1
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@__SETUP_UV_REF__ # v6.8.0
        with:
          enable-cache: false
      - name: Audit, check, and lint
        run: |
          set +e
          uvx --python 3.13 --from doc-lattice==__VERSION__ doc-lattice ci audit --repository """
    "__REPOSITORY__\n"
    """          rc_audit=$?
          uvx --python 3.13 --from doc-lattice==__VERSION__ doc-lattice check
          rc_check=$?
          uvx --python 3.13 --from doc-lattice==__VERSION__ doc-lattice lint
          rc_lint=$?
          [ "$rc_audit" -eq 0 ] && [ "$rc_check" -eq 0 ] && [ "$rc_lint" -eq 0 ]
"""
)

_LINEAR_TEMPLATE = (
    """name: doc-lattice Linear
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  linear:
    name: Trusted Linear gate
    if: >-
      github.repository == '__REPOSITORY__' &&
      github.ref == 'refs/heads/main' &&
      (github.event_name == 'push' || github.event_name == 'workflow_dispatch')
    environment: doc-lattice-linear
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@__CHECKOUT_REF__ # v4.3.1
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@__SETUP_UV_REF__ # v6.8.0
        with:
          enable-cache: false
      - name: Install pinned doc-lattice without the Linear secret
        run: |
          uv python install 3.13
          uv venv --python 3.13 "$RUNNER_TEMP/doc-lattice-venv"
          uv pip install --python "$RUNNER_TEMP/doc-lattice-venv/bin/python" doc-lattice=="""
    "__VERSION__\n"
    """      - name: Run trusted Linear gate
        env:
          LINEAR_API_KEY: ${{ secrets.DOC_LATTICE_LINEAR_API_KEY }}
        run: '"$RUNNER_TEMP/doc-lattice-venv/bin/doc-lattice" linear --exit-code'
"""
)


def ownership_header(role: ArtifactRole, repository: str, version: str) -> str:
    """Build the ownership header for one managed artifact.

    Args:
        role: Managed artifact role.
        repository: Validated repository display identity.
        version: Validated final-release version.

    Returns:
        The four-line ownership header with a final newline.
    """
    return (
        "# doc-lattice-managed: github-ci-v1\n"
        f"# doc-lattice-artifact: {role}\n"
        f"# doc-lattice-version: {version}\n"
        f"# doc-lattice-repository: {repository}\n"
    )


def render_workflows(repository: str, version: str) -> tuple[ManagedArtifact, ManagedArtifact]:
    """Render the offline and trusted Linear GitHub Actions workflows.

    Args:
        repository: GitHub repository in ``OWNER/REPO`` form.
        version: Exact final-release version to install in both workflows.

    Returns:
        The offline and Linear workflow artifacts in canonical order.

    Raises:
        ConfigError: If the repository or version is invalid.
    """
    identity = parse_repository(repository)
    validate_final_release_version(version)

    offline_text = ownership_header("offline", identity.display, version) + _replace_tokens(
        _OFFLINE_TEMPLATE,
        identity.display,
        version,
    )
    linear_text = ownership_header("linear", identity.display, version) + _replace_tokens(
        _LINEAR_TEMPLATE,
        identity.display,
        version,
    )
    return (
        ManagedArtifact("offline", OFFLINE_WORKFLOW_PATH, offline_text),
        ManagedArtifact("linear", LINEAR_WORKFLOW_PATH, linear_text),
    )


def _replace_tokens(template: str, repository: str, version: str) -> str:
    """Replace the fixed renderer tokens without interpreting literal braces."""
    return (
        template.replace("__REPOSITORY__", repository)
        .replace("__VERSION__", version)
        .replace("__CHECKOUT_REF__", CHECKOUT_REF)
        .replace("__SETUP_UV_REF__", SETUP_UV_REF)
    )
