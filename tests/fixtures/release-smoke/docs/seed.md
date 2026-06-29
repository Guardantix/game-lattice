---
id: release-smoke-seed
layer: design
---
# Release Smoke Seed {#release-smoke-seed-top}

A standalone node with no derives_from edges. check finds nothing stale and lint
finds nothing to rank, so both exit 0. Used only by the CI release smoke step.
