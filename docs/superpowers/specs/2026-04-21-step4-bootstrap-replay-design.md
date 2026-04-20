# Step 4: Bootstrap-Replay Validation of fastmcp-server-template v1.0.0

**Status:** Approved design, awaiting implementation plan.
**Date:** 2026-04-21
**Part of:** fastmcp-pvl-core extraction (Step 4 of 8)

## Goal

Validate that `fastmcp-server-template` v1.0.0 can reproduce the structure of
`markdown-vault-mcp` v1.25.0, then retrofit MV to actually adopt the template
(generate `.copier-answers.yml`, commit), then prove the release pipeline still
works end-to-end.

This is the first time the template is tested against a real-world project.
Every divergence found is either a template bug (fix in template, patch
release) or an explicit acceptable-divergence decision (documented).

## Scope

Three phases, executed in order:

1. **Replay** — `copier copy` into a throwaway dir with MV's answers, diff
   against real MV, classify every diff, iterate template patches until the
   only remaining diffs are domain-only.
2. **Retrofit** — `copier copy --overwrite --trust` against
   `/mnt/code/markdown-mcp`, restore C-class domain content in hybrid files,
   run the gate, commit as `chore: adopt fastmcp-server-template v1.0.x`.
3. **Release pipeline validation** — cut `v1.26.0-rc.1` (Docker+MCPB smoke),
   promote to `v1.26.0` stable (all six publish targets).

Out of scope: migrating IG/scholar/kroki (Steps 5-7), retiring SYNC.md
(Step 8).

## MV's copier answers

Used for both the replay render and the retrofit:

| Variable              | Value                                    |
| --------------------- | ---------------------------------------- |
| `project_name`        | `markdown-vault-mcp`                     |
| `pypi_name`           | `markdown-vault-mcp`                     |
| `python_module`       | `markdown_vault_mcp`                     |
| `env_prefix`          | `MARKDOWN_VAULT_MCP`                     |
| `human_name`          | `Markdown Vault MCP`                     |
| `domain_description`  | `Generic markdown collection MCP server with FTS5 + semantic search` |
| `github_org`          | `pvliesdonk`                             |
| `docker_registry`     | `ghcr.io/pvliesdonk`                     |

Stored as `.copier-answers.yml` in MV after retrofit, so future
`copier update` runs are non-interactive.

## Phase 1: Replay + diff classification

### Procedure

1. `mkdir -p /tmp/mv-replay && cd /tmp/mv-replay`
2. `copier copy --trust --data-file <answers.yml> /mnt/code/fastmcp-server-template .`
3. `diff -r /tmp/mv-replay /mnt/code/markdown-mcp` (excluding `.git`, `.venv`,
   `node_modules`, `__pycache__`, `.copier-answers.yml`, coverage artifacts,
   vendored SPA output)
4. Classify every diff into one of five classes below.
5. For every Class B/D/E item: patch the template, tag `v1.0.x`, re-render,
   re-diff. Iterate until only Class A and explicitly-approved Class C remain.

### Diff taxonomy

- **Class A — Domain content** (expected, no action): files that exist only
  in MV because they implement vault-specific functionality. Examples:
  `src/markdown_vault_mcp/collection.py`, `fts_index.py`, `vector_index.py`,
  `managers/`, `scanner.py`, `providers.py`, `tracker.py`, domain tests,
  docs site pages, MCP Apps SPA, `docs/design.md`.

- **Class B — Infra bug in MV** (rare, fix MV to match template): MV has
  infra that the template got right but MV is stale on. Example: MV still
  references a deleted helper that the template correctly omits. Fix in MV as
  part of the retrofit.

- **Class C — Hybrid file, domain content preserved** (expected): files the
  template produces as starter stubs with domain sentinel blocks; MV's real
  version has real content between the sentinels. Manually preserved during
  retrofit. Canonical list:
  - `pyproject.toml` — PROJECT-DEPS-START/END, PROJECT-EXTRAS-START/END
  - `src/markdown_vault_mcp/config.py` — CONFIG-FIELDS-START/END,
    CONFIG-FROM-ENV-START/END
  - `CLAUDE.md` — DOMAIN-START/END
  - `README.md` — starter template; MV's is full docs site entry
  - `src/markdown_vault_mcp/tools.py`, `resources.py`, `prompts.py` —
    template produces stubs, MV has full registrations
  - `server.json` — PyPI+OCI env vars extend the template defaults
  - `docs/` — template produces skeleton, MV has full MkDocs site

- **Class D — Infra bug in template** (fix in template, v1.0.x patch):
  the template should have produced X but didn't, and MV's X is correct.
  Each patch gets tagged separately; MV's `.copier-answers.yml` is pinned
  to the latest after retrofit.

- **Class E — Acceptable divergence** (document and move on): something MV
  does that the template intentionally does not, or vice versa. Each
  E-class item needs a one-line rationale in the Step 4 retrospective.

### Expected C-class hotspots

Based on spec-writing analysis, these files are known hybrid zones to
inspect carefully during retrofit:

- `src/markdown_vault_mcp/config.py` — MV's keeps auth helper wrappers
  (`build_bearer_auth`, `build_oidc_auth`, `build_remote_auth`,
  `resolve_auth_mode`) that delegate to core. Test suite locks these in.
  Treat as **domain** — restore MV's version inside the sentinel blocks.
- `src/markdown_vault_mcp/mcp_server.py` — template's `make_server()` is
  generic; MV's has ~200 lines of vault-specific tool/resource/prompt
  wiring, SPA registration, read_only gating. Treat as **domain**.
- `src/markdown_vault_mcp/cli.py` — template is a standard CLI; MV's uses
  `configure_logging_from_env` + `normalise_http_path` from core. Likely
  template-compatible after adoption. Inspect diff carefully.
- `pyproject.toml` — dependencies, extras, ruff overrides. Preserve MV's
  between sentinels.
- `CLAUDE.md` — MV has a very long project-specific CLAUDE.md. Preserve
  between DOMAIN sentinels.
- `Dockerfile` — MV has entrypoint + gosu + PUID/PGID. Template should
  produce the same shape; any diff is probably a D-class template bug.

### Strictness bar

"Diff is domain-only" means: every remaining diff after template patches
is either Class A (clearly domain) or Class C (hybrid file where the
non-template portion is domain). Any infra diff without one of those
labels is a template bug to fix before closing Phase 1.

### Template versioning during iteration

When Phase 1 finds a template bug, cut a new patch release (`v1.0.1`,
`v1.0.2`, etc.) — do not retag `v1.0.0`. MV's `.copier-answers.yml` pins
the final version reached. This keeps the template's tag history clean
and lets other projects adopt a known version.

## Phase 2: Retrofit to MV

### Procedure

1. In `/mnt/code/markdown-mcp`, create branch `chore/adopt-fastmcp-template`.
2. Run `copier copy --overwrite --trust --data-file <answers.yml> \
   /mnt/code/fastmcp-server-template .`
3. For each Class C hotspot above, restore MV's domain content between
   sentinel blocks. Use `git diff` to inspect what copier overwrote.
4. For each Class B fix identified in Phase 1, apply inline.
5. Run the gate: `uv run pytest -x -q && uv run ruff check --fix . && \
   uv run ruff format . && uv run ruff format --check . && \
   uv run mypy src/`
6. Commit: `chore: adopt fastmcp-server-template v1.0.x`
7. Open PR, merge when green.

### Rollback

If the retrofit PR reveals the template needs more work, close the PR
without merging, fix the template (new patch release), and restart from
step 1. The branch is disposable.

## Phase 3: Release pipeline validation

### Phase 3a — Prerelease smoke test (`v1.26.0-rc.1`)

1. Trigger `release.yml` with `prerelease: true`, `prerelease_token: rc`.
2. PSR cuts `v1.26.0-rc.1`. MV's PSR config gates PyPI on prereleases —
   expect Docker + MCPB only.
3. Verify:
   - Docker image `ghcr.io/pvliesdonk/markdown-vault-mcp:v1.26.0-rc.1`
     builds multi-arch (linux/amd64, linux/arm64).
   - MCPB artifact attached to the GitHub release.
   - `server.json` version bumped to `1.26.0-rc.1`.
   - CHANGELOG entry generated.
   - Tag points at a single commit carrying all version-coupled files.
4. Pull the rc image, run against a throwaway vault, confirm stdio +
   HTTP transports start and `list_documents` responds.

### Phase 3b — Stable promotion (`v1.26.0`)

1. If 3a green, trigger `release.yml` without the prerelease flag.
2. PSR cuts `v1.26.0`. Expect all six publish targets:
   - PyPI (`markdown-vault-mcp==1.26.0`)
   - GHCR (`ghcr.io/pvliesdonk/markdown-vault-mcp:v1.26.0`)
   - MCP Registry (`io.github.pvliesdonk/markdown-vault-mcp@1.26.0`)
   - Linux packages (`.deb` / `.rpm` on the GitHub release)
   - GitHub release with CHANGELOG
   - MCPB artifact attached

### Rollback stance

- **3a failure:** rc is throwaway. Fix forward with `rc.2`. Don't revert.
- **3b failure after 3a green:** release-workflow bug, not a template
  bug. Investigate but don't block Step 4 closure on it; file as a
  post-step follow-up issue.

## Success criteria

Step 4 is complete when **all** of these are true:

1. Replay diff of template vs. real MV contains only Class A and
   approved Class C items. Every infra diff was either fixed via
   template patch release or documented as Class E with rationale.
2. `/mnt/code/markdown-mcp/.copier-answers.yml` exists, pins the final
   template version, and is committed on main under
   `chore: adopt fastmcp-server-template v1.0.x`.
3. Retrofit commit passes full gate: `uv run pytest -x -q`,
   `uv run ruff check`, `uv run ruff format --check`,
   `uv run mypy src/`.
4. `v1.26.0-rc.1` prerelease smoke test passed (Docker + MCPB).
5. `v1.26.0` stable shipped to all six publish targets (PyPI, GHCR,
   MCP Registry, Linux packages, GitHub release, MCPB).
6. `fastmcp_pvl_core_extraction_handoff.md` memory updated: Step 4 DONE,
   next step named (Step 5: migrate image-generation-mcp onto copier
   scaffold).

## Non-goals

- Migrating image-generation-mcp, scholar-mcp, or kroki-mcp (Steps 5-7).
- Retiring `SYNC.md` (Step 8).
- Adding new features to MV.
- Refactoring domain code during the retrofit (stay focused; anything
  non-retrofit is a separate PR).

## Risks

- **Hybrid sentinel blocks miss content.** If copier overwrites a file
  whose real domain content isn't wrapped in sentinels, we lose it
  silently. Mitigation: inspect every overwritten file via `git diff`
  before committing; the retrofit is on a branch, not main.
- **Template patches cascade.** One template bug may mask another. Plan
  for 2-3 Phase 1 iterations, not 1.
- **Release pipeline flake.** 3b touches PyPI, which is irreversible.
  Only promote to stable after 3a is fully green.
