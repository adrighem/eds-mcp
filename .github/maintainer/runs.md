# Maintainer Runs

## 2026-08-14

- Scope: open issue/PR triage for `adrighem/eds-mcp`.
- Findings: no open non-PR issues; open PR `PR:15` is a Dependabot update targeting `pypdf` from 6.14.2 to 6.15.0.
- Action: refreshed `pypdf` locally with `uv lock --upgrade-package pypdf`; resolver selected `pypdf` 6.16.1, which is newer than the PR target 6.15.0 and includes both robust security fixes and critical bug resolutions.
- Verification: `make lock-check` passed; `uv run pytest tests/test_documents.py` passed.

## 2026-06-24

- Scope: open issue/PR/security triage for `adrighem/eds-mcp`.
- Findings: no open issues, PRs, Dependabot alerts, or code-scanning alerts.
- Action: no public action needed.

## 2026-06-24 local maintenance

- Scope: resolve local stash/upstream conflicts and refresh dependencies.
- Action: resolved conflicts in the Evolution bridge, environment setup, and generated `uv.lock`; refreshed all Python dependencies with `uv lock --upgrade`.
- Bridge resolution: kept `MarkAsRead`, kept one `SendMail` D-Bus XML entry, and retained the transport-UID based `SendMail` implementation.
- Environment resolution: combined D-Bus session fallback with the PyGObject warning filter.
- Verification: `make check` passed with 26 tests; `cmake --build evolution-mcp-automation-bridge/build` passed.

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

## 2026-06-17 refactor pass

- Scope: contributor-focused refactor for readability, testability, and onboarding.
- Action: extracted `summary.py`, refactored `documents.py`, consolidated mail bridge calls, added `CONTRIBUTING.md`, expanded Makefile checks, and fixed `.gitignore` so tests under `tests/` are not ignored.
- Verification: `make check` passed with 24 tests and 1 existing `PyGIDeprecationWarning`.
