# GitHub Linear CI Bootstrap Design

**Date:** 2026-07-15
**Status:** Amended after review; awaiting re-approval

## Purpose

Make the safe GitHub Actions deployment of doc-lattice systematic without giving ordinary
`doc-lattice init` runs, pull-request workflows, or package code a GitHub administrator token.
The installation must prevent fork and other untrusted pull requests from receiving
`LINEAR_API_KEY`, must not install an automated mutating `reconcile`, and must remain reviewable by
the human maintainer who performs the one-time GitHub setup.

## Existing constraints

- `init` currently creates `.doc-lattice.yml` only when absent and prints offline pre-commit and CI
  snippets. Existing files are preserved.
- The generated CI currently runs only `check` and `lint`; it does not receive
  `LINEAR_API_KEY`.
- `linear` is the only product command that accesses the network, and `linear_client` is the only
  module that performs that request.
- `reconcile` is the only command that mutates tracked documents. `reconcile --dry-run` does not
  persist or recover anything.
- Repository workflows are repository-controlled input. Workflow-file conditions alone are not a
  sufficient secret boundary because a pull request can edit them.

## Goals

1. Generate a least-privilege offline PR workflow and a separately privileged Linear workflow.
2. Place the Linear credential behind a GitHub environment whose server-side deployment policy
   permits only the exact `main` branch.
3. Keep GitHub administration outside the Python application. A generated, secret-free `gh`
   bootstrap script is reviewed and run explicitly by a human maintainer.
4. Detect local workflow drift and common unsafe configurations with a read-only audit command.
5. Make local file creation and remote setup idempotent and fail closed on ambiguous existing
   state.
6. Preserve the current offline and create-only behavior unless the user explicitly selects the
   GitHub scaffolding option.
7. Refuse secret-bearing setup when the repository visibility and account plan do not support both
   environment secrets and deployment branch policies.

## Non-goals

- The installer will not accept, store, transmit, or validate the value of the Linear API key.
- The installer will not run `gh`, call GitHub APIs, or hold a GitHub credential itself.
- The installer will not create a CI workflow that runs real `reconcile`.
- The audit command will not claim to prove arbitrary GitHub Actions workflows safe. It is drift
  detection, not the authorization boundary.
- The feature will not administer organization-wide Actions policies or rulesets. Those remain an
  optional organization-owner control.
- The feature will not automatically rewrite customized workflows or existing GitHub environments.
  An explicit local refresh flow may replace marked doc-lattice-generated artifacts only after
  showing a diff and receiving confirmation.
- The initial bootstrap supports GitHub.com only. GitHub Enterprise Server has version-dependent
  pull-request ref semantics and is not accepted without a separate compatibility design.

## Considered approaches

### Static instructions only

Keep `init` unchanged and document a safe workflow and GitHub settings. This has the smallest code
surface, but installation remains easy to perform incompletely and has no repeatable verification.

### Direct GitHub API administration

Let `init` use an administrator token to configure environments, policies, and secrets. This is
convenient but gives installed package and dependency code unnecessary administrative authority,
adds a second network client to the product, and introduces partial remote mutation and credential
handling into normal CLI behavior.

### Reviewed two-stage bootstrap

Generate local workflow files and a secret-free `gh` script. The maintainer reviews the generated
files, explicitly runs the script using existing `gh` authentication, and sets the secret directly
through `gh`. This provides repeatability without exposing administrative credentials or the
Linear key to doc-lattice. This is the selected approach.

## Security boundary

The authoritative control is the GitHub environment, not a workflow `if` expression.

That control is available in public repositories on current GitHub plans. Private and internal
repositories require GitHub Pro, GitHub Team, or GitHub Enterprise for environment secrets and
deployment branch policies. GitHub Free private repositories are unsupported because GitHub ignores
their environment secrets and protection rules. Bootstrap `plan` must establish repository
visibility and an eligible owner plan before any mutation. If the API does not expose enough plan
or capability information to prove eligibility, bootstrap fails closed with a manual remediation
message; it does not assume that an environment created through the API is protected. Post-apply
read-back independently verifies that the branch policy exists before the secret-setting command is
shown.

The bootstrap creates an environment named `doc-lattice-linear` with selected deployment branches
and tags enabled. Its complete allow list is one branch rule for `main`; it has no tag rules and no
pull-request ref rule such as `refs/pull/*/merge`. GitHub evaluates this policy against the workflow
run's `GITHUB_REF` before the job starts and before environment secrets become available.

The Linear credential is stored under the environment-only name
`DOC_LATTICE_LINEAR_API_KEY`. The workflow maps it to the process variable expected by the client
only on the command step:

```yaml
env:
  LINEAR_API_KEY: ${{ secrets.DOC_LATTICE_LINEAR_API_KEY }}
```

The setup instructions forbid repository- or organization-scoped copies of this credential. The
bootstrap can verify repository secret metadata when its authenticated identity has permission to
list it. Because repository administration cannot always enumerate organization secrets, the
instructions also require the maintainer to confirm that the organization does not expose a secret
of the same name to the repository. The dedicated environment secret name avoids falling back to a
broader `LINEAR_API_KEY`; server-side environment scoping remains the control.

This protects same-repository and fork pull requests even if they edit the workflow:

- Adding a `pull_request` trigger or removing the job `if` still leaves a PR `GITHUB_REF` that the
  environment rejects.
- Removing the job's `environment` binding removes access to the environment-only secret.
- Fork pull requests additionally receive GitHub's normal fork secret restrictions.

This statement applies to `pull_request`, `pull_request_review`, and
`pull_request_review_comment` on current GitHub.com, where environment policies evaluate the
execution ref `refs/pull/N/merge`. It deliberately does not apply to `pull_request_target`. Since
December 8, 2025, GitHub.com gives `pull_request_target` the default branch as `GITHUB_REF`, so an
exact `main` environment rule would pass and the job could receive its environment secret while
handling untrusted pull-request input. The repository-global audit prohibition on
`pull_request_target`, trusted default-branch workflow review, and the generated workflow's exact
event allow list are therefore load-bearing controls.

Before that GitHub.com change, pull-request environment policy could be evaluated against the
user-controlled head branch. An attacker can choose even an exact branch name such as `main`, so
the initial bootstrap does not claim that an exact rule repairs those older semantics and does not
support GitHub Enterprise Server. Future support for another GitHub host or broader branch patterns
requires a separate compatibility and threat review.

The contract does not protect a malicious commit already admitted to trusted `main`. Branch
protection and review decide what becomes trusted. An optional required reviewer and disabled
administrator bypass can extend protection to each Linear run, at the cost of manual approval for
every run. These optional protections are enabled only when the repository visibility and plan
support them; they are not prerequisites for the exact-`main` environment boundary and are never
silently omitted after being requested.

## Generated artifacts

An explicit `doc-lattice init --github --repository OWNER/REPO` mode adds three create-only
artifacts while retaining the existing config behavior. The repository argument is required for
GitHub generation and is validated as one owner segment plus one repository segment; generation
does not infer it from a mutable local remote:

1. `.github/workflows/doc-lattice.yml` runs offline PR gates.
2. `.github/workflows/doc-lattice-linear.yml` runs the Linear gate on trusted `main` only.
3. A clearly named one-time bootstrap script configures and verifies the GitHub environment with
   `gh`. The script contains no secret value and warns the maintainer to review it and run it only
   from trusted project state.

Each artifact carries a machine-readable ownership marker and generator version. The marker means
that the explicit refresh operation may replace the file; removing it opts the file out of managed
replacement but does not exempt a canonical workflow path from audit invariants.

GitHub artifact generation and refresh require doc-lattice itself to have a final release version
such as `2.0.0`. A development, prerelease, or local version such as `2.0.1.dev0`, `2.1.0rc1`, or
`2.0.0+local` is rejected before file creation because the corresponding exact PyPI requirement is
not guaranteed to resolve. The tool does not guess the nearest release. Ordinary `init` remains
available from development builds because its existing printed guidance and config creation are
unchanged.

Before creating any missing artifact, `init --github` preflights the complete target set:

- An absent target is eligible for creation.
- An existing byte-identical generated artifact is accepted.
- Any differing existing artifact causes a tool error before doc-lattice creates another target and
  points to `doc-lattice ci refresh` for a managed upgrade.

After a successful preflight, missing files use the existing durable create-if-absent primitive.
A concurrent creator can still win between preflight and creation; that race reports a tool error
and preserves the winner's bytes. The operation does not need a destructive rollback because every
write is create-only and a safe rerun can accept exact artifacts.

Normal `doc-lattice init` retains its current output and write behavior. GitHub artifacts are
created only when `--github` is explicitly selected.

## Managed artifact upgrades

`doc-lattice ci refresh --repository OWNER/REPO` is the supported upgrade and repository-rename
path. The repository argument is always explicit, including when it is unchanged. Without
`--apply`, refresh is read-only: it validates all canonical targets, renders the new artifacts,
prints a unified diff, and exits `0` when current, `1` when an update is available, or `2` on an
unsafe or unreadable state.

`doc-lattice ci refresh --apply` repeats that preflight, prints the same diff, and requires
interactive confirmation before replacement. It replaces only canonical artifacts with a valid
doc-lattice ownership marker. An unmarked file, an unexpected path, or an ambiguous marker fails
closed and requires manual reconciliation; there is no general force-overwrite flag.

All targets are preflighted before mutation and each replacement is atomic. The files are tracked
and contain no secret, so a crash between replacements is a safe mixed-version state rather than a
reason for destructive rollback. A rerun recognizes current and prior marked artifacts, previews
the remaining changes, and completes the refresh. The maintainer reviews and commits the resulting
diff normally.

The audit reports a stale managed generator version as a finding and directs the operator to the
read-only refresh preview. A repository rename or transfer also requires refresh with the new
explicit `OWNER/REPO` value; until then, the generated job condition intentionally skips Linear.

## Offline pull-request workflow

The PR workflow:

- Triggers exactly on `pull_request` targeting `main` and `push` to `main`.
- Declares `permissions: contents: read` explicitly.
- Pins third-party actions to full commit SHAs with human-readable release comments.
- Uses `persist-credentials: false` for checkout.
- Does not enable dependency or Actions caching in the initial implementation.
- Runs the exact published doc-lattice version selected by the release that generated it.
- Runs `ci audit --repository OWNER/REPO`, `check`, and `lint`, capturing all three results so an
  earlier finding does not skip a later gate.
- Does not reference any Linear secret, run `linear`, use `pull_request_target`, or run real
  `reconcile`.
- Does not invoke `reconcile`, including dry-run, in the initial implementation. A future preview
  must use only `reconcile --dry-run` and requires a separate behavior change.

## Trusted Linear workflow

The Linear workflow triggers only on `push` to `main` and `workflow_dispatch`. Its job repeats the
trust decision as defense in depth:

```yaml
if: >-
  github.repository == 'OWNER/REPO' &&
  github.ref == 'refs/heads/main' &&
  (github.event_name == 'push' ||
   github.event_name == 'workflow_dispatch')
```

The job binds `environment: doc-lattice-linear`, declares only `contents: read`, and checks out
without persisting credentials. Setup actions and package installation run before the secret is
mapped. The Linear invocation is the only secret-bearing step and is the final step in the job.
The workflow uses exact package and action identities; implementation planning must choose and test
the concrete action SHAs. It does not restore or save a dependency or Actions cache. The pinned
setup action is configured with caching disabled when its interface offers that control. Future
caching requires a separate security review rather than relying implicitly on trigger-based cache
scoping.

No workflow generated by this feature grants `contents: write` or invokes real `reconcile`.

## Bootstrap script

The generated script has `plan`, `apply`, and `verify` operations and requires an explicit
`OWNER/REPO` target. It never infers authority solely from the current `gh` default repository.
`OWNER/REPO` is notation for the required owner and repository argument supplied at generation or
invocation time; it is never emitted literally into an executable command. The script embeds the
expected identity selected at generation and refuses an invocation argument that differs, so it
cannot configure a repository other than the one named by the generated workflow.

The initial script targets Bash 3.2 or later on macOS and Linux and requires the GitHub CLI. It uses
`gh api` and its built-in JSON query support, not a separate `jq`, `curl`, or Python runtime. Windows
maintainers may run it through a compatible Git Bash or WSL environment; native PowerShell is not
supported by the initial implementation. The generated instructions report these requirements
before setup begins.

### Plan

`plan` performs read-only checks:

- Confirm `gh` is installed and authenticated.
- Resolve the requested repository and its default branch.
- Require the GitHub host to be `github.com` for the initial implementation.
- Read repository visibility and owner/account plan or capability metadata. Public repositories are
  eligible; private or internal repositories proceed only when Pro, Team, or Enterprise support is
  positively established. Missing or ambiguous eligibility data is a hard failure.
- Require the default branch to be `main` for the initial implementation.
- Inspect the existing `doc-lattice-linear` environment, deployment policies, and visible secret
  metadata.
- Print the exact target and intended mutations without printing secret values.

### Apply

`apply` repeats the preflight, displays the plan, and requires interactive confirmation. It then:

1. Creates the environment if absent with custom branch policies enabled.
2. Creates the single `main` branch policy.
3. Reads the environment and branch policy back.
4. Stops unless verification proves the exact allow list.
5. Prints the exact `gh secret set DOC_LATTICE_LINEAR_API_KEY --env doc-lattice-linear
   --repo OWNER/REPO` command for the maintainer to run separately.

The script never enables a workflow or requests the secret before the environment policy verifies.
This ordering avoids the unsafe state in which a credential exists in an unrestricted or implicitly
created environment.

An exact existing configuration is accepted. A safely incomplete bootstrap-owned shape, such as a
custom-policy environment with no rules and no visible secret, can be completed after confirmation.
An environment that allows additional branches, tags, or pull-request refs is not narrowed
automatically because another workflow may own it; the script fails and prints manual remediation.

### Verify

`verify` is read-only and checks:

- The exact repository and default branch.
- The GitHub.com host, repository visibility, and continued environment-feature eligibility.
- The environment exists with custom branch policies enabled.
- The allow list contains exactly the `main` branch rule and no tag rule.
- The environment secret metadata contains `DOC_LATTICE_LINEAR_API_KEY`.
- No repository-scoped secret metadata with that name is visible.

It reminds the maintainer that organization-scoped exposure must be checked separately if the
current credential cannot inspect organization secret policy.

Remote API operations are not transactional. Every completed state is re-readable, and safe partial
states are resumable. On failure, the script reports completed checks, the failing operation, and
the next safe command; it does not delete preexisting remote state or guess at rollback ownership.

## CI audit command

`doc-lattice ci audit` reads repository workflow YAML without accessing the network or loading the
lattice. It distinguishes repository-global prohibitions from invariants owned by the two canonical
generated workflows.

### Repository-global rules

These rules apply to every YAML workflow under `.github/workflows`:

- `pull_request_target` is configured anywhere. This is an intentional repository policy even when
  an unrelated workflow could use the trigger safely.
- A workflow triggered by `pull_request`, `pull_request_review`, or
  `pull_request_review_comment` directly invokes `linear`.
- A workflow triggered by those pull-request events directly invokes `reconcile` without
  `--dry-run`.
- `LINEAR_API_KEY` or `DOC_LATTICE_LINEAR_API_KEY` is referenced anywhere except the canonical
  secret mapping in the generated Linear workflow's `linear` job.

Unrelated workflows may use broader token permissions or persisted checkout credentials when their
own behavior requires it. For example, a release workflow may retain `contents: write`; the audit
does not apply generated-workflow least-privilege rules to it.

### Managed-workflow rules

Managed checks are selected by the canonical paths `.github/workflows/doc-lattice.yml` and
`.github/workflows/doc-lattice-linear.yml`, not by guessing from workflow names. The Linear
workflow must retain the generated `linear` job id. A rename, missing canonical path, or missing job
id is an installation-policy finding rather than an attempt to infer an equivalent customized job.

For the two managed paths, audit enforces the exact supported triggers and commands, explicit
`contents: read`, pinned action identities, and checkout with `persist-credentials: false`. For the
Linear path it also enforces the fixed environment name, repository/ref/event condition, final-step
secret mapping, and exact `linear` job id. For the offline path it forbids every secret reference,
`linear`, and every `reconcile` invocation in the initial implementation.

Audit normalizes the canonical GitHub repository identity from an explicit `--repository
OWNER/REPO` option or, when omitted, the local `origin` URL. If neither yields one unambiguous
GitHub.com identity, audit exits `2` and requests the option. A mismatch between that identity and
the generated `github.repository` literal is an exit-`1` finding. This turns a repository rename or
transfer into an actionable audit failure instead of leaving the skipped Linear job as the only
signal.

The audit parses YAML structure and inspects direct shell invocations. It cannot prove that an
arbitrary script, local action, reusable workflow, or renamed wrapper does not eventually invoke a
sensitive command. Diagnostics and documentation state this limitation. The exact generated
templates and server-side environment are stronger controls than heuristic analysis of customized
workflows.

Exit codes follow existing gate conventions:

- `0`: inspected workflows satisfy the supported local invariants.
- `1`: one or more policy violations were found, including an absent workflows directory, either
  missing canonical generated workflow, or an unrecognized rename.
- `2`: a present workflow file could not be read, parsed, or inspected reliably, or repository
  identity needed for a managed check could not be determined.

## Error handling

- Invalid or unsafe CLI values use the existing `ConfigError` and exit-code-2 path.
- Repository, environment, branch, and secret names are validated and shell-quoted at the rendering
  boundary. Untrusted values are passed to `gh` as arguments, never evaluated as shell source.
- Local create collisions preserve existing bytes and identify the exact path.
- Remote authentication or authorization failure names the failed GitHub operation without printing
  tokens, request authorization, or secret values.
- A remote mismatch reports observed non-secret policy state and refuses mutation where ownership is
  ambiguous.
- Verification failure prevents the bootstrap from printing the secret-setting step as ready.
- No cleanup path deletes workflows, environments, policies, or secrets automatically.

## Testing strategy

### Pure rendering and audit tests

- Parse generated workflows as YAML and assert the exact triggers, permissions, environment, and
  step-level secret mapping.
- Assert the offline workflow runs audit, check, and lint even when an earlier gate reports a
  finding, then returns failure if any gate was nonzero.
- Assert the PR workflow contains no `linear`, Linear secret reference, `pull_request_target`, or
  real `reconcile`.
- Assert the Linear workflow's repository, ref, and event conditions fail for fork and same-repo PR
  event fixtures.
- Model current GitHub.com ref semantics explicitly: ordinary pull-request events use
  `refs/pull/N/merge`, while `pull_request_target` uses the default branch and is rejected by the
  global audit/event allow list rather than by the environment branch policy.
- Cover adversarial workflow fixtures for `pull_request_target`, `workflow_run`, job-level secrets,
  repository-scoped key names, multiline shell commands, and mutating reconciliation.
- Verify unrelated workflows may use `contents: write` and their own checkout policy without
  inheriting managed-workflow findings.
- Verify missing canonical files and repository-literal drift are findings, while malformed present
  YAML and ambiguous repository identity are tool errors.
- Document and test the boundary between detected direct invocation and unsupported indirection.

### CLI and filesystem tests

- Verify normal `init` output remains backward compatible.
- Verify `init --github` creates the complete artifact set only after a successful preflight.
- Verify existing exact files are accepted and differing files remain byte-identical.
- Verify concurrent create collisions preserve the winning file and return a tool error.
- Verify hostile repository and environment values cannot alter generated shell structure.
- Verify GitHub generation and refresh reject development, prerelease, and local versions without
  creating or replacing artifacts.

### Refresh tests

- Verify read-only refresh returns `0` for current artifacts and `1` with a stable unified diff for
  stale marked artifacts.
- Verify apply requires confirmation, replaces only marked canonical targets, and refuses unmarked
  or ambiguous files without changing any target.
- Verify a synthetic interruption between atomic replacements leaves a rerunnable mixed-version
  state.
- Verify a repository identity change updates the generated literal only through refresh.

### Bootstrap tests

- Run the generated script against a fake `gh` executable that records argument vectors and returns
  synthetic JSON.
- Run shell syntax and behavior tests against the documented Bash baseline; document Windows as
  Git Bash/WSL-only for this initial script.
- Cover absent, exact, safely incomplete, and dangerously broad environment states.
- Cover public repositories, eligible private/internal repositories, GitHub Free private
  repositories, unavailable plan metadata, and non-GitHub.com hosts. Unsupported or unprovable
  capability must fail before mutation.
- Cover authentication failure, insufficient permission, partial remote failure, rerun, secret
  metadata absence, and successful final verification.
- Assert no captured argument, output, or fixture contains a Linear secret value.

### Repository verification

Implementation handoff uses the complete project verification suite required by `CLAUDE.md`, plus
any shell syntax or lint check selected during implementation planning for the generated script.

## Documentation and durable decisions

- README owns the supported `init --github`, `ci audit`, bootstrap, and operator workflow.
- ARCHITECTURE.md gains a decision recording that GitHub administration is emitted as a reviewed
  external `gh` script, so the Python application's network boundary remains unchanged.
- CHANGELOG records the new installation and audit surface.
- The existing Linear CI security note is updated to link to the generated protected-environment
  workflow instead of duplicating the full contract.

## Residual risks

- A maintainer can approve or merge malicious code into `main`; optional environment review reduces
  but does not eliminate that governance risk.
- A compromised `gh` binary, maintainer workstation, pinned action, PyPI artifact, or resolved
  dependency can misuse credentials available during legitimate trusted execution.
- A maintainer can manually broaden or delete the environment policy after installation. Local
  audit cannot see that remote drift; rerunning bootstrap `verify` is required.
- Organization secrets and policies may be invisible to a repository-scoped administrator. The
  one-time setup includes an explicit organization-scope confirmation rather than claiming an
  unverifiable guarantee.
- Repository visibility or billing-plan changes can disable previously configured environment
  secrets or policies. Bootstrap `verify` must be rerun after such a change; unsupported or
  unprovable eligibility fails closed.
- Heuristic audit cannot recognize every indirect command execution path. GitHub's server-side
  environment policy remains authoritative.

## External behavior references

- [GitHub deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
  defines plan availability, environment secret timing, and `GITHUB_REF` branch-policy matching.
- [GitHub environment management](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
  documents that private repositories require an eligible paid plan and that an implicitly created
  environment otherwise has no protection rules or secrets.
- [GitHub's December 2025 pull-request ref change](https://github.blog/changelog/2025-11-07-actions-pull_request_target-and-environment-branch-protections-changes/)
  records current `refs/pull/N/merge` evaluation for ordinary pull-request events, default-branch
  evaluation for `pull_request_target`, and the previous head-ref behavior.
