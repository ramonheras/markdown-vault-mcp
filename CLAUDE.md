# markdown-vault-mcp

Generic markdown collection MCP server with FTS5 + semantic search, frontmatter-aware indexing, and incremental reindexing.

## Design

The authoritative design specification lives at [`docs/design.md`](docs/design.md). All implementation must conform to this spec. When in doubt, the design doc wins.

## Project Structure

```
src/markdown_vault_mcp/
  scanner.py        -- file discovery, frontmatter parsing, chunking
  fts_index.py      -- SQLite FTS5 schema, BM25 search
  vector_index.py   -- numpy embeddings, cosine similarity
  providers.py      -- embedding provider ABC + implementations
  tracker.py        -- hash-based change detection
  collection.py     -- thin facade: init, lazy loading, public API
  config.py         -- configuration loading
  mcp_server.py     -- generic FastMCP server with tool annotations
  cli.py            -- CLI entry point
```

## Conventions

- Python 3.10+
- `uv` for package management, `ruff` for linting/formatting (line length 88)
- `hatchling` build backend
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Google-style docstrings on all public functions
- `logging.getLogger(__name__)` throughout, no `print()`
- Type hints everywhere
- Tests: `pytest` with fixtures in `tests/fixtures/`

## Reference

This project is extracted from [`pvliesdonk/if-craft-corpus`](https://github.com/pvliesdonk/if-craft-corpus). See the design doc's Reference Code section for the mapping between source files.

## Documentation Discipline

Every issue, PR, and code change must consider documentation impact. Before closing any issue or creating any PR, check whether the following need updating:

- **`docs/design.md`** — the authoritative spec. Any new feature, changed behavior, or architectural decision must be reflected here. If the code diverges from the spec, update the spec.
- **`README.md`** — user-facing documentation. New env vars, tools, resources, prompts, CLI flags, or configuration options must be documented here.
- **`docs/` site pages** — the published documentation site. These pages must stay in sync with the codebase:
    - `docs/tools/index.md` — new or changed MCP tools
    - `docs/resources.md` — new or changed MCP resources
    - `docs/prompts.md` — new or changed MCP prompts
    - `docs/configuration.md` — new or changed env vars
    - `docs/installation.md` — new installation methods or dependencies
    - `docs/guides/*.md` — new features that affect user workflows (e.g., new views, auth modes, deployment options)
    - `docs/index.md` — feature list and architecture overview
- **`examples/`** — example env files. New env vars or changed defaults should be reflected in relevant examples.
- **`CHANGELOG.md`** — managed by semantic-release from conventional commits, but verify entries are meaningful.
- **Inline docstrings** — new or changed public API methods need accurate docstrings.

**Rule: code without matching docs is incomplete.** When writing issues, include a "Documentation" section listing which docs need updating. When reviewing PRs, verify documentation is included. A PR that adds a tool, env var, resource, or user-facing feature without updating the corresponding docs/ page and README section should not be merged.

## Cross-Repo Sync

This repo shares domain-independent infrastructure with [`pvliesdonk/image-generation-mcp`](https://github.com/pvliesdonk/image-generation-mcp). See [`SYNC.md`](SYNC.md) for the shared file mapping, known divergences, and port history.

**Rule:** When fixing or improving shared infrastructure (auth, CI/CD, Docker entrypoint, release pipeline, packaging, CLI logging), create a corresponding issue in the other repo to port the change. Reference the source PR in the issue body. Domain-specific code (vault logic, image generation, tools, resources) does not need cross-posting.

## Key Design Decisions

- Document identity: relative path with `.md` extension
- Frontmatter: optional by default, `required_frontmatter` config to enforce
- Hybrid search: Reciprocal Rank Fusion (RRF)
- Tool semantics: mirror Claude Code Read/Write/Edit patterns
- Library is sync; MCP layer uses `asyncio.to_thread()`
- Full decision log in `docs/design.md` appendix
