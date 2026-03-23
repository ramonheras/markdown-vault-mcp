# Cross-Repo Sync: markdown-vault-mcp ↔ image-generation-mcp

Both repos share a common origin and have overlapping infrastructure.
This document tracks the shared surface and port history to prevent
silent divergence.

## Shared File Mapping

| Area | markdown-vault-mcp | image-generation-mcp | Notes |
|------|-------------------|----------------------|-------|
| **Auth: bearer** | `mcp_server.py:_build_bearer_auth()` | `mcp_server.py:_build_bearer_auth()` | Identical (env prefix differs) |
| **Auth: remote** | `mcp_server.py:_build_remote_auth()` | `mcp_server.py:_build_remote_auth()` | MV guards missing httpx with ImportError; IG does bare import (crashes if absent) |
| **Auth: oidc-proxy** | `mcp_server.py:_build_oidc_auth()` | `mcp_server.py:_build_oidc_auth()` | Identical (env prefix differs) |
| **Auth: mode detect** | `mcp_server.py:_resolve_auth_mode()` | `mcp_server.py:_resolve_auth_mode()` | MV logs on explicit+auto-detect; IG logs only warning |
| **Auth: multi-auth** | `mcp_server.py:create_server()` | `mcp_server.py:create_server()` | Both use `MultiAuth(…, required_scopes=[])` |
| **CI: lint+type+test** | `.github/workflows/ci.yml` | `.github/workflows/ci.yml` | Structure identical; diff-cover approach differs (see below) |
| **CI: audit** | `ci.yml` audit job | `ci.yml` audit job | MV has `--ignore-vuln CVE-2026-25990` |
| **CI: secrets** | `ci.yml` gitleaks (SHA-pinned) | `ci.yml` gitleaks (SHA-pinned) | Identical |
| **Release** | `.github/workflows/release.yml` | `.github/workflows/release.yml` | Structure identical (see divergences) |
| **CLI** | `cli.py` | `cli.py` | Both use FastMCP `configure_logging()` |
| **Docker** | `Dockerfile` + `docker-entrypoint.sh` | `Dockerfile` + `docker-entrypoint.sh` | Volume layout differs (project-specific) |
| **Packaging** | `packaging/nfpm.yaml` + systemd unit | `packaging/nfpm.yaml` + systemd unit | Paths differ, structure shared |
| **server.json** | Per-package `environmentVariables` | Root-level `environmentVariables` | MV is correct; IG is legacy format |
| **Auth docs** | `docs/guides/authentication.md`, `docs/deployment/oidc.md` | `docs/guides/authentication.md`, `docs/deployment/oidc-providers.md` | Content aligned after backport |

**Legend:** MV = markdown-vault-mcp, IG = image-generation-mcp

## Known Divergences

These are intentional or pending differences between the repos.

### CI: diff-cover Python detection

| | markdown-vault-mcp | image-generation-mcp |
|-|-------------------|----------------------|
| **Method** | `git diff --name-only` (pure git) | `gh pr view --json files` (GitHub API) |
| **Permission** | No extra permissions needed | Requires `pull-requests: read` |
| **No-coverable-lines** | Falls through to `TOTAL="unknown"` | Explicit "No coverable lines in diff" case |
| **Step ID** | `diffcover` | `patch-coverage` |
| **Status passing** | String interpolation in github-script | Env vars (`PATCH_STATE`, `PATCH_DESC`) |

**Assessment:** Both work. IG's "no coverable lines" case is cleaner.
MV's approach avoids the extra GitHub API permission. Recommend
converging on one approach in a future sync.

### Release: versionless package copies

IG creates `_latest.deb` / `_latest.rpm` symlinks for stable download
URLs. MV does not. Low priority — useful for documentation but not
blocking.

### Release: linux-packages job dependencies

| | markdown-vault-mcp | image-generation-mcp |
|-|-------------------|----------------------|
| `needs:` | `[release]` | `[release, publish-pypi]` |

Both are correct — Linux packages don't depend on PyPI or Docker.
MV's approach allows faster parallel execution.

### server.json structure

MV uses per-package `environmentVariables` (correct per MCP registry
schema). IG still has root-level `environmentVariables` (legacy). IG
also lists `LOG_LEVEL` which is stale after logging consolidation
(should reference `FASTMCP_LOG_LEVEL`).

**Port direction:** MV → IG (IG should adopt per-package format)

### Auth: httpx error handling

MV catches `ImportError` separately in `_build_remote_auth()` with a
clear install instruction message. IG does bare `import httpx` (crashes
on missing dep) and catches `(httpx.HTTPError, ValueError)` for
discovery. MV's approach is more robust for optional-dependency
scenarios.

**Port direction:** MV → IG

### image-gen-specific features (not shared)

These exist only in image-generation-mcp and are NOT candidates for
porting:

- `ResourcesAsTools` transform (exposes resources as tools for clients
  without resource support)
- MCP-level keepalives during long image generation (#95/#96)
- `HTTP_PATH` env var for streamable-http mount path

## Sync Log

Completed ports, newest first.

| Date | Direction | What | Source PR | Target PR |
|------|-----------|------|-----------|-----------|
| 2026-03-23 | IG → MV | Authelia remote auth docs | image-gen#104 | MV#268 (bundled) |
| 2026-03-23 | IG → MV | RemoteAuthProvider OIDC mode | image-gen#101 | MV#268 |
| 2026-03-23 | IG → MV | diff-cover patch coverage gate | image-gen#99 | MV#267 |
| 2026-03-21 | IG → MV | server.json + release pipeline fixes | image-gen#97 | MV#241, MV#243 |
| 2026-03-21 | IG → MV | Consolidate onto FastMCP logging | image-gen#82 | MV#263 |

## Pending Ports

| Direction | What | Source | Priority | Notes |
|-----------|------|--------|----------|-------|
| MV → IG | Per-package server.json format | MV#243 | Medium | IG still uses legacy root-level format |
| MV → IG | httpx ImportError guard in `_build_remote_auth()` | MV#268 | Low | Prevents crash when httpx not installed |
| IG → MV | Versionless `_latest.deb`/`_latest.rpm` copies | IG release.yml | Low | Stable download URLs |
| IG → MV | "No coverable lines" explicit diff-cover case | IG#102 ci.yml | Low | Cleaner than TOTAL="unknown" fallthrough |
