# Maintainer Patterns

## Dependency PRs

- Dependabot PRs in this repo currently update only `uv.lock`.
- Prefer a local `uv lock --upgrade-package ...` refresh plus tests over merging bot PRs directly.

## Refactoring

- Keep MCP decorators in `server.py` thin; move orchestration and formatting logic to importable modules with focused tests.
- Keep live Evolution/D-Bus checks explicit. The default `uv run pytest` suite should remain runnable without a live Evolution session.
- Avoid global ignore patterns that hide legitimate test files under `tests/`.
