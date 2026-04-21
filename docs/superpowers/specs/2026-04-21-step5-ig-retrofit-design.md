# Step 5: IG Retrofit onto fastmcp-server-template + fastmcp-pvl-core

**Status:** Approved design, awaiting implementation plan.
**Date:** 2026-04-21
**Part of:** fastmcp-pvl-core extraction (Step 5 of 8)

## Goal

Bring `image-generation-mcp` (IG) onto the same platform as MV: render
`fastmcp-server-template` v1.0.0 with IG's answers, restore IG's domain code
on top, rewrite `mcp_server.py` as a `make_server()` composing
`fastmcp-pvl-core` primitives, ship a new stable release with all six publish
targets.

This is the first time the template+core combination is applied to a project
that does **not** already depend on `fastmcp-pvl-core`. MV (Step 4) already
ate core in v1.25.0 (PRs #396–#403); IG hasn't. So Step 5 covers two retrofits
in one PR: code adoption (mcp_server/config/cli use core) AND infra adoption
(template-driven workflows/Dockerfile/packaging/CHANGELOG/etc.).

## Approach

**Single-PR rebuild.** Per user decision (2026-04-21): start from the freshly
rendered template (the new base) and re-add IG's domain layer (tools,
prompts, resources, providers, transforms) on top. Easier to reason about
than refactoring IG's current code in place — no half-state on main.

The reorganization happens implicitly: 400+ lines of auth/instructions/
event-store boilerplate vanish from `mcp_server.py` (→ core imports), so the
file naturally shrinks from 533 → ~150 lines without a separate refactor.

Out of scope: Steps 6–8 (scholar-mcp, kroki-mcp, SYNC.md retire). Promoting
IG-specific features (`ResourcesAsTools`, long-op keepalives, `HTTP_PATH`)
into core — they stay in IG's domain layer per Step 4 handoff.

## Working repos

- `/mnt/code/image-gen-mcp` — target (IG retrofit lands here on branch `chore/adopt-fastmcp-template`).
- `/mnt/code/fastmcp-server-template` — template source (already at tag v1.0.0; no patches expected).
- `/mnt/code/fastmcp-pvl-core` — library reference (read-only; no patches expected).
- `/tmp/ig-replay` — scratch replay destination (throwaway).

## IG's copier answers

Used for both the replay render and the retrofit.

| Variable | Value |
| -------- | ----- |
| `project_name` | `image-generation-mcp` |
| `pypi_name` | `image-generation-mcp` |
| `python_module` | `image_generation_mcp` |
| `env_prefix` | `IMAGE_GENERATION_MCP` |
| `human_name` | `Image Generation MCP` |
| `domain_description` | `MCP server for AI image generation via OpenAI, Google GenAI, or Stable Diffusion WebUI` |
| `github_org` | `pvliesdonk` |
| `docker_registry` | `ghcr.io/pvliesdonk` |

Stored as `.copier-answers.yml` in IG after retrofit; future `copier update`
runs are non-interactive.

## Phase 1: Replay + diff classification

Same procedure as Step 4 §"Phase 1": render template into `/tmp/ig-replay`,
diff against `/mnt/code/image-gen-mcp`, classify every entry into one of
five classes (A=domain, B=adopt template version, C=hybrid, D=template bug,
E=acceptable divergence). Iterate template patches if any Class D items
surface; aim for diff = Class A/C/E only.

**Expected differences from Step 4 triage:**

- More Class B items than MV's 4. IG is far behind on infra (still on
  `actions/checkout@v4`, `astral-sh/setup-uv@v4`, no `prerelease` workflow
  input, no `prerelease_token: rc`). Template's release.yml is the canonical
  shape and IG should adopt it wholesale.
- IG lacks `_server_apps.py` (no MCP Apps SPA). Template ships an inert
  scaffold; IG accepts it (Class B) and can implement later if desired.
- IG has artifacts under `node_modules/`, `site/`, `package.json`,
  `package-lock.json` (Pillow + asset processing pipeline). All Class A
  domain.
- `_vendored_sdk.py` and `TEMPLATE.md` are IG-specific; verify the
  template's `_exclude` list doesn't strip them.

## Phase 2: Retrofit to IG

Same procedure as Step 4 §"Phase 2", with extra rewrites because IG isn't
on core yet.

### Class C hybrids — restore from `step5-pre-retrofit` tag

Mirroring the Step 4 hot-list, adapted for IG:

- `pyproject.toml` — preserve IG's domain dependencies (`httpx`, `Pillow`,
  optional `[openai]`/`[google-genai]`/`[mcp]`/`[all]` extras), ruff
  per-file overrides, mypy overrides, PSR `assets` list pointing at IG's
  files. **Add** `fastmcp-pvl-core>=1.0,<2` as a new core dep.
- `CLAUDE.md` — preserve IG's project-specific section between sentinel
  blocks; template-owned outer prose updates from template.
- `config.py` — **rewrite, do not just restore**. New shape:
  - `ProjectConfig` dataclass holding `server: ServerConfig` + IG domain fields
    (provider configs, artifact TTL, asset paths, etc.).
  - Drop hand-rolled auth/OIDC fields that move into `ServerConfig`.
  - Drop hand-rolled `_env`/`_parse_*` helpers; import from core.
- `server.json` — IG-specific env vars added back to PyPI + OCI packages
  (likely `IMAGE_GENERATION_MCP_*` for provider keys, asset dir, etc.).
  Full restore from `step5-pre-retrofit`.
- `README.md` — full restore (IG's badges, install, usage docs).
- `mcp_server.py` — **rewrite, do not just restore**. New shape:
  - Becomes `server.py` per template convention OR stays as `mcp_server.py`
    if IG's tests reference that name (decide based on test grep).
  - `make_server()` ~150 lines: `auth = build_auth(config.server)`,
    `wire_middleware_stack(mcp)`, `build_instructions(...)`,
    `build_event_store(...)`, then `register_tools(mcp)`,
    `register_resources(mcp)`, `register_prompts(mcp)`, IG-specific
    `ResourcesAsTools` wrap if applicable.
  - Drop all of: `_build_bearer_auth`, `_resolve_auth_mode`,
    `_build_remote_auth`, `_build_oidc_auth`, `_build_default_instructions`,
    `build_event_store` (all → core).
- `cli.py` — adopt `configure_logging_from_env` and `normalise_http_path`
  from core (mirrors MV PR #401, PR #398).
- `artifacts.py` — if IG's shape matches MV's eager-bytes pattern, replace
  with thin re-export of core `ArtifactStore`. Else keep a thin wrapper
  (decide during retrofit by reading IG's current artifacts.py).
- `_server_tools.py`, `_server_resources.py`, `_server_prompts.py` —
  domain. Restore from `step5-pre-retrofit` (template's are starter stubs).
- `_server_deps.py` — likely restore from pre-retrofit; IG's lifespan wires
  the IG `Service` (image-gen pipeline) which is domain.
- Workflows (`ci.yml`, `release.yml`, `claude-code-review.yml`,
  `claude.yml`, `codeql.yml`, `docs.yml`) — accept template versions
  (Class B → these are the infra refresh).
- Dockerfile, docker-entrypoint.sh, compose.yml, packaging/ — accept
  template versions where IG had stale variants; keep IG-specific
  customizations only where domain-justified.

### Class A — preserve verbatim

- `src/image_generation_mcp/providers/{capabilities,gemini,openai,placeholder,sd_webui,selector,types}.py`
- `src/image_generation_mcp/_vendored_sdk.py`
- `src/image_generation_mcp/processing.py`
- `src/image_generation_mcp/service.py`
- `src/image_generation_mcp/styles.py`
- `src/image_generation_mcp/_http_logging.py`
- `tests/test_*.py` (all domain tests)
- `examples/` (IG-specific env files)
- `docs/` (IG's MkDocs site)
- `node_modules/`, `site/`, `package.json`, `package-lock.json` (asset
  pipeline; copier shouldn't touch these)
- `TEMPLATE.md` (IG-specific historical artifact; classify Class E if it
  remains, decide whether to delete)

### Gate

After all restores + rewrites:

```
uv sync --all-extras --dev
uv run ruff check --fix .
uv run ruff format .
uv run ruff format --check .
uv run mypy src/
uv run pytest -x -q
```

All must pass before commit. Iterate restoration → gate → fix until green.

### Commit + PR

Single commit on branch `chore/adopt-fastmcp-template`, message:

```
chore: adopt fastmcp-server-template v1.0.0 + fastmcp-pvl-core

[Body summarizing: template adoption, core adoption,
 mcp_server rewrite to make_server(), config restructure,
 IG-specific features preserved (ResourcesAsTools, keepalives, etc.).]
```

PR opens, CI must be green, merge via `gh pr merge --merge`.

## Phase 3: Release pipeline validation

Same shape as Step 4 §"Phase 3", adapted for IG's current version (1.5.0):

### Phase 3a — Prerelease (`v1.6.0-rc.1`)

- Trigger `release.yml` with `force=minor` + `prerelease=true`.
- PSR cuts `v1.6.0-rc.1`. PyPI / MCP Registry / Linux packages /
  Claude Plugin PR all skipped (rc-gated).
- Verify: tag, GH release marked prerelease, Docker multi-arch, MCPB
  attached, server.json bumped, CHANGELOG entry.
- Smoke: `docker run … markdown-vault-mcp serve --transport http` against
  a throwaway image gen request (or just verify server starts).

### Phase 3b — Stable (`v1.6.0`)

**Trigger with NO `force` flag** + `prerelease=false`. PSR drops the rc
suffix to land on `v1.6.0` exactly (avoids the v1.27.0-on-MV mistake from
Step 4 — see `feedback_psr_promote_rc_no_force.md`).

Verify all six targets: PyPI, GHCR multi-arch, MCP Registry, Linux .deb +
.rpm, GH release, MCPB.

### Rollback

- 3a failure: fix forward with rc.2; rc is throwaway.
- 3b failure: file follow-up issue but don't block Step 5 closure (per
  Step 4 spec rollback stance).

## Success criteria

Step 5 is complete when **all** of these hold:

1. Replay diff contains only Class A/C/E entries (no Class D template bugs,
   or all Class D items closed via template patch releases).
2. `/mnt/code/image-gen-mcp/.copier-answers.yml` exists, pins template
   `v1.0.0`, committed on main.
3. Retrofit commit passes full gate: `uv run pytest -x -q`,
   `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src/`.
4. `fastmcp-pvl-core` imported and used in `make_server()` — grep audit
   confirms no duplicate auth/middleware/logging/event-store code left in
   `image_generation_mcp/`.
5. `mcp_server.py` (or `server.py`) is ≤ ~200 lines and consists of
   `make_server()` + IG-specific transforms only.
6. `v1.6.0-rc.1` rc smoke passed (Docker + MCPB).
7. `v1.6.0` stable shipped to all six publish targets.
8. `fastmcp_pvl_core_extraction_handoff.md` memory updated: Step 5 DONE,
   next step named (Step 6 — scholar-mcp).

## Non-goals

- Migrating scholar-mcp or kroki-mcp (Steps 6–7).
- Retiring `SYNC.md` (Step 8).
- Promoting IG-specific features (`ResourcesAsTools`, long-op keepalives,
  HTTP_PATH) into core — they stay in IG's domain layer for now.
- Adding new image-gen features.
- Refactoring IG's provider implementations.

## Risks

- **Larger code rewrite than MV retrofit.** MV Step 4 was 8 files / 306
  insertions. Step 5 includes a full `mcp_server.py` rewrite + `config.py`
  restructure on top of the template adoption. Higher chance of latent
  test breakage. Mitigation: run IG's test suite frequently during the
  rebuild; restore from `step5-pre-retrofit` aggressively if anything
  surprises.
- **More Class B items than Step 4.** IG is far behind on infra; the diff
  triage will be longer (budget 2–3 hours).
- **`ResourcesAsTools` wrapping.** IG uses `fastmcp.server.transforms.
  ResourcesAsTools` to expose resources as tools for clients that don't
  list resources. The template's `make_server()` shape doesn't show this
  wrapping; IG's `make_server` diverges by calling `ResourcesAsTools(mcp)`
  before returning. Verify the wrap order doesn't break middleware.
- **Vendored SDK / asset pipeline survival.** `_vendored_sdk.py`,
  `node_modules/`, `package.json`, `site/` must survive `copier copy
  --overwrite`. Verify by inspecting `git status` after the render and
  before any restoration.
- **Test/docstring drift.** IG's tests likely import `create_server` (the
  current name); rewrite renames it to `make_server`. Either keep the old
  name as an alias temporarily, or update test imports during the
  retrofit.
