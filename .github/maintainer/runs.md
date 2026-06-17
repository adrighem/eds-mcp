# Maintainer Runs

## 2026-06-17

- Scope: open issue/PR triage for `adrighem/eds-mcp`.
- Findings: no open non-PR issues; open PRs were Dependabot lockfile updates `PR:7`, `PR:8`, and `PR:9`.
- Action: combined dependency refresh locally with `uv lock --upgrade-package cryptography --upgrade-package starlette --upgrade-package python-multipart`.
- Repo-health fix: constrained root pytest collection to `tests/`; the bridge D-Bus test is an integration check that should be run explicitly in a system `gi` environment.
- Verification: `uv lock --check` passed; `uv run pytest` passed with 12 tests and 1 existing `PyGIDeprecationWarning`.

## 2026-06-17 pypdf follow-up

- Scope: `gh-helper --repo adrighem/eds-mcp` follow-up.
- Findings: no open issues, no unread notifications, no code scanning alerts; open `PR:10` and Dependabot alerts `ALERT:18`, `ALERT:19`, `ALERT:20`, and `ALERT:21` all target `pypdf`.
- Action: refreshed `pypdf` locally with `uv lock --upgrade-package pypdf`; resolver selected `pypdf` 6.13.2, newer than the PR target 6.13.0.
- Verification: `uv lock --check` passed; `uv run pytest` passed with 12 tests and 1 existing `PyGIDeprecationWarning`.
