# Maintainer Patterns

## Dependency PRs

- Dependabot PRs in this repo currently update only `uv.lock`.
- Prefer a local `uv lock --upgrade-package ...` refresh plus tests over merging bot PRs directly.

