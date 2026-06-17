# Maintainer Runs

## 2026-06-17

- Scope: open issue/PR triage for `adrighem/eds-mcp`.
- Findings: no open non-PR issues; open PRs were Dependabot lockfile updates `PR:7`, `PR:8`, and `PR:9`.
- Action: combined dependency refresh locally with `uv lock --upgrade-package cryptography --upgrade-package starlette --upgrade-package python-multipart`.
- Repo-health fix: constrained root pytest collection to `tests/`; the bridge D-Bus test is an integration check that should be run explicitly in a system `gi` environment.
- Verification: `uv lock --check` passed; `uv run pytest` passed with 12 tests and 1 existing `PyGIDeprecationWarning`.
