# PR:7

## Intent

Update `python-multipart` in `uv.lock`.

## Maintainer Decision

Handle through local dependency refresh instead of merging the PR. `uv` resolved `python-multipart` 0.0.32, which is newer than the PR target.

## Verification

`uv lock --check` passed. `uv run pytest` passed.
