# Step 6: Scholar-MCP Retrofit onto fastmcp-server-template + fastmcp-pvl-core

**Status:** Approved design, awaiting implementation plan.
**Date:** 2026-04-21
**Part of:** fastmcp-pvl-core extraction (Step 6 of 8)

## Goal

Bring `scholar-mcp` onto the same platform as MV and IG: render
`fastmcp-server-template` (v1.0.3) with scholar's answers, restore scholar's
domain code on top, rewrite `mcp_server.py` / `config.py` / `cli.py` to
compose `fastmcp-pvl-core` primitives, ship a new stable release on all six
publish targets.

Step 6 has two sequential deliverables because scholar's click-based CLI
surfaces a template-wide improvement that should land first.

## Scope

**Part A — Template v1.0.3 (argparse → typer rewrite)**

The current template ships `cli.py.jinja` with `argparse` and a single
`serve` subcommand.  Scholar's hand-built CLI uses `click` with four
subcommands (`serve`, `sync-standards`, `cache stats`, `cache clear`).
The user prefers typer/click over argparse for scholar *and* for future
copier consumers, so the template is updated upstream **before** scholar
retrofits.

Deliverable: PR on `pvliesdonk/fastmcp-server-template` that replaces
`cli.py.jinja` with a typer-based skeleton + adds `typer>=0.12` to
`pyproject.toml.jinja` dependencies.  No new surface added to
`fastmcp-pvl-core` (keeps core minimal; typer stays a direct dep of
generated projects only).

**Part B — Scholar retrofit (PR on `pvliesdonk/scholar-mcp`)**

Single rebuild PR on branch `chore/adopt-fastmcp-template`: `copier copy
--overwrite` against template v1.0.3, restore scholar's ~40-file domain
layer verbatim, rewrite `config.py` / `mcp_server.py` / `cli.py` to use
core's helpers and typer.  Target release: first stable on all six
targets (expected `v1.8.0` or later, per the PSR-bumps-from-prerelease
lesson surfaced during Step 5).

## Working repos

- `/mnt/code/scholar-mcp` — target (retrofit lands here on branch
  `chore/adopt-fastmcp-template`).
- `/mnt/code/fastmcp-server-template` — gets the typer rewrite as Part A;
  must be at tag v1.0.3 (or later) before Part B begins.
- `/mnt/code/fastmcp-pvl-core` — unchanged.  `make_serve_parser`
  (argparse helper) stays for backward compat but becomes unused by the
  template; deprecate later.
- `/tmp/scholar-replay` — scratch replay destination (throwaway).

## Out of scope

- Renaming PyPI `pvliesdonk-scholar-mcp` → `scholar-mcp`.  The short name
  is already registered elsewhere; retrofit keeps the current PyPI name.
- Promoting scholar-specific features into core: the `sync-standards`
  subcommand, the `cache` subcommand group, and the standards-sync
  exit-code semantics (0/1/3) stay in scholar's domain layer.
- Migrating MV and IG CLIs to typer via `copier update`.  Tracked as a
  separate follow-up — their next `copier update` pass will present
  typer as a diff; they can accept or skip per project cadence.
- Adding typer-based CLI helpers to `fastmcp-pvl-core`.  The existing
  `normalise_http_path` + `configure_logging_from_env` are sufficient.
- Any domain refactor beyond what the retrofit mechanically requires.

## Part A — Template v1.0.3

### Files changed

- `src/{{python_module}}/cli.py.jinja` — rewritten from argparse to typer.
  Shape (synced — NOT in `_skip_if_exists`):

  ```python
  """Command-line interface for {{ human_name }}."""

  from __future__ import annotations

  import logging

  import typer
  from fastmcp_pvl_core import configure_logging_from_env, normalise_http_path

  from {{ python_module }}.config import _ENV_PREFIX

  logger = logging.getLogger(__name__)

  app = typer.Typer(
      name="{{ project_name }}",
      help="{{ domain_description }}",
      no_args_is_help=True,
      add_completion=False,
  )


  @app.callback()
  def _root(
      verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable debug logging."),
  ) -> None:
      configure_logging_from_env(verbose=verbose)


  @app.command()
  def serve(
      transport: str = typer.Option("stdio", help="MCP transport (stdio / http / sse)."),
      host: str = typer.Option("0.0.0.0", help="Bind host (http only)."),
      port: int = typer.Option(8000, help="Bind port (http only)."),
      http_path: str | None = typer.Option(
          None, "--http-path", "--path",
          help=f"Mount path (http only, default: ${_ENV_PREFIX}_HTTP_PATH or /mcp).",
      ),
  ) -> None:
      """Run the MCP server."""
      import os

      from {{ python_module }}.mcp_server import build_event_store, create_server

      server = create_server(transport=transport)
      if transport == "http":
          import uvicorn

          path = normalise_http_path(http_path or os.environ.get(f"{_ENV_PREFIX}_HTTP_PATH"))
          uvicorn.run(
              server.http_app(path=path, event_store=build_event_store()),
              host=host, port=port,
          )
      else:
          server.run(transport=transport)


  def main() -> None:
      app()


  if __name__ == "__main__":
      main()
  ```

- `pyproject.toml.jinja` — add `"typer>=0.12"` to `[project].dependencies`.

- `tests/test_smoke.py.jinja` — if the current smoke test imports
  `cli._normalise_http_path` or calls `parser.parse_args`, update to use
  `typer.testing.CliRunner`.  Confirm during implementation.

### Design rationale

- **`app.callback()` owns `configure_logging_from_env`**: every subcommand
  inherits the verbose flag.  Avoids duplicating logging bootstrap in each
  command.
- **`--http-path` + `--path` alias**: preserves backward compat with
  existing shell scripts and docs that use `--path`.
- **`no_args_is_help=True`**: calling `project-name` with no subcommand
  prints help instead of erroring.
- **typer is a direct dep of generated projects, not of core**: keeps
  core's public surface minimal.  Projects that don't want typer can
  vendor their own CLI; the template doesn't force the dep on them past
  first render (but `pyproject.toml` is NOT in `_skip_if_exists`, so a
  copier update would re-add it; projects who rip out typer must also
  remove the dep manually each update cycle).

### Release

Merge → PSR cuts `v1.0.3` (or whatever patch number lands) on the
template repo.  Part B starts only after v1.0.3 is tagged.

## Part B — Scholar retrofit

### Scholar's copier answers

| Variable | Value |
| -------- | ----- |
| `project_name`        | `scholar-mcp` |
| `pypi_name`           | `pvliesdonk-scholar-mcp` |
| `python_module`       | `scholar_mcp` |
| `env_prefix`          | `SCHOLAR_MCP` |
| `human_name`          | `Scholar MCP` |
| `domain_description`  | `FastMCP server for Semantic Scholar with OpenAlex enrichment and docling PDF conversion` |
| `github_org`          | `pvliesdonk` |
| `docker_registry`     | `ghcr.io/pvliesdonk` |

Stored as `.copier-answers.yml` after retrofit; `_commit: v1.0.3`.

### Phase 1: Replay + triage

Standard 5-class diff triage against `/tmp/scholar-replay`.  Expected
counts (estimate): ~120 entries, 0 Class D, 40-50 Class A, handful of
Class B (template infra scholar lacks), ~30 Class C (hybrids), residual
Class E.

Known **Class E acceptable divergences** to document up front:
- `coverage-status.yml` workflow — scholar-specific infra not shipped by
  template.  Keep.
- `coverage.json` / `coverage.xml` at repo root — local test-run
  artifacts that shouldn't be committed.  Remove as part of retrofit.

Iterate template patches only if Class D surfaces.  None expected given
Step 5's clean run.

### Phase 2: Rebuild retrofit

**Class A (preserve verbatim — ~40 files):**
- All 8 API clients: `_crossref_client.py`, `_docling_client.py`,
  `_epo_client.py`, `_google_books_client.py`, `_openalex_client.py`,
  `_openlibrary_client.py`, `_s2_client.py`, `_standards_client.py`
- All 5 enrichers: `_enricher_{crossref,google_books,openalex,openlibrary,standards}.py`
- Standards sync subsystem: `_standards_sync.py`, `_sync_cc.py`,
  `_sync_cen.py`, `_sync_relaton.py`, `_relaton_live.py`,
  `_book_enrichment.py`
- 10 tool-split files: `_tools_{books,citation,graph,patent,pdf,recommendations,search,standards,tasks,utility}.py`
- Utilities: `_cache.py`, `_chapter_parser.py`, `_citation_formatter.py`,
  `_citation_names.py`, `_enrichment.py`, `_epo_xml.py`,
  `_patent_numbers.py`, `_pdf_url_resolver.py`, `_protocols.py`,
  `_rate_limiter.py`, `_record_types.py`, `_task_queue.py`
- Registration modules: `_server_{deps,tools,resources,prompts}.py`
- `tests/`, `docs/`, `examples/` — domain.

**Class C rewrites:**

1. **`config.py` (~90 → ~130 lines)** — compose `ServerConfig`, rename
   any local `ServerConfig` class to `ProjectConfig` (matching IG's
   pattern).  Add `server: ServerConfig = field(default_factory=ServerConfig)`.
   Keep all scholar domain fields (cache_dir, github_token, s2_api_key,
   OpenAlex contact email, docling config, etc.) wrapped in
   `CONFIG-FIELDS-START/END` and `CONFIG-FROM-ENV-START/END` sentinel
   blocks.
2. **`mcp_server.py` (~475 → ~200 lines)** — drop local auth helpers
   (`_build_bearer_auth`, `_build_oidc_auth`, etc. if present) and
   local `build_event_store`.  Compose `build_auth`,
   `wire_middleware_stack`, `build_instructions`,
   `configure_logging_from_env`, `resolve_auth_mode`, `build_event_store`
   from `fastmcp_pvl_core`.  Preserve scholar-specific wiring:
   task-queue initialization, cache lifecycle hooks, any per-project
   server identity.  Keep `create_server = make_server` alias for test
   backward compat.
3. **`cli.py` (~327 → ~200 lines)** — rewrite click → typer.  Four
   subcommands preserved:

   ```python
   app = typer.Typer(name="scholar-mcp", help=..., no_args_is_help=True, add_completion=False)
   cache_app = typer.Typer(name="cache", help="Manage the Scholar MCP local cache.")
   app.add_typer(cache_app, name="cache")

   @app.callback()
   def _root(verbose: bool = ...) -> None:
       configure_logging_from_env(verbose=verbose)

   @app.command()
   def serve(transport, host, port, http_path) -> None: ...

   @app.command("sync-standards")
   def sync_standards(body: str = ..., force: bool = ..., cache_dir: Path | None = ...) -> None: ...

   @cache_app.command("stats")
   def cache_stats(cache_dir: Path | None = None) -> None: ...

   @cache_app.command("clear")
   def cache_clear(older_than: int | None = None, cache_dir: Path | None = None) -> None: ...
   ```

   Behavioural contract preserved:
   - `sync-standards` exit codes 0 / 1 / 3 via explicit `raise typer.Exit(code=N)`.
   - `--body` case-insensitive: either use `Enum` or normalize to upper
     before dispatch.
   - Async bodies wrapped in `asyncio.run(_run())` as today — typer is
     sync-only, no change needed.

4. **`pyproject.toml`** — add `fastmcp-pvl-core>=1.0,<2`, add
   `typer>=0.12`, drop `click>=8.0` (typer pulls click transitively),
   keep `httpx` (direct use in API clients), keep `aiosqlite`, keep
   `python-epo-ops-client`, keep `lxml`, keep `beautifulsoup4`.  Also
   adopt PSR `build_command = "python scripts/bump_manifests.py"` +
   `assets = ["server.json"]` so server.json auto-bumps (the Step 5
   lesson, now in template v1.0.2+).

**Deleted template scaffolds** (scholar uses `_server_*.py` with
underscore prefix):
- `src/scholar_mcp/{server,domain,tools,resources,prompts}.py`
- `tests/test_smoke.py`, `tests/test_tools.py` (scholar has richer tests)

**Deleted repo cruft** (Class E cleanup):
- `coverage.json`, `coverage.xml` at repo root.
- Ensure they're in `.gitignore`.

### Gate

```
uv sync --all-extras --dev
uv run ruff check --fix .
uv run ruff format .
uv run ruff format --check .
uv run mypy src/
uv run pytest -x -q
```

Expect 2-4 iterations fixing typer param coercion differences from click.

### Release

`v1.8.0` (or higher) stable across all six targets: PyPI, GHCR, MCP
Registry, Linux packages, GitHub release, MCPB.  Trigger pattern:
`force=minor` + `prerelease=true` for rc, then `force=minor` +
`prerelease=false` for stable (per the lesson from Step 5 — PSR bumps
from the highest existing prerelease, so even with `force=minor` on
stable the version will be higher than 1.7.x).

## Success criteria

1. **Template PR merged**, `v1.0.3` cut.  Rendered output uses typer
   with `serve` subcommand; `typer>=0.12` in deps.
2. Scholar replay diff (template v1.0.3 vs scholar main) contains only
   Class A / C / E entries.  Class D = 0.
3. `/mnt/code/scholar-mcp/.copier-answers.yml` exists, pins template
   `v1.0.3`, committed on main.
4. Scholar retrofit commit passes full gate: `uv run pytest -x -q`,
   `ruff check`, `ruff format --check`, `mypy src/`.
5. `fastmcp-pvl-core` used in scholar's `make_server()`; grep audit
   confirms no duplicate auth / middleware / logging / event-store code
   left in `scholar_mcp/`.
6. `mcp_server.py` ≤ ~220 lines (from 475).
7. `cli.py` is typer-based with all four subcommands functional:
   `scholar-mcp serve`, `scholar-mcp sync-standards`, `scholar-mcp
   cache stats`, `scholar-mcp cache clear`.
8. rc smoke green (Docker + MCPB).
9. Stable release green on all six publish targets (PyPI + GHCR +
   MCP Registry + Linux + GH release + MCPB).
10. `fastmcp_pvl_core_extraction_handoff.md` memory updated: Step 6
    DONE, next step named (Step 7 — kroki-mcp).

## Risks

- **Click → typer behavioural gaps.** `click.Choice(..., case_sensitive=False)`
  has no direct typer analog.  Scholar's `sync-standards --body` uses a
  6-value Choice.  Mitigation: normalize (`body = body.upper()`) before
  dispatch, or use a `StrEnum`.  Called out in implementation plan.

- **Exit codes.** Scholar's `sync-standards` returns 0 / 1 / 3 for
  success / hard-fail / partial.  typer defaults to `sys.exit(0)` on
  return.  Preserve via explicit `raise typer.Exit(code=N)`.

- **async-in-CLI pattern preserved.** Each async command wraps
  `asyncio.run(_run())`.  typer doesn't know about async; the
  sync-wrapper stays.  Low risk, just mechanical.

- **sync-standards must stay server-start-independent.** The subcommand
  is a long-running pre-populate task; `make_server()` must NOT invoke
  `_standards_sync` at server boot.  Check during `mcp_server.py`
  rewrite that no startup lifespan hook reaches into sync code.

- **Test suite size.** Scholar has a substantial test suite; retrofit
  iteration on import / rename fixes may span 2-4 cycles.  Budget time
  for gate loops.

- **Version jump.** PSR will bump from the highest existing tag,
  including prereleases (`v1.7.0-rc.2`).  `force=minor` + `prerelease=false`
  will land `v1.8.0` (or higher), NOT `v1.6.0` or `v1.7.0`.  Accept
  whatever number lands.

- **Cascade to MV / IG.** Once template v1.0.3 ships, MV and IG will
  show typer-based `cli.py` as a diff on next `copier update`.  They
  can accept (adopt typer) or skip (keep argparse).  Not blocking Step
  6; tracked as follow-up.
