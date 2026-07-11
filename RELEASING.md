# Releasing doc-lattice

doc-lattice is distributed from git, not from PyPI. The `init` command prints
pre-commit and CI snippets that pin `uvx --from git+...@vX.Y.Z`, so a release is
only complete once the matching tag exists and resolves. The version bump is the
human step; CI cuts and verifies the tag on merge, so a half-done release (code
merged but no tag, or a tag without the version bump) cannot land.

## Checklist

1. Bump the version to the new `X.Y.Z` in all four locations:
   - `src/doc_lattice/__init__.py` (`__version__`)
   - `pyproject.toml` (`version`)
   - the `@vX.Y.Z` ref in the README "Adopting doc-lattice" `uvx` command (a
     manual edit, but now checked by the version-sync guard)
2. Run `uv lock` and commit the refreshed `uv.lock`.
3. Add a `## [X.Y.Z]` section to `CHANGELOG.md` (rename the `## [Unreleased]`
   section if you have been accumulating notes there). This section's body becomes
   the GitHub Release notes the release job publishes, so it must not be empty.
4. Open the PR and get it green. The `check-version-sync` gate fails the PR if
   `__version__`, `pyproject.toml`, the `CHANGELOG.md` heading, or a pinned
   `doc-lattice@vX.Y.Z` ref in `README.md` disagree, so fix any drift before
   merge.
5. Merge to `main`. On that push, the `release` job:
   - verifies version sync again,
   - smoke-tests the exact commit over `git+...@<sha>`, running `check`, `lint`,
     and `init`,
   - creates and pushes the lightweight `vX.Y.Z` tag,
   - publishes a GitHub Release for that tag, with the body taken from the
     `## [X.Y.Z]` section of `CHANGELOG.md`,
   - confirms the pinned `@vX.Y.Z` ref resolves.

   The release-notes step runs after the tag is pushed (the tag is the
   load-bearing artifact). If it fails because the `## [X.Y.Z]` section is empty,
   the tag still lands; add the notes and publish the Release by hand with
   `gh release create vX.Y.Z --title vX.Y.Z --notes-file <(...)`, since a re-run
   will no-op once the tag exists.

   An ordinary merge that does not change the version is a safe no-op: the job
   confirms the existing tag points at a commit of the matching version.

If the release job fails after the tag is pushed, do not move the tag: cut
`X.Y.(Z+1)` instead, because a moved tag breaks adopters already pinned to the
old one.

The tag must point at a commit that contains `check`, `lint`, and `init`, so the
gates run and adopters can run `doc-lattice init` from the same ref. The release
job's smoke step enforces exactly this before the tag is created.
