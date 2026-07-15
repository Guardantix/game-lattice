# GitHub Linear CI Bootstrap Design

**Date:** 2026-07-15
**Status:** Approved for implementation planning

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

## Non-goals

- The installer will not accept, store, transmit, or validate the value of the Linear API key.
- The installer will not run `gh`, call GitHub APIs, or hold a GitHub credential itself.
- The installer will not create a CI workflow that runs real `reconcile`.
- The audit command will not claim to prove arbitrary GitHub Actions workflows safe. It is drift
  detection, not the authorization boundary.
- The feature will not administer organization-wide Actions policies or rulesets. Those remain an
  optional organization-owner control.
- The feature will not automatically rewrite customized workflows or existing GitHub environments.

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

The contract does not protect a malicious commit already admitted to trusted `main`. Branch
protection and review decide what becomes trusted. An optional required reviewer and disabled
administrator bypass can extend protection to each Linear run, at the cost of manual approval for
every run.

## Generated artifacts

An explicit `doc-lattice init --github` mode adds three create-only artifacts while retaining the
existing config behavior:

1. `.github/workflows/doc-lattice.yml` runs offline PR gates.
2. `.github/workflows/doc-lattice-linear.yml` runs the Linear gate on trusted `main` only.
3. A clearly named one-time bootstrap script configures and verifies the GitHub environment with
   `gh`. The script contains no secret value and warns the maintainer to review it and run it only
   from trusted project state.

Before creating any missing artifact, `init --github` preflights the complete target set:

- An absent target is eligible for creation.
- An existing byte-identical generated artifact is accepted.
- Any differing existing artifact causes a tool error before doc-lattice creates another target.

After a successful preflight, missing files use the existing durable create-if-absent primitive.
A concurrent creator can still win between preflight and creation; that race reports a tool error
and preserves the winner's bytes. The operation does not need a destructive rollback because every
write is create-only and a safe rerun can accept exact artifacts.

Normal `doc-lattice init` retains its current output and write behavior. GitHub artifacts are
created only when `--github` is explicitly selected.

## Offline pull-request workflow

The PR workflow:

- Triggers exactly on `pull_request` targeting `main` and `push` to `main`.
- Declares `permissions: contents: read` explicitly.
- Pins third-party actions to full commit SHAs with human-readable release comments.
- Uses `persist-credentials: false` for checkout.
- Runs the exact published doc-lattice version selected by the release that generated it.
- Runs `check` and `lint`.
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
the concrete action SHAs.

No workflow generated by this feature grants `contents: write` or invokes real `reconcile`.

## Bootstrap script

The generated script has `plan`, `apply`, and `verify` operations and requires an explicit
`OWNER/REPO` target. It never infers authority solely from the current `gh` default repository.
`OWNER/REPO` is notation for the required owner and repository argument supplied at generation or
invocation time; it is never emitted literally into an executable command.

### Plan

`plan` performs read-only checks:

- Confirm `gh` is installed and authenticated.
- Resolve the requested repository and its default branch.
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
lattice. It reports direct violations of the supported GitHub contract:

- `pull_request_target` is configured.
- A PR-triggered workflow directly invokes `linear`.
- A PR-triggered workflow directly invokes `reconcile` without `--dry-run`.
- `LINEAR_API_KEY` or `DOC_LATTICE_LINEAR_API_KEY` is referenced outside the supported trusted job.
- The trusted job lacks `environment: doc-lattice-linear`.
- The trusted workflow permits events other than the supported trusted triggers.
- Token permissions exceed `contents: read`.
- Checkout explicitly persists credentials or omits the generated safe setting.

The audit parses YAML structure and inspects direct shell invocations. It cannot prove that an
arbitrary script, local action, reusable workflow, or renamed wrapper does not eventually invoke a
sensitive command. Diagnostics and documentation state this limitation. The exact generated
templates and server-side environment are stronger controls than heuristic analysis of customized
workflows.

Exit codes follow existing gate conventions:

- `0`: inspected workflows satisfy the supported local invariants.
- `1`: one or more policy violations were found.
- `2`: workflows could not be discovered, parsed, or inspected reliably.

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
- Assert the PR workflow contains no `linear`, Linear secret reference, `pull_request_target`, or
  real `reconcile`.
- Assert the Linear workflow's repository, ref, and event conditions fail for fork and same-repo PR
  event fixtures.
- Cover adversarial workflow fixtures for `pull_request_target`, `workflow_run`, job-level secrets,
  repository-scoped key names, multiline shell commands, and mutating reconciliation.
- Document and test the boundary between detected direct invocation and unsupported indirection.

### CLI and filesystem tests

- Verify normal `init` output remains backward compatible.
- Verify `init --github` creates the complete artifact set only after a successful preflight.
- Verify existing exact files are accepted and differing files remain byte-identical.
- Verify concurrent create collisions preserve the winning file and return a tool error.
- Verify hostile repository and environment values cannot alter generated shell structure.

### Bootstrap tests

- Run the generated script against a fake `gh` executable that records argument vectors and returns
  synthetic JSON.
- Cover absent, exact, safely incomplete, and dangerously broad environment states.
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
- Heuristic audit cannot recognize every indirect command execution path. GitHub's server-side
  environment policy remains authoritative.
