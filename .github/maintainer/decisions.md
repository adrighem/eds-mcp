# Maintainer Decisions

## 2026-06-17

- Initialized maintainer state because the repository did not yet have `.github/maintainer/`.
- Combined open Dependabot lockfile-only PRs into one local dependency refresh rather than reviewing or merging each bot branch independently.
- Constrained root pytest discovery to `tests/` because the bridge D-Bus test requires Evolution and `gi` and is not a default unit-test dependency.

## 2026-06-17 refactor pass

- Extracted daily-summary orchestration from `server.py` into `summary.py` so it can be tested without GI or MCP registration side effects.
- Refactored document parsing around a parser registry and explicit context limits so new file formats have a clear extension point.
- Narrowed `.gitignore` root scratch-test handling from `test_*.py` to `/test_*.py`; real unit tests under `tests/` should be trackable.
- Added contributor documentation and Makefile checks to reduce setup and review friction.

## 2026-06-24 local maintenance

- Resolved the `env.py` conflict by keeping both the D-Bus session-bus fallback and the PyGObject deprecation-warning suppression.
- Resolved the bridge conflict by keeping the upstream `MarkAsRead` method and the transport-UID based `SendMail` path, while removing the duplicate `SendMail` XML declaration.
- Refreshed `uv.lock` with a full `uv lock --upgrade` after resolving generated lockfile conflicts.

## 2026-08-14 dependency maintenance

- Refreshed `pypdf` dependency via local `uv lock --upgrade-package pypdf` rather than merging Dependabot branch `PR:15` directly.
- Validated new version 6.16.1 against core document parser tests to confirm no regressions in PDF extraction logic.
