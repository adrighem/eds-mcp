# Maintainer Decisions

## 2026-06-17

- Initialized maintainer state because the repository did not yet have `.github/maintainer/`.
- Combined open Dependabot lockfile-only PRs into one local dependency refresh rather than reviewing or merging each bot branch independently.
- Constrained root pytest discovery to `tests/` because the bridge D-Bus test requires Evolution and `gi` and is not a default unit-test dependency.
