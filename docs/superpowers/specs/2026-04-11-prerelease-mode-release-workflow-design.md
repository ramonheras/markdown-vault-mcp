---
title: Pre-release mode for release.yml
issue: https://github.com/pvliesdonk/markdown-vault-mcp/issues/352
supersedes: https://github.com/pvliesdonk/markdown-vault-mcp/issues/351
date: 2026-04-11
---

# Pre-release mode for `release.yml`

## Goal

Add a `prerelease` boolean input to the existing `workflow_dispatch` trigger in
`.github/workflows/release.yml`. When set, the workflow exercises the full
release pipeline — semantic versioning, Docker build, mcpb bundle — but
**does not touch PyPI, the Linux packages, the MCP Registry, or the Claude Code
catalog**. The only public surfaces produced are:

- a GitHub **Pre-release** tagged `vX.Y.Z-rc.N`, with SBOM, source tarball, and
  `.mcpb` bundle attached
- a Docker image pushed as `ghcr.io/pvliesdonk/markdown-vault-mcp:unstable`
  and `:vX.Y.Z-rc.N` (no `:latest`, no floating minor/major tags)

This creates a real-world smoke-test channel for release-pipeline changes
without polluting stable catalogs. Supersedes the dry-run-only scope of
issue #351.

## Non-goals

- No new workflow file. This is an additive change to `release.yml` only.
- No TestPyPI integration. Dependency resolution from TestPyPI is unreliable;
  the Docker image and mcpb bundle cover the runtime paths we need to verify.
- No automated promotion from rc to stable. Real releases remain an explicit
  opt-in via the dispatch form.

## User-facing behavior

When a user triggers the `Release` workflow from the GitHub Actions tab, the
dispatch form now shows **two** inputs:

| Input | Type | Default | Notes |
|---|---|---|---|
| `force` | choice (`''`/`patch`/`minor`/`major`) | `''` | existing |
| `prerelease` | boolean | **`true`** | **new** — uncheck to cut a real release |

**The default is `true`** deliberately: real releases are rare and high-stakes,
pre-releases are cheap and safe. A reflexive "click and dispatch" should not
push to PyPI — the user has to consciously uncheck the box to do a real release.

The description text on the input reads:

> Create a pre-release (rc channel — skips PyPI, catalog, registry, linux
> packages). Uncheck to cut a real release.

## Job-by-job behavior matrix

| Job | Normal release | Pre-release (`prerelease: true`) |
|---|---|---|
| `release` (semantic-release) | creates `vX.Y.Z` tag, full GitHub Release | creates `vX.Y.Z-rc.N` tag, GitHub **Pre-release** |
| `release` → *Update versioned manifests* step | runs (commits `server.json`/`plugin.json`/`.mcp.json`, force-moves tag) | **skipped** |
| `publish-pypi` | runs | **skipped** |
| `publish-docker` | tags `:latest`, `:vX.Y.Z`, `:v1.21`, `:v1` | tags `:unstable`, `:vX.Y.Z-rc.N` |
| `publish-linux-packages` | runs | **skipped** |
| `build-mcpb` | runs | runs (unchanged — envsubst renders `vX.Y.Z-rc.N` into templates) |
| `publish-mcpb` | attaches `.mcpb` to Release | attaches `.mcpb` to Pre-release |
| `publish-claude-plugin-pr` | opens catalog bump PR | **skipped** |
| `publish-registry` | publishes to MCP Registry | **skipped** |

Net result on pre-release: only `release` (minus the manifest-bump step),
`publish-docker` (unstable tag set), `build-mcpb`, and `publish-mcpb` run.

## Implementation details

### 1. New `workflow_dispatch` input

Add under the existing `force` input:

```yaml
on:
  workflow_dispatch:
    inputs:
      force:
        description: 'Force version bump (leave empty for auto)'
        type: choice
        default: ''
        options:
          - ''
          - patch
          - minor
          - major
      prerelease:
        description: 'Create a pre-release (rc channel — skips PyPI, catalog, registry, linux packages). Uncheck to cut a real release.'
        type: boolean
        default: true
```

### 2. Semantic-release pre-release flags

The `python-semantic-release/python-semantic-release@v10.5.3` action already
supports `prerelease` and `prerelease_token` inputs. Thread the dispatch input
through:

```yaml
- name: Semantic Version Release
  id: release
  uses: python-semantic-release/python-semantic-release@v10.5.3
  with:
    github_token: ${{ secrets.RELEASE_TOKEN }}
    git_committer_name: "github-actions"
    git_committer_email: "actions@users.noreply.github.com"
    force: ${{ inputs.force }}
    prerelease: ${{ inputs.prerelease }}
    prerelease_token: rc
```

This produces versions like `1.21.0-rc.1`, `1.21.0-rc.2`, and marks the
resulting GitHub Release as a pre-release automatically.

### 3. Skip the "Update versioned manifests" step on pre-release

Add `&& !inputs.prerelease` to the step-level `if:`:

```yaml
- name: Update versioned manifests to released version
  if: steps.release.outputs.released == 'true' && !inputs.prerelease
```

**Why this step can be skipped safely on pre-release:**

- `server.json` is only consumed by the MCP Registry → that job is skipped.
- `plugin.json` / `.mcp.json` are only consumed by the Claude Code catalog →
  that job is skipped.
- The mcpb bundle takes its version from `envsubst '${VERSION}'` at build
  time, using `${{ needs.release.outputs.version }}` — no committed change
  required.

Skipping avoids committing `vX.Y.Z-rc.N` into `.claude-plugin/plugin/plugin.json`
on `main` (which would leak the rc version to anyone pulling `main` between the
pre-release and the next real release).

### 4. Skip downstream jobs on pre-release

Add `&& !inputs.prerelease` to the job-level `if:` of:

- `publish-pypi`
- `publish-linux-packages`
- `publish-claude-plugin-pr`
- `publish-registry`

Example:

```yaml
publish-pypi:
  needs: release
  if: needs.release.outputs.released == 'true' && !inputs.prerelease
```

### 5. Conditional Docker tags

In `publish-docker`, replace the current static `tags:` block in the
`docker/metadata-action` step with mode-aware entries using the native
`enable=<bool>` per-tag modifier supported by `docker/metadata-action`:

```yaml
- name: Extract metadata (tags, labels)
  id: meta
  uses: docker/metadata-action@v5
  with:
    images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
    tags: |
      type=raw,value=v${{ steps.version.outputs.version }}
      type=raw,value=latest,enable=${{ !inputs.prerelease }}
      type=raw,value=v${{ steps.version.outputs.minor }},enable=${{ !inputs.prerelease }}
      type=raw,value=v${{ steps.version.outputs.major }},enable=${{ !inputs.prerelease }}
      type=raw,value=unstable,enable=${{ inputs.prerelease }}
    labels: |
      org.opencontainers.image.title=markdown-vault-mcp
      org.opencontainers.image.description=Generic markdown vault MCP server with FTS5 + semantic search
      org.opencontainers.image.vendor=pvliesdonk
      io.modelcontextprotocol.server.name=io.github.pvliesdonk/markdown-vault-mcp
```

The `enable=<bool>` modifier is native `docker/metadata-action` syntax — when
the boolean resolves to `false`, the action omits that tag entirely. This
produces exactly the right tag set per mode:

- **Normal release:** `:v1.21.0`, `:latest`, `:v1.21`, `:v1`
- **Pre-release:** `:v1.21.0-rc.1`, `:unstable`

The full versioned tag is always pushed. Floating stable tags (`:latest`,
`:v1.21`, `:v1`) never move on a pre-release.

### 6. What does NOT change

- `build-mcpb` needs no modification. `needs.release.outputs.version` already
  carries `1.21.0-rc.1` on pre-release. `envsubst '${VERSION}'` renders it
  into `manifest.json` and `pyproject.toml` unchanged.
- `publish-mcpb` needs no modification. `gh release upload <tag>` accepts
  pre-release tags the same as stable tags.
- The `release` job still uploads SBOM, source tarball, and
  semantic-release's publish-action assets — they simply attach to the
  pre-release rather than a stable release.
- `publish-docker` still generates build provenance attestations and Docker
  SBOMs for pre-release images. These are cheap, useful for testing the full
  security pipeline, and carry no downside for unstable builds.

### 7. Behavior when `inputs.prerelease` is unset

`release.yml` only has a `workflow_dispatch` trigger, so `inputs.prerelease`
is always supplied (default `true`). Should a future `push` or `schedule`
trigger be added, `inputs.prerelease` would evaluate to `''` (falsy), so
`!inputs.prerelease` is truthy → normal-release behavior. Safe fallthrough.

## Acceptance criteria

- Dispatching with `prerelease: true` (the default) produces a
  `vX.Y.Z-rc.N` **Pre-release** on GitHub with `.mcpb` bundle, SBOM, and
  source tarball attached.
- `publish-pypi`, `publish-linux-packages`, `publish-claude-plugin-pr`, and
  `publish-registry` jobs are skipped on pre-release (verified via workflow
  run UI showing them as "skipped").
- Docker image is pushed as `ghcr.io/.../markdown-vault-mcp:unstable` and
  `:vX.Y.Z-rc.N` on pre-release; `:latest` / `:v1.21` / `:v1` still point at
  the last real release (verified by `docker manifest inspect`).
- The "Update versioned manifests" step is skipped on pre-release; `main`
  receives no `rc.N` manifest commits.
- Dispatching with `prerelease: false` produces behavior identical to the
  current release workflow — same tags, same PyPI push, same catalog PR,
  same registry publish.
- mcpb bundle downloaded from the pre-release installs successfully in
  Claude Desktop as a smoke test.

## Documentation impact

Per `CLAUDE.md` Documentation Discipline, the following need updating alongside
the workflow change:

- **`docs/design.md`** — add a short "Release channels" note covering the
  stable/pre-release distinction and what each produces.
- **`docs/installation.md`** — mention `:unstable` as an alternative Docker
  tag for early adopters who want to test pre-release builds.
- **`README.md`** — no change required (the dispatch form is an internal
  maintainer concern).

## Out of scope / deferred

- Dry-run workflow for plugin bundle validation (issue #351) — this pre-release
  channel gives us more than the dry-run did, so #351 can be closed as
  superseded.
- Automated rc → stable promotion — real releases remain manual.
- Pruning old `:unstable` images or rc GitHub Pre-releases — can be addressed
  separately if they accumulate noticeably.
