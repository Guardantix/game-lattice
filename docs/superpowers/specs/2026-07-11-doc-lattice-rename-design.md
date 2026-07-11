# doc-lattice rename design

Date: 2026-07-11
Status: approved

## Goal

Rename the project from game-lattice to doc-lattice everywhere: GitHub repo, Python package,
CLI entry point, adopter config file, cache location, docs, and prose positioning. The engine
was never game-specific; the name should match the general purpose (traceability for design
and production documentation in any domain).

## Decisions (confirmed with the owner)

1. **GitHub repo is renamed** to `Guardantix/doc-lattice`. GitHub redirects the old URL for
   web, git, and API traffic, so existing `uvx --from git+...@v0.8.0` pins keep working.
2. **Config filename is a clean break.** Only `.doc-lattice.yml` is recognized from 0.9.0.
   No fallback to `.game-lattice.yml`, no deprecation shim. Release notes tell adopters to
   rename the file.
3. **Prose generalizes.** Descriptions say design and production documentation generally, not
   game docs. Game-flavored illustrative examples (art direction, player-character spec) stay;
   they are good examples and the conftest fixture built on them is load-bearing.
4. **Ships as v0.9.0** with an explicit BREAKING section in the changelog. Historical
   spec/plan docs under `docs/superpowers/` are renamed and updated (the local-core spec is
   binding and must not contradict the code). CHANGELOG history stays untouched; entries were
   true when written.

## Approach

One rename PR carrying every code and doc change, with the GitHub repo renamed in a
coordinated cutover immediately before merge. The repo rename is an external mutation that a
PR revert cannot undo, so it happens only once the PR is green and merge-ready, shrinking the
window where the canonical repo name and `main` disagree to minutes. PR-stage CI never
fetches the repo URL (tests only assert strings), so the PR can be fully green before the
rename; the post-merge release job does fetch
`git+https://github.com/Guardantix/doc-lattice@<sha>`, so the rename must land before the
merge. Alternatives rejected: staged PRs (every intermediate state is internally
inconsistent), and a fresh repo (loses history, issues, and redirects).

## Order of operations

1. **The rename PR**, branched off `main` at v0.8.0 (`rename/doc-lattice`):
   - Package/CLI: `git mv src/game_lattice src/doc_lattice`; pyproject `name`, entry point
     (`doc-lattice = "doc_lattice.cli:main"`), `packages`, coverage paths, Homepage; all
     imports across src and tests.
   - Breaking adopter surfaces: `DEFAULT_CONFIG_NAME = ".doc-lattice.yml"` (config.py);
     scaffold constant renamed to `DOC_LATTICE_REPO_URL` with the new URL and regenerated
     pre-commit/CI codegen text; cache path segment `<cache_home>/doc-lattice/` (old opt-in
     caches are orphaned, not migrated; they regenerate on first load);
     `tests/fixtures/release-smoke/.doc-lattice.yml` and the CI smoke step that reads it.
   - Prose: README, pyproject description, ARCHITECTURE.md, CLAUDE.md, RELEASING.md,
     roadmap.md, build-log.md, module docstrings, and CLI help/error strings.
   - Docs: rename the `docs/superpowers/` spec and plan files whose names contain
     game-lattice and update their content references.
   - Version: 0.9.0 in `src/doc_lattice/__init__.py`, pyproject, and a new CHANGELOG entry
     listing the breaking changes (config filename, CLI and package name, cache location,
     repo URL) and carrying the adopter migration checklist below verbatim.
     `uv lock` regenerates the lockfile.
2. **Verification before the PR:** full pytest (with `env -u FORCE_COLOR`), ruff check and
   format, ty, the typing-boundary and version-sync scripts, an end-to-end
   `uv run doc-lattice check` against a fixture, and a repo-wide
   `grep -rI 'game.lattice'` sweep that must be empty outside CHANGELOG history and this
   spec (which necessarily names the old identity).
3. **Cutover, once the PR is green and merge-ready:** `gh repo rename doc-lattice`, then
   `git remote set-url origin git@github.com:Guardantix/doc-lattice.git`. Verify both URLs
   before merging: `git ls-remote https://github.com/Guardantix/doc-lattice.git HEAD` (new
   name live) and the same against `.../game-lattice.git` (redirect intact). Rollback while
   unmerged: `gh repo rename game-lattice` restores the old name and the PR remains an
   ordinary unmerged branch; nothing on `main` referenced the new name yet.
4. **Merge immediately after the cutover.** The existing release job on `main` verifies
   version sync, smoke-tests via the new URL, and cuts the `v0.9.0` tag on the renamed repo.
   Post-merge smoke test:
   `uvx --from git+https://github.com/Guardantix/doc-lattice@v0.9.0 doc-lattice --help`.
5. **Local environment, last:** rename the working directory
   `~/workspace/repos/tooling/game-lattice` to `doc-lattice` and migrate the Claude memory
   directory to the new project-path key. This invalidates the running session's cwd, so it
   is the final act; the owner reopens Claude Code from the new path.

## Error handling and risks

- `gh repo rename` requires admin rights on the repo (the owner has them).
- If the release job fails after merge, the manual tag fallback in RELEASING.md applies
  unchanged.
- Old cache directories under `<cache_home>/game-lattice/` are stale garbage after upgrade;
  harmless, and adopters can delete them.
- No data or graph semantics change; the lattice frontmatter vocabulary (`id`,
  `derives_from`, `authority`, `seen`) is untouched. Doc sets themselves need no edits, but
  upgrading an install is more than the config rename; see the migration checklist.

## Adopter migration (v0.8.x to v0.9.0)

Nothing breaks until an adopter bumps their pin: checked-in gates pin a tag
(`uvx --from git+.../game-lattice@v0.8.0 game-lattice ...`) and GitHub's rename redirect
keeps that resolving indefinitely. Upgrading the pin to v0.9.0 requires, in one commit:

1. Rename `.game-lattice.yml` to `.doc-lattice.yml` (contents unchanged).
2. Regenerate the checked-in pre-commit hook and CI workflow (re-run `doc-lattice init`
   codegen, or by hand update the repo URL, the `@v0.9.0` pin, and the executable name
   `game-lattice` to `doc-lattice` in each invocation).
3. Any Python code importing `game_lattice` switches to `doc_lattice` (the package is not on
   PyPI and no import consumers are known; listed for completeness).

This checklist ships verbatim in the 0.9.0 CHANGELOG entry, which becomes the release notes.
A tested v0.8-to-v0.9 upgrade fixture was considered and rejected: the breakage surface lives
in adopter-side checked-in files and the GitHub redirect, neither of which a test in this
repo can exercise; the release job's `uvx` smoke of the new tag covers the installable
surface.

## Testing

The existing suite (723 tests, coverage gate 80 percent) already pins every renamed surface:
test_scaffold asserts the repo URL and codegen text, test_config asserts the config filename,
test_cache asserts the cache path, test_cli asserts help text. Updating those assertions is
part of the rename; no new test machinery is needed.
