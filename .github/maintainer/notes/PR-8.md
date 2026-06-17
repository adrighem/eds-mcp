# PR:8

## Intent

Update `starlette` in `uv.lock`.

## Maintainer Decision

Handle through local dependency refresh instead of merging the PR.

## Verification

`uv lock --check` passed. `uv run pytest` passed.
