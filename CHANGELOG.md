# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed (BREAKING)

- `Collection.get_index_status` `status` field value renamed from
  `"ready"` to `"queryable"`. MCP clients pattern-matching on the
  old value will silently treat the new value as unknown until
  updated.
- `Collection.get_index_status` priority order flipped: a built
  index with a captured background error from a prior attempt now
  reports `status="queryable"` (with the diagnostic in `error`),
  not `status="failed"`. `"failed"` now means "preconditions do not
  hold AND a captured error exists" — i.e., the index is not
  readable.
- `Collection.is_index_ready()` renamed to `Collection.is_queryable()`.
- `Collection._require_index_ready()` (private) renamed to
  `Collection._require_built()` — matches what it actually checks
  (only `_index_built`, single field).
- `Collection.wait_for_index_ready()` renamed to
  `Collection.wait_until_queryable()`.
- MCP decorator `needs_index_ready` renamed to `needs_queryable`.
  Module `_server_readiness.py` renamed to `_server_queryable.py`.
- Public exception `IndexNotReadyError` renamed to
  `IndexUnavailableError`.
- Environment variable `MARKDOWN_VAULT_MCP_READY_TIMEOUT_S` renamed
  to `MARKDOWN_VAULT_MCP_BUILD_TIMEOUT_S`. Running deployments that
  set the old variable will silently fall back to the 60-second
  default after upgrading; update operator configs (compose files,
  systemd units, `.env` files) accordingly.

External consumers that previously imported `IndexNotReadyError`,
called `is_index_ready()`/`wait_for_index_ready()`, or set the old
env var must rename their references. No deprecation shims ship.
