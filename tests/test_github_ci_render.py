"""Tests for deterministic managed GitHub Actions workflow rendering."""

import re

import pytest
from ruamel.yaml import YAML

from doc_lattice.github_ci.render import (
    BOOTSTRAP_PATH,
    CHECKOUT_REF,
    LINEAR_WORKFLOW_PATH,
    OFFLINE_WORKFLOW_PATH,
    SETUP_UV_REF,
    render_workflows,
)


def _load_workflow(text):
    """Parse one rendered workflow as safe YAML."""
    return YAML(typ="safe").load(text)


def test_render_workflows_returns_only_canonical_workflow_artifacts():
    artifacts = render_workflows("Guardantix/doc-lattice", "2.1.0")

    assert [(artifact.role, artifact.relative_path) for artifact in artifacts] == [
        ("offline", OFFLINE_WORKFLOW_PATH),
        ("linear", LINEAR_WORKFLOW_PATH),
    ]
    assert BOOTSTRAP_PATH not in {artifact.relative_path for artifact in artifacts}


def test_render_offline_workflow_runs_all_gates_without_secrets():
    offline = render_workflows("Guardantix/doc-lattice", "2.1.0")[0]
    workflow = _load_workflow(offline.text)

    assert workflow["on"] == {
        "push": {"branches": ["main"]},
        "pull_request": {"branches": ["main"]},
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert "LINEAR_API_KEY" not in offline.text
    assert "${{ secrets." not in offline.text
    assert "pull_request_target" not in offline.text
    assert "reconcile" not in offline.text

    run = workflow["jobs"]["check"]["steps"][-1]["run"]
    assert "doc-lattice ci audit" in run
    assert "doc-lattice check" in run
    assert "doc-lattice lint" in run
    assert "rc_audit=$?" in run
    assert "rc_check=$?" in run
    assert "rc_lint=$?" in run
    assert run.splitlines()[-1] == (
        '[ "$rc_audit" -eq 0 ] && [ "$rc_check" -eq 0 ] && [ "$rc_lint" -eq 0 ]'
    )


def test_render_linear_workflow_installs_before_mapping_secret():
    linear = render_workflows("Guardantix/doc-lattice", "2.1.0")[1]
    workflow = _load_workflow(linear.text)

    assert workflow["on"] == {
        "push": {"branches": ["main"]},
        "workflow_dispatch": None,
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert "env" not in workflow

    job = workflow["jobs"]["linear"]
    assert job["environment"] == "doc-lattice-linear"
    assert "env" not in job
    assert job["if"] == (
        "github.repository == 'Guardantix/doc-lattice' && github.ref == 'refs/heads/main' "
        "&& (github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
    )

    steps = job["steps"]
    assert all("env" not in step for step in steps[:-1])
    for step in steps[:-1]:
        for field in ("env", "with", "run"):
            assert "${{ secrets." not in str(step.get(field, ""))
    assert linear.text.count("${{ secrets.") == 1
    assert steps[-1]["env"] == {"LINEAR_API_KEY": "${{ secrets.DOC_LATTICE_LINEAR_API_KEY }}"}
    assert steps[-1]["run"] == (
        '"$RUNNER_TEMP/doc-lattice-venv/bin/doc-lattice" linear --exit-code'
    )

    install = steps[-2]["run"]
    assert "uv python install 3.13" in install
    assert 'uv venv --python 3.13 "$RUNNER_TEMP/doc-lattice-venv"' in install
    assert "uv pip install" in install
    assert "doc-lattice==2.1.0" in install


def test_action_refs_are_approved_full_commit_shas():
    assert CHECKOUT_REF == "34e114876b0b11c390a56381ad16ebd13914f8d5"  # pragma: allowlist secret
    assert SETUP_UV_REF == "d0cc045d04ccac9d8b7881df0226f9e82c39688e"  # pragma: allowlist secret
    assert re.fullmatch(r"[0-9a-f]{40}", CHECKOUT_REF) is not None
    assert re.fullmatch(r"[0-9a-f]{40}", SETUP_UV_REF) is not None


def test_rendered_workflows_pin_actions_and_mark_ownership():
    artifacts = render_workflows("Guardantix/doc-lattice", "2.1.0")

    for artifact in artifacts:
        workflow = _load_workflow(artifact.text)
        steps = next(iter(workflow["jobs"].values()))["steps"]

        assert steps[0]["uses"] == f"actions/checkout@{CHECKOUT_REF}"
        assert steps[0]["with"] == {"persist-credentials": False}
        assert steps[1]["uses"] == f"astral-sh/setup-uv@{SETUP_UV_REF}"
        assert steps[1]["with"] == {"enable-cache": False}
        assert f"actions/checkout@{CHECKOUT_REF} # v4.3.1" in artifact.text
        assert f"astral-sh/setup-uv@{SETUP_UV_REF} # v6.8.0" in artifact.text
        assert "actions/cache" not in artifact.text
        assert "doc-lattice==2.1.0" in artifact.text
        assert artifact.text.splitlines()[:4] == [
            "# doc-lattice-managed: github-ci-v1",
            f"# doc-lattice-artifact: {artifact.role}",
            "# doc-lattice-version: 2.1.0",
            "# doc-lattice-repository: Guardantix/doc-lattice",
        ]


def test_render_workflows_is_byte_deterministic():
    first = render_workflows("Guardantix/doc-lattice", "2.1.0")
    second = render_workflows("Guardantix/doc-lattice", "2.1.0")

    assert first == second


@pytest.mark.parametrize(
    "repository",
    [
        "a/__VERSION__",
        "a/__CHECKOUT_REF__",
        "a/__SETUP_UV_REF__",
    ],
)
def test_render_workflows_preserves_token_like_repository_names(repository):
    offline, linear = render_workflows(repository, "2.1.0")
    offline_run = _load_workflow(offline.text)["jobs"]["check"]["steps"][-1]["run"]
    linear_condition = _load_workflow(linear.text)["jobs"]["linear"]["if"]

    assert (
        "uvx --python 3.13 --from doc-lattice==2.1.0 doc-lattice ci audit "
        f"--repository {repository}"
    ) in offline_run.splitlines()
    assert linear_condition == (
        f"github.repository == '{repository}' && github.ref == 'refs/heads/main' "
        "&& (github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
    )
    assert f"--repository {repository}\n" in offline.text
    assert f"github.repository == '{repository}' &&" in linear.text
