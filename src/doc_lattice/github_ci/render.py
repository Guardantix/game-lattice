"""Deterministic rendering for managed GitHub Actions artifacts."""

import re
from pathlib import PurePosixPath

from .identity import parse_repository, validate_final_release_version
from .model import ArtifactRole, ManagedArtifact

OFFLINE_WORKFLOW_PATH = PurePosixPath(".github/workflows/doc-lattice.yml")
LINEAR_WORKFLOW_PATH = PurePosixPath(".github/workflows/doc-lattice-linear.yml")
BOOTSTRAP_PATH = PurePosixPath(".github/doc-lattice-bootstrap.sh")

CHECKOUT_REF = "34e114876b0b11c390a56381ad16ebd13914f8d5"  # pragma: allowlist secret
SETUP_UV_REF = "d0cc045d04ccac9d8b7881df0226f9e82c39688e"  # pragma: allowlist secret

_TOKEN_RE = re.compile(r"__(?:REPOSITORY|VERSION|CHECKOUT_REF|SETUP_UV_REF)__")

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

_BOOTSTRAP_TEMPLATE = """set -u
EXPECTED_REPOSITORY='__REPOSITORY__'
ENVIRONMENT='doc-lattice-linear'
EXIT_FINDING=1
EXIT_TOOL_ERROR=2

die() { printf 'error: %s\n' "$1" >&2; exit "$EXIT_TOOL_ERROR"; }
lower_ascii() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
api() { gh api --hostname github.com "$@"; }
confirm_repository() {
  [ -t 0 ] || die "apply requires an interactive TTY on stdin"
  printf 'Type %s to apply: ' "$CANONICAL_REPOSITORY" >&2
  IFS= read -r answer || die "confirmation ended before a repository was entered"
  [ "$answer" = "$CANONICAL_REPOSITORY" ] || die "repository confirmation did not match"
}

sort_lines() {
  if [ -n "$1" ]; then
    printf '%s\n' "$1" | LC_ALL=C sort
  else
    printf ''
  fi
}

contains_line() {
  [ -n "$1" ] || return 1
  while IFS= read -r candidate; do
    [ "$candidate" = "$2" ] && return 0
  done <<EOF
$1
EOF
  return 1
}

fingerprint_value() { printf '%s:%s' "${#1}" "$1"; }

load_repository() {
  repository_fields=$(api "repos/$REQUESTED_REPOSITORY" --jq \
    '[.full_name, .default_branch, .visibility, .owner.type] | @tsv') || \
    die "repository metadata inspection failed"
  IFS="$(printf '\t')" read -r CANONICAL_REPOSITORY DEFAULT_BRANCH VISIBILITY OWNER_TYPE <<EOF
$repository_fields
EOF
  [ -n "$CANONICAL_REPOSITORY" ] && [ -n "$DEFAULT_BRANCH" ] && \
    [ -n "$VISIBILITY" ] && [ -n "$OWNER_TYPE" ] || \
    die "repository metadata was incomplete"
  printf 'canonical repository: %s\n' "$CANONICAL_REPOSITORY"
  [ "$CANONICAL_REPOSITORY" = "$EXPECTED_REPOSITORY" ] || \
    die "canonical repository identity does not match embedded repository; "\
"run a fresh plan then apply"
  [ "$DEFAULT_BRANCH" = "main" ] || die "default branch must be exactly main"
  OWNER=${CANONICAL_REPOSITORY%%/*}
  REPOSITORY=${CANONICAL_REPOSITORY#*/}
}

check_eligibility() {
  PLAN_NAME=""
  case "$VISIBILITY:$OWNER_TYPE" in
    public:*)
      ELIGIBILITY="public repository"
      ;;
    internal:User)
      die "user-owned internal repositories are not eligible"
      ;;
    private:User)
      PLAN_NAME=$(api "users/$OWNER" --jq '.plan.name') || \
        die "personal plan metadata is unavailable; eligibility is unverified"
      [ "$PLAN_NAME" = "pro" ] || \
        die "personal private repositories require the pro plan"
      ELIGIBILITY="personal pro plan"
      ;;
    private:Organization|internal:Organization)
      PLAN_NAME=$(api "orgs/$OWNER" --jq '.plan.name') || \
        die "organization plan metadata is unavailable; eligibility is unverified"
      case "$PLAN_NAME" in
        team|enterprise|business|business_plus)
          ELIGIBILITY="organization $PLAN_NAME plan"
          ;;
        *)
          die "organization plan is not recognized as eligible"
          ;;
      esac
      ;;
    *)
      die "repository visibility or owner type is not recognized as eligible"
      ;;
  esac
  printf 'eligibility: %s\n' "$ELIGIBILITY"
}

load_state() {
  REPOSITORY_SECRET_NAMES=$(api \
    "repos/$OWNER/$REPOSITORY/actions/secrets" --paginate --jq '.secrets[].name') || \
    die "repository secret-name metadata inspection failed; state is unreliable"
  REPOSITORY_SECRET_NAMES=$(sort_lines "$REPOSITORY_SECRET_NAMES")

  ENVIRONMENT_NAMES=$(api "repos/$OWNER/$REPOSITORY/environments" --paginate \
    --jq '.environments[].name') || \
    die "environment metadata inspection failed; state is unreliable"
  ENVIRONMENT_NAMES=$(sort_lines "$ENVIRONMENT_NAMES")

  ENVIRONMENT_EXISTS=0
  CUSTOM_BRANCH_POLICIES=""
  PROTECTED_BRANCHES=""
  POLICY_ROWS=""
  ENVIRONMENT_SECRET_NAMES=""
  if contains_line "$ENVIRONMENT_NAMES" "$ENVIRONMENT"; then
    ENVIRONMENT_EXISTS=1
    environment_fields=$(api "repos/$OWNER/$REPOSITORY/environments/$ENVIRONMENT" --jq \
      '[.deployment_branch_policy.custom_branch_policies, \
.deployment_branch_policy.protected_branches] | @tsv') || \
      die "target environment policy inspection failed; state is unreliable"
    IFS="$(printf '\t')" read -r CUSTOM_BRANCH_POLICIES PROTECTED_BRANCHES <<EOF
$environment_fields
EOF
    POLICY_ROWS=$(api \
      "repos/$OWNER/$REPOSITORY/environments/$ENVIRONMENT/deployment-branch-policies" \
      --paginate --jq '.branch_policies[] | [.name, .type] | @tsv') || \
      die "deployment branch-policy inspection failed; state is unreliable"
    POLICY_ROWS=$(sort_lines "$POLICY_ROWS")
    ENVIRONMENT_SECRET_NAMES=$(api \
      "repos/$OWNER/$REPOSITORY/environments/$ENVIRONMENT/secrets" \
      --paginate --jq '.secrets[].name') || \
      die "environment secret-name metadata inspection failed; state is unreliable"
    ENVIRONMENT_SECRET_NAMES=$(sort_lines "$ENVIRONMENT_SECRET_NAMES")
  fi

  ENVIRONMENT_SECRET_PRESENT=0
  LEGACY_REPO_SECRET_PRESENT=0
  DEDICATED_REPO_SECRET_PRESENT=0
  contains_line "$ENVIRONMENT_SECRET_NAMES" "DOC_LATTICE_LINEAR_API_KEY" && \
    ENVIRONMENT_SECRET_PRESENT=1
  contains_line "$REPOSITORY_SECRET_NAMES" "LINEAR_API_KEY" && \
    LEGACY_REPO_SECRET_PRESENT=1
  contains_line "$REPOSITORY_SECRET_NAMES" "DOC_LATTICE_LINEAR_API_KEY" && \
    DEDICATED_REPO_SECRET_PRESENT=1

  POLICY_EXACT=0
  SAFE_INCOMPLETE=0
  if [ "$CUSTOM_BRANCH_POLICIES" = "true" ] && [ "$PROTECTED_BRANCHES" = "false" ]; then
    if [ "$POLICY_ROWS" = "$(printf 'main\tbranch')" ]; then
      POLICY_EXACT=1
    elif [ -z "$POLICY_ROWS" ] && [ "$ENVIRONMENT_SECRET_PRESENT" -eq 0 ]; then
      SAFE_INCOMPLETE=1
    fi
  fi

  STATE_FINGERPRINT=$(fingerprint_value "$CANONICAL_REPOSITORY"
    fingerprint_value "$DEFAULT_BRANCH"
    fingerprint_value "$VISIBILITY"
    fingerprint_value "$OWNER_TYPE"
    fingerprint_value "$PLAN_NAME"
    fingerprint_value "$ELIGIBILITY"
    fingerprint_value "$REPOSITORY_SECRET_NAMES"
    fingerprint_value "$ENVIRONMENT_NAMES"
    fingerprint_value "$ENVIRONMENT_EXISTS"
    fingerprint_value "$CUSTOM_BRANCH_POLICIES"
    fingerprint_value "$PROTECTED_BRANCHES"
    fingerprint_value "$POLICY_ROWS"
    fingerprint_value "$ENVIRONMENT_SECRET_NAMES")
}

print_state() {
  printf 'target: %s environment %s\n' "$CANONICAL_REPOSITORY" "$ENVIRONMENT"
  printf 'eligibility result: %s\n' "$ELIGIBILITY"
  if [ "$POLICY_EXACT" -eq 1 ]; then
    printf 'policy: exact\n'
  elif [ "$ENVIRONMENT_EXISTS" -eq 0 ]; then
    printf 'policy: absent\n'
  elif [ "$SAFE_INCOMPLETE" -eq 1 ]; then
    printf 'policy: safe-incomplete\n'
  else
    printf 'policy: mismatch\n'
  fi
  if [ "$ENVIRONMENT_SECRET_PRESENT" -eq 1 ]; then
    printf 'environment secret DOC_LATTICE_LINEAR_API_KEY: present by name metadata\n'
  else
    printf 'environment secret DOC_LATTICE_LINEAR_API_KEY: absent by name metadata\n'
  fi
  if [ "$LEGACY_REPO_SECRET_PRESENT" -eq 1 ]; then
    printf 'repository secret LINEAR_API_KEY: present by name metadata\n'
  else
    printf 'repository secret LINEAR_API_KEY: absent by name metadata\n'
  fi
  if [ "$DEDICATED_REPO_SECRET_PRESENT" -eq 1 ]; then
    printf 'repository secret DOC_LATTICE_LINEAR_API_KEY: present by name metadata\n'
  else
    printf 'repository secret DOC_LATTICE_LINEAR_API_KEY: absent by name metadata\n'
  fi
  printf '%s\n' \
    'note: organization-secret visibility may require confirmation by the organization owner'
}

observable_status() {
  [ "$POLICY_EXACT" -eq 1 ] && \
    [ "$ENVIRONMENT_SECRET_PRESENT" -eq 1 ] && \
    [ "$LEGACY_REPO_SECRET_PRESENT" -eq 0 ] && \
    [ "$DEDICATED_REPO_SECRET_PRESENT" -eq 0 ]
}

create_main_policy() {
  api --method POST \
    "repos/$OWNER/$REPOSITORY/environments/$ENVIRONMENT/deployment-branch-policies" \
    --field 'name=main' --field 'type=branch' >/dev/null
}

apply_policy() {
  mutated=0
  if [ "$POLICY_EXACT" -eq 1 ]; then
    :
  elif [ "$ENVIRONMENT_EXISTS" -eq 0 ]; then
    api --method PUT "repos/$OWNER/$REPOSITORY/environments/$ENVIRONMENT" \
      --field 'deployment_branch_policy[protected_branches]=false' \
      --field 'deployment_branch_policy[custom_branch_policies]=true' >/dev/null || \
      die "environment PUT did not complete observably; "\
"no branch-policy POST was attempted; rerun plan then apply"
    create_main_policy || \
      die "environment custom policy mode was created; "\
"main branch-policy POST did not complete observably; rerun plan then apply"
    mutated=1
  elif [ "$SAFE_INCOMPLETE" -eq 1 ]; then
    create_main_policy || \
      die "environment custom policy mode remains present with no reviewed policy; "\
"main branch-policy POST did not complete observably; rerun plan then apply"
    mutated=1
  else
    die "existing environment policy is ambiguous; refusing to narrow or take ownership"
  fi

  if [ "$mutated" -eq 1 ]; then
    load_state
    [ "$POLICY_EXACT" -eq 1 ] || \
      die "environment mutation did not read back as exact; rerun plan then apply"
  fi
  printf '%s\n' 'environment policy verified'
  if [ "$ENVIRONMENT_SECRET_PRESENT" -eq 0 ]; then
    printf '%s%s\n' \
      'gh secret set DOC_LATTICE_LINEAR_API_KEY --env doc-lattice-linear ' \
      '--repo "$CANONICAL_REPOSITORY"'
  fi
  if [ "$LEGACY_REPO_SECRET_PRESENT" -eq 1 ]; then
    printf '%s\n' 'gh secret delete LINEAR_API_KEY --repo "$CANONICAL_REPOSITORY"'
  fi
  if [ "$DEDICATED_REPO_SECRET_PRESENT" -eq 1 ]; then
    printf '%s\n' \
      'gh secret delete DOC_LATTICE_LINEAR_API_KEY --repo "$CANONICAL_REPOSITORY"'
  fi
}

[ "$#" -eq 2 ] || die "usage: $0 plan|apply|verify OWNER/REPO"
OPERATION=$1
REQUESTED_REPOSITORY=$2
case "$OPERATION" in
  plan|apply|verify) ;;
  *) die "operation must be exactly plan, apply, or verify" ;;
esac
[ "$(lower_ascii "$REQUESTED_REPOSITORY")" = "$(lower_ascii "$EXPECTED_REPOSITORY")" ] || \
  die "requested repository does not match embedded repository"
command -v gh >/dev/null 2>&1 || die "gh is required on PATH"
gh auth status --hostname github.com >/dev/null 2>&1 || \
  die "gh authentication for github.com is required"

load_repository
check_eligibility
load_state
print_state

case "$OPERATION" in
  plan)
    observable_status
    exit $?
    ;;
  verify)
    printf '%s%s\n' \
      'reminder: run local doc-lattice ci audit; remote verification cannot prove ' \
      'legacy workflow removal'
    observable_status
    exit $?
    ;;
  apply)
    INITIAL_CANONICAL_REPOSITORY=$CANONICAL_REPOSITORY
    INITIAL_STATE_FINGERPRINT=$STATE_FINGERPRINT
    confirm_repository
    load_repository
    check_eligibility
    load_state
    [ "$CANONICAL_REPOSITORY" = "$INITIAL_CANONICAL_REPOSITORY" ] && \
      [ "$STATE_FINGERPRINT" = "$INITIAL_STATE_FINGERPRINT" ] || \
      die "repository state changed during confirmation; run a fresh plan then apply"
    apply_policy
    observable_status
    exit $?
    ;;
esac
"""


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


def render_bootstrap(repository: str, version: str) -> ManagedArtifact:
    """Render the human-run GitHub environment bootstrap script.

    Args:
        repository: GitHub repository in ``OWNER/REPO`` form.
        version: Exact final-release version recorded in the ownership header.

    Returns:
        The Bash 3.2 bootstrap artifact.

    Raises:
        ConfigError: If the repository or version is invalid.
    """
    identity = parse_repository(repository)
    validate_final_release_version(version)
    text = (
        "#!/usr/bin/env bash\n"
        + ownership_header("bootstrap", identity.display, version)
        + _replace_tokens(_BOOTSTRAP_TEMPLATE, identity.display, version)
    )
    return ManagedArtifact("bootstrap", BOOTSTRAP_PATH, text)


def render_managed_artifacts(
    repository: str,
    version: str,
) -> tuple[ManagedArtifact, ManagedArtifact, ManagedArtifact]:
    """Render every managed GitHub CI artifact in canonical order.

    Args:
        repository: GitHub repository in ``OWNER/REPO`` form.
        version: Exact final-release version for the managed artifacts.

    Returns:
        The offline workflow, Linear workflow, and human-run bootstrap script.

    Raises:
        ConfigError: If the repository or version is invalid.
    """
    offline, linear = render_workflows(repository, version)
    return offline, linear, render_bootstrap(repository, version)


def _replace_tokens(template: str, repository: str, version: str) -> str:
    """Replace the fixed renderer tokens without interpreting literal braces."""
    replacements = {
        "__REPOSITORY__": repository,
        "__VERSION__": version,
        "__CHECKOUT_REF__": CHECKOUT_REF,
        "__SETUP_UV_REF__": SETUP_UV_REF,
    }
    return _TOKEN_RE.sub(lambda match: replacements[match.group(0)], template)
