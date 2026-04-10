# Claude Desktop + Claude Code Plugin Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `markdown-vault-mcp` through two new first-party plugin channels — a Claude Desktop `.mcpb` bundle and a Claude Code marketplace plugin — fully automated from the existing release pipeline.

**Architecture:** Package source lives inside the `markdown-vault-mcp` repo under `packaging/mcpb/` (bundle templates) and `.claude-plugin/plugin/` (Claude Code plugin source). A new `pvliesdonk/claude-plugins` catalog repo hosts the marketplace manifest and references the plugin via `git-subdir` at a pinned tag. Three new CI jobs in `release.yml` build the `.mcpb`, attach it to the GitHub Release, and open a bump-PR against the catalog repo. All version strings (`server.json`, `plugin.json`, `.mcp.json`) are bumped in lockstep by the existing `release` job.

**Tech Stack:** `@anthropic-ai/mcpb` CLI, `envsubst`, `jq`, `uv` / `uvx`, `peter-evans/create-pull-request@v7`, existing `python-semantic-release` v10 setup.

**Spec:** `docs/superpowers/specs/2026-04-10-claude-plugins-design.md` (commit `d824ee4`). Section references (§N) in this plan point at that spec.

## Risk verification results (2026-04-10)

- `manifest_version 0.4` + `server.type: "uv"`: **supported** — documented in the authoritative MANIFEST.md spec under "UV Runtime (v0.4+)"; spec current version is 0.3 for stable, but `uv` type explicitly requires `manifest_version: "0.4"` and is documented as a production feature (not experimental).
- Minimum Claude Desktop version for mcpb v0.4: **`>=0.10.0`** — the MANIFEST.md spec uses `"claude_desktop": ">=0.10.0"` in all its canonical examples for Python, Node.js, and binary extension types. No newer minimum is documented for the `uv` type specifically.
- mcpb CLI version installed: **2.1.2** (installed via `npm install --prefix /tmp/mcpb-install @anthropic-ai/mcpb@latest`)
- `mcpb validate` with `server.type: "uv"`: **passed** — validation passes when `mcp_config` is included. Note: `mcp_config` is required by the validator even for `uv` type (the spec says "optional" but the CLI enforces it). Pack produces a 3-file archive: `manifest.json`, `pyproject.toml`, `src/server.py` — no `server/lib/` or `server/venv/`.
- Claude Code `${VAR:-default}` in .mcp.json: **supported** — Claude Code docs explicitly document both `${VAR}` and `${VAR:-default}` as supported expansion syntax in `.mcp.json` env blocks (source: https://code.claude.com/docs/en/mcp.md, "Environment variable expansion in `.mcp.json`" section). Expansion works in `command`, `args`, `env` values, and `url` fields.
- Fallback taken: **one adjustment** — `mcp_config` must be present in the manifest even for `server.type: "uv"` (the spec says optional but `mcpb validate` v2.1.2 rejects manifests without it). The manifest template in Task 4 must include `mcp_config` with `"command": "uv"` and `"args": ["run", ...]`.

---

## Prerequisites and context for the implementing engineer

- The repo uses **`uv`** for everything: `uv run pytest`, `uv run ruff check`, `uv run mypy src/`. Do not invoke `pip` or `pytest` directly.
- CLAUDE.md defines **Hard PR Acceptance Gates**: `pytest -x -q` green, `ruff check --fix` then `ruff format` then `ruff format --check`, `mypy src/` clean, patch coverage ≥ 80% via local `diff-cover`, and docs updated in the same commit as user-facing changes. Every commit in this plan must leave the tree in a state where those gates would pass.
- Tests live in `tests/`; fixtures in `tests/fixtures/`; `asyncio_mode = "auto"` is set so async tests do not need `@pytest.mark.asyncio`.
- Never use `gh pr merge --admin`. The ruleset only allows `merge` (not `squash`): merge via `gh pr merge --merge`.
- Repo has pre-commit hooks that run on commit. Let them run; do not use `--no-verify` unless you are explicitly told to.
- **This plan is for the `markdown-vault-mcp` repo only**, with one exception: Task 14 bootstraps the separate `pvliesdonk/claude-plugins` catalog repo. Keep that separation clear — do not land catalog content in the main repo.

---

## File structure

### Files created in `pvliesdonk/markdown-vault-mcp`

| Path | Responsibility |
|---|---|
| `packaging/mcpb/manifest.json.in` | `envsubst` template for the `.mcpb` manifest. Single source of truth for `user_config` fields and `mcp_config.env` mapping. |
| `packaging/mcpb/pyproject.toml.in` | `envsubst` template declaring one dep: `markdown-vault-mcp[all]==${VERSION}`. |
| `packaging/mcpb/src/server.py` | Three-line entry shim: `from markdown_vault_mcp.cli import main; main(["serve"])`. |
| `packaging/mcpb/build.sh` | Local helper mirroring the `build-mcpb` CI job; renders templates and runs `mcpb validate && mcpb pack`. |
| `packaging/mcpb/.gitignore` | Excludes `build/` and `dist/` from version control. |
| `.claude-plugin/plugin/.claude-plugin/plugin.json` | Claude Code plugin metadata. Version bumped by release workflow. |
| `.claude-plugin/plugin/.mcp.json` | MCP launch config for Claude Code — pinned `uvx --from markdown-vault-mcp[all]==<version>`. Version bumped by release workflow. |
| `.claude-plugin/plugin/skills/vault-workflow/SKILL.md` | Tool-usage guidance for Claude Code (hybrid search, get_context first, rename with update_links, etc.). |
| `.claude-plugin/plugin/README.md` | One-page install instructions for the plugin. |
| `tests/test_packaging_mcpb.py` | Smoke test: parses all five packaging files and asserts structural invariants. |
| `docs/guides/claude-code-plugin.md` | New user-facing guide for the Claude Code plugin. |

### Files modified in `pvliesdonk/markdown-vault-mcp`

| Path | Change |
|---|---|
| `.github/workflows/release.yml` | Extend existing "Update server.json" step to also bump `plugin.json` and `.mcp.json`. Add three new jobs: `build-mcpb`, `publish-mcpb`, `publish-claude-plugin-pr`. |
| `README.md` | Install section gains tabbed one-click (Claude Desktop) / plugin (Claude Code) / PyPI tabs. |
| `docs/guides/claude-desktop.md` | Prepend "Option 0: one-click install (.mcpb)" before the existing four steps. |
| `docs/installation.md` | Add two rows to the install-methods table. |
| `docs/index.md` | Feature list and "Works with" row mention both plugin formats. |
| `docs/configuration.md` | Callout listing which env vars are exposed via the mcpb form vs. require direct editing. |
| `mkdocs.yml` | Add nav entry for `guides/claude-code-plugin.md`. |
| `CLAUDE.md` | Add `packaging/mcpb/**` and `.claude-plugin/plugin/**` to the Documentation Discipline file list; add an Acceptance Gate bullet about plugin artifact parity. |
| `SYNC.md` | List `packaging/mcpb/` and `.claude-plugin/plugin/` under pending ports to `image-generation-mcp`. |

### Files created in new `pvliesdonk/claude-plugins` repo (Task 14 only)

| Path | Responsibility |
|---|---|
| `.claude-plugin/marketplace.json` | Catalog manifest — single `markdown-vault-mcp` entry today, open to adding `image-generation-mcp` later. |
| `README.md` | One-paragraph repo description + `/plugin marketplace add` instructions. |
| `LICENSE` | MIT. |

---

## Task 1: Verify mcpb runtime and Claude Code env-var substitution support

This is the **§10 Risk 1** + **§10 Risk 2** verification gate. Do this *before* writing any code. If either check fails, stop and update the design doc before proceeding — the rest of the plan depends on these answers.

**Files:** none (research task).

- [ ] **Step 1: Confirm `manifest_version 0.4` with `server.type: "uv"` is supported in a shipping Claude Desktop.**

  Fetch the authoritative mcpb MANIFEST spec:

  ```bash
  curl -s https://raw.githubusercontent.com/anthropics/mcpb/main/MANIFEST.md | less
  ```

  Look for `server.type` valid values and the `"uv"` section. Confirm it is documented (not marked "experimental" or "unreleased") and that the spec says the host provides `uv`.

  Then check the Claude Desktop release notes (GitHub releases or changelog) for any version that mentions `mcpb` v0.4 or `server.type: "uv"` support. Target minimum version for the `compatibility.claude_desktop` field in `manifest.json.in`.

  Expected outcome: a concrete minimum Claude Desktop version number to use in §4.2 / Task 4 of this plan (e.g. `>=0.10.0` or whatever the spec reveals).

- [ ] **Step 2: Install the mcpb CLI locally and run `mcpb --version`.**

  ```bash
  npm install -g @anthropic-ai/mcpb@latest
  mcpb --version
  ```

  Expected: a version string (for example `0.4.x`). If `npm install` fails, that is a blocker — escalate before continuing.

- [ ] **Step 3: Scratch-test the `.mcpb` path manually.**

  Create a throwaway manifest in `/tmp`:

  ```bash
  mkdir -p /tmp/mcpb-scratch/src
  cat > /tmp/mcpb-scratch/manifest.json <<'JSON'
  {
    "manifest_version": "0.4",
    "name": "scratch-test",
    "version": "0.0.0",
    "description": "scratch verification for server.type: uv",
    "author": {"name": "scratch"},
    "server": {
      "type": "uv",
      "entry_point": "src/server.py"
    }
  }
  JSON
  cat > /tmp/mcpb-scratch/pyproject.toml <<'TOML'
  [project]
  name = "scratch"
  version = "0.0.0"
  requires-python = ">=3.10"
  dependencies = []
  TOML
  cat > /tmp/mcpb-scratch/src/server.py <<'PY'
  print("hello from scratch")
  PY

  mcpb validate /tmp/mcpb-scratch/manifest.json
  mcpb pack /tmp/mcpb-scratch /tmp/scratch-test.mcpb
  unzip -l /tmp/scratch-test.mcpb
  ```

  Expected: `mcpb validate` reports no errors; `mcpb pack` produces `/tmp/scratch-test.mcpb`; the unzip listing includes `manifest.json`, `pyproject.toml`, and `src/server.py` with no `server/lib/` or `server/venv/` directories.

  If `mcpb validate` rejects `server.type: "uv"`, that is the Risk 1 fallback signal — stop and update the design to use `server.type: "python"` with documented FastEmbed exclusion.

- [ ] **Step 4: Verify Claude Code env-var substitution syntax.**

  Open the Claude Code plugins reference and find the section on `.mcp.json` env substitution:

  ```bash
  # Authoritative source — may be in docs.claude.com under Claude Code → Plugins
  # Fall back to: claude-code repo docs directory on GitHub
  ```

  The question to answer: does Claude Code's `.mcp.json` `env` block support `${VAR:-default}` shell-style defaults, or only bare `${VAR}`? Check both the published reference and by grepping the claude-code repo if you have a clone.

  Expected outcome: a definitive yes/no. If yes, the `.mcp.json` in Task 8 uses `${VAR:-default}` as designed. If no, Task 8 drops the default and Task 10 (plugin README) adds a prominent "set this env var first" block.

- [ ] **Step 5: Record findings.**

  Add a short note at the top of this plan file under "Risk verification results":

  ```
  Risk verification results (YYYY-MM-DD):
  - manifest_version 0.4 + server.type: "uv": <supported / not supported>
  - Minimum Claude Desktop version: <version>
  - Claude Code ${VAR:-default} syntax: <supported / not supported>
  - Fallback taken: <none / server.type python / bare ${VAR}>
  ```

  Commit:

  ```bash
  git add docs/superpowers/plans/2026-04-10-claude-plugins.md
  git commit -m "docs: record mcpb + claude code plugin verification results"
  ```

---

## Task 2: Bootstrap the packaging smoke-test file

Start with the smoke test infrastructure so every subsequent file-creation task has a failing-test → passing-test loop. Tests live in `tests/test_packaging_mcpb.py` and grow one assertion per task.

**Files:**
- Create: `tests/test_packaging_mcpb.py`

- [ ] **Step 1: Write the first failing test — CLI import target exists.**

  This test has no dependencies on anything we will create; it verifies the base assumption that the shim we are about to write (`from markdown_vault_mcp.cli import main`) will resolve. If this is already true it passes immediately; if the CLI gets renamed it catches drift.

  Create `tests/test_packaging_mcpb.py`:

  ```python
  """Smoke tests for the Claude Desktop .mcpb bundle and Claude Code plugin.

  These tests do not run the packaged server — they assert that the packaging
  files are syntactically valid and that invariants the release workflow
  depends on (version strings, import paths) stay consistent.
  """

  from __future__ import annotations

  import json
  from pathlib import Path

  import pytest

  REPO_ROOT = Path(__file__).resolve().parent.parent
  MCPB_DIR = REPO_ROOT / "packaging" / "mcpb"
  PLUGIN_DIR = REPO_ROOT / ".claude-plugin" / "plugin"


  def test_cli_main_import_target_exists() -> None:
      """The mcpb shim imports markdown_vault_mcp.cli.main — make sure it exists."""
      from markdown_vault_mcp.cli import main

      assert callable(main)
  ```

- [ ] **Step 2: Run the test and verify it passes.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py -v
  ```

  Expected: `test_cli_main_import_target_exists PASSED`.

- [ ] **Step 3: Lint and type-check the new file.**

  ```bash
  uv run ruff check --fix tests/test_packaging_mcpb.py
  uv run ruff format tests/test_packaging_mcpb.py
  uv run ruff format --check tests/test_packaging_mcpb.py
  uv run mypy src/ tests/test_packaging_mcpb.py
  ```

  Expected: all clean.

- [ ] **Step 4: Commit.**

  ```bash
  git add tests/test_packaging_mcpb.py
  git commit -m "test(packaging): scaffold mcpb + claude-plugin smoke tests"
  ```

---

## Task 3: mcpb entry shim (TDD)

**Files:**
- Create: `packaging/mcpb/src/server.py`
- Modify: `tests/test_packaging_mcpb.py`

- [ ] **Step 1: Write the failing test.**

  Append to `tests/test_packaging_mcpb.py`:

  ```python
  def test_mcpb_server_shim_calls_main_serve() -> None:
      """The shim's only job is to invoke `cli.main(["serve"])`."""
      shim = MCPB_DIR / "src" / "server.py"
      assert shim.exists(), f"missing shim at {shim}"
      content = shim.read_text(encoding="utf-8")
      assert "from markdown_vault_mcp.cli import main" in content
      assert 'main(["serve"])' in content
  ```

- [ ] **Step 2: Run the test and verify it fails.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_mcpb_server_shim_calls_main_serve -v
  ```

  Expected: `FAILED` — `AssertionError: missing shim at .../packaging/mcpb/src/server.py`.

- [ ] **Step 3: Create the shim.**

  Create `packaging/mcpb/src/server.py`:

  ```python
  """Entry shim for the markdown-vault-mcp .mcpb bundle.

  Claude Desktop invokes this file through the host-provided uv runtime. The
  bundle's pyproject.toml pins ``markdown-vault-mcp[all]==<version>``; uv
  resolves the dependency tree on install and this shim just delegates to the
  package's CLI.
  """

  from markdown_vault_mcp.cli import main

  if __name__ == "__main__":
      main(["serve"])
  ```

- [ ] **Step 4: Run the test and verify it passes.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_mcpb_server_shim_calls_main_serve -v
  ```

  Expected: PASSED.

- [ ] **Step 5: Lint and commit.**

  ```bash
  uv run ruff check --fix packaging/mcpb/src/server.py tests/test_packaging_mcpb.py
  uv run ruff format packaging/mcpb/src/server.py tests/test_packaging_mcpb.py
  uv run ruff format --check packaging/mcpb/src/server.py tests/test_packaging_mcpb.py
  git add packaging/mcpb/src/server.py tests/test_packaging_mcpb.py
  git commit -m "feat(packaging): add mcpb entry shim delegating to cli.main"
  ```

---

## Task 4: mcpb manifest template (TDD)

**Files:**
- Create: `packaging/mcpb/manifest.json.in`
- Modify: `tests/test_packaging_mcpb.py`

- [ ] **Step 1: Write the failing test.**

  Append to `tests/test_packaging_mcpb.py`:

  ```python
  def _load_manifest_template() -> dict:
      """Load the mcpb manifest template with ${VERSION} replaced by a literal."""
      template = (MCPB_DIR / "manifest.json.in").read_text(encoding="utf-8")
      rendered = template.replace("${VERSION}", "0.0.0-test")
      return json.loads(rendered)


  def test_mcpb_manifest_template_valid_and_complete() -> None:
      """The mcpb manifest must parse and carry the fields the spec requires."""
      manifest = _load_manifest_template()

      assert manifest["manifest_version"] == "0.4"
      assert manifest["name"] == "markdown-vault-mcp"
      assert manifest["version"] == "0.0.0-test"

      server = manifest["server"]
      assert server["type"] == "uv"
      assert server["entry_point"] == "src/server.py"

      env = server["mcp_config"]["env"]
      # The one truly required env var must be wired to the form.
      assert env["MARKDOWN_VAULT_MCP_SOURCE_DIR"] == "${user_config.source_dir}"

      user_config = manifest["user_config"]
      assert user_config["source_dir"]["required"] is True
      assert user_config["source_dir"]["type"] == "directory"
      # Sensitive fields must be marked so the host stores them in the keychain.
      assert user_config["openai_api_key"]["sensitive"] is True
      assert user_config["git_token"]["sensitive"] is True
  ```

- [ ] **Step 2: Run the test and verify it fails.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_mcpb_manifest_template_valid_and_complete -v
  ```

  Expected: `FileNotFoundError` — template does not exist yet.

- [ ] **Step 3: Create the manifest template.**

  Create `packaging/mcpb/manifest.json.in`. Replace the `compatibility.claude_desktop` minimum with the value verified in Task 1, Step 1:

  ```json
  {
    "manifest_version": "0.4",
    "name": "markdown-vault-mcp",
    "display_name": "Markdown Vault",
    "version": "${VERSION}",
    "description": "FTS5 + semantic search over a markdown vault. Read, edit, link, and analyze notes.",
    "long_description": "Generic markdown-collection MCP server with SQLite FTS5 full-text search, optional embedding-based semantic search, frontmatter-aware indexing, link-graph tools (backlinks, outlinks, similar notes, orphans), git write strategy, and MCP Apps views (Context Card, Graph Explorer, Vault Browser).",
    "author": {
      "name": "Peter van Liesdonk",
      "url": "https://github.com/pvliesdonk"
    },
    "repository": {
      "type": "git",
      "url": "https://github.com/pvliesdonk/markdown-vault-mcp.git"
    },
    "homepage": "https://pvliesdonk.github.io/markdown-vault-mcp/",
    "documentation": "https://pvliesdonk.github.io/markdown-vault-mcp/",
    "support": "https://github.com/pvliesdonk/markdown-vault-mcp/issues",
    "license": "MIT",
    "keywords": ["markdown", "vault", "obsidian", "search", "fts5", "embeddings", "zettelkasten"],
    "server": {
      "type": "uv",
      "entry_point": "src/server.py",
      "mcp_config": {
        "env": {
          "MARKDOWN_VAULT_MCP_SOURCE_DIR":       "${user_config.source_dir}",
          "MARKDOWN_VAULT_MCP_READ_ONLY":        "${user_config.read_only}",
          "MARKDOWN_VAULT_MCP_SERVER_NAME":      "${user_config.server_name}",
          "MARKDOWN_VAULT_MCP_EXCLUDE":          "${user_config.exclude_patterns}",
          "MARKDOWN_VAULT_MCP_STATE_PATH":       "${user_config.state_path}",
          "EMBEDDING_PROVIDER":                  "${user_config.embedding_provider}",
          "OLLAMA_HOST":                         "${user_config.ollama_host}",
          "MARKDOWN_VAULT_MCP_OLLAMA_MODEL":     "${user_config.ollama_model}",
          "MARKDOWN_VAULT_MCP_FASTEMBED_MODEL":  "${user_config.fastembed_model}",
          "OPENAI_API_KEY":                      "${user_config.openai_api_key}",
          "MARKDOWN_VAULT_MCP_GIT_REPO_URL":     "${user_config.git_repo_url}",
          "MARKDOWN_VAULT_MCP_GIT_TOKEN":        "${user_config.git_token}",
          "MARKDOWN_VAULT_MCP_GIT_PUSH_DELAY_S": "${user_config.git_push_delay_s}",
          "FASTMCP_LOG_LEVEL":                   "${user_config.log_level}"
        }
      }
    },
    "user_config": {
      "source_dir": {
        "type": "directory",
        "title": "Vault directory",
        "description": "Absolute path to your markdown vault.",
        "required": true,
        "default": "${DOCUMENTS}/Vault"
      },
      "read_only": {
        "type": "boolean",
        "title": "Read-only mode",
        "description": "When true, write/edit/delete/rename tools are hidden.",
        "required": false,
        "default": true
      },
      "server_name": {
        "type": "string",
        "title": "Server name",
        "description": "Name shown in the Claude tool list.",
        "required": false,
        "default": "markdown-vault-mcp"
      },
      "exclude_patterns": {
        "type": "string",
        "title": "Exclude patterns",
        "description": "Comma-separated glob patterns to exclude from indexing.",
        "required": false,
        "default": ".obsidian/**,.trash/**,.git/**"
      },
      "state_path": {
        "type": "directory",
        "title": "State directory",
        "description": "Where to store the FTS5 index and embeddings. Blank uses .markdown_vault_mcp next to the vault.",
        "required": false
      },
      "embedding_provider": {
        "type": "string",
        "title": "Embedding provider",
        "description": "One of: fastembed, ollama, openai. Leave blank to disable semantic search.",
        "required": false
      },
      "fastembed_model": {
        "type": "string",
        "title": "FastEmbed model",
        "description": "Only used when embedding_provider=fastembed.",
        "required": false,
        "default": "BAAI/bge-small-en-v1.5"
      },
      "ollama_host": {
        "type": "string",
        "title": "Ollama host",
        "description": "Only used when embedding_provider=ollama.",
        "required": false,
        "default": "http://localhost:11434"
      },
      "ollama_model": {
        "type": "string",
        "title": "Ollama model",
        "description": "Only used when embedding_provider=ollama.",
        "required": false,
        "default": "nomic-embed-text"
      },
      "openai_api_key": {
        "type": "string",
        "title": "OpenAI API key",
        "description": "Only used when embedding_provider=openai. Stored in the OS keychain.",
        "required": false,
        "sensitive": true
      },
      "git_repo_url": {
        "type": "string",
        "title": "Git repository URL",
        "description": "Set to enable managed git mode (auto-commit and push on write).",
        "required": false
      },
      "git_token": {
        "type": "string",
        "title": "Git personal access token",
        "description": "HTTPS auth for the configured git repository.",
        "required": false,
        "sensitive": true
      },
      "git_push_delay_s": {
        "type": "number",
        "title": "Git push delay (seconds)",
        "description": "Batches rapid writes. 0 disables delayed push.",
        "required": false,
        "default": 30,
        "min": 0,
        "max": 3600
      },
      "log_level": {
        "type": "string",
        "title": "Log level",
        "description": "One of: DEBUG, INFO, WARNING, ERROR.",
        "required": false,
        "default": "INFO"
      }
    },
    "compatibility": {
      "claude_desktop": ">=0.10.0",
      "platforms": ["darwin", "win32", "linux"],
      "runtimes": {
        "python": ">=3.10,<4.0"
      }
    }
  }
  ```

- [ ] **Step 4: Run the test and verify it passes.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_mcpb_manifest_template_valid_and_complete -v
  ```

  Expected: PASSED.

- [ ] **Step 5: Validate the rendered manifest with the real mcpb CLI.**

  ```bash
  mkdir -p /tmp/mcpb-manifest-check
  VERSION=0.0.0-test envsubst < packaging/mcpb/manifest.json.in \
    > /tmp/mcpb-manifest-check/manifest.json
  mcpb validate /tmp/mcpb-manifest-check/manifest.json
  ```

  Expected: no validation errors.

- [ ] **Step 6: Commit.**

  ```bash
  git add packaging/mcpb/manifest.json.in tests/test_packaging_mcpb.py
  git commit -m "feat(packaging): add mcpb manifest template"
  ```

---

## Task 5: mcpb pyproject template (TDD)

**Files:**
- Create: `packaging/mcpb/pyproject.toml.in`
- Modify: `tests/test_packaging_mcpb.py`

- [ ] **Step 1: Write the failing test.**

  Append to `tests/test_packaging_mcpb.py`:

  ```python
  def test_mcpb_pyproject_template_pins_versioned_package() -> None:
      """The bundle pyproject must pin markdown-vault-mcp[all] to the same VERSION."""
      template = (MCPB_DIR / "pyproject.toml.in").read_text(encoding="utf-8")
      assert "${VERSION}" in template, "template must use ${VERSION} placeholder"
      # The dep line should pin [all] extras to the same version.
      assert 'markdown-vault-mcp[all]==${VERSION}' in template
      assert 'requires-python = ">=3.10"' in template
  ```

- [ ] **Step 2: Run the test and verify it fails.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_mcpb_pyproject_template_pins_versioned_package -v
  ```

  Expected: FAILED — file missing.

- [ ] **Step 3: Create the template.**

  Create `packaging/mcpb/pyproject.toml.in`:

  ```toml
  # Rendered at build time by envsubst. ${VERSION} matches the package release.
  [project]
  name = "markdown-vault-mcp-mcpb"
  version = "${VERSION}"
  requires-python = ">=3.10"
  dependencies = [
    "markdown-vault-mcp[all]==${VERSION}",
  ]
  ```

- [ ] **Step 4: Run the test and verify it passes.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_mcpb_pyproject_template_pins_versioned_package -v
  ```

  Expected: PASSED.

- [ ] **Step 5: Commit.**

  ```bash
  git add packaging/mcpb/pyproject.toml.in tests/test_packaging_mcpb.py
  git commit -m "feat(packaging): add mcpb pyproject template pinning [all] extras"
  ```

---

## Task 6: mcpb local build script and .gitignore

The CI job in Task 12 is the source of truth, but developers need a way to build locally without pushing a tag.

**Files:**
- Create: `packaging/mcpb/build.sh`
- Create: `packaging/mcpb/.gitignore`

- [ ] **Step 1: Create `packaging/mcpb/.gitignore`.**

  ```gitignore
  # Local build artifacts
  build/
  dist/
  ```

- [ ] **Step 2: Create `packaging/mcpb/build.sh`.**

  ```bash
  #!/usr/bin/env bash
  # Build a markdown-vault-mcp .mcpb bundle locally.
  #
  # Usage:
  #   VERSION=1.20.1 ./packaging/mcpb/build.sh
  #
  # With no VERSION set, builds a "dev" bundle for validation only.
  set -euo pipefail

  VERSION="${VERSION:-dev}"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
  BUILD_DIR="${REPO_ROOT}/packaging/mcpb/build"
  DIST_DIR="${REPO_ROOT}/packaging/mcpb/dist"

  command -v mcpb >/dev/null 2>&1 || {
    echo "error: mcpb CLI not found. Install with:" >&2
    echo "  npm install -g @anthropic-ai/mcpb@latest" >&2
    exit 1
  }

  rm -rf "${BUILD_DIR}"
  mkdir -p "${BUILD_DIR}/src" "${DIST_DIR}"

  VERSION="${VERSION}" envsubst < "${SCRIPT_DIR}/manifest.json.in" \
    > "${BUILD_DIR}/manifest.json"
  VERSION="${VERSION}" envsubst < "${SCRIPT_DIR}/pyproject.toml.in" \
    > "${BUILD_DIR}/pyproject.toml"
  cp "${SCRIPT_DIR}/src/server.py" "${BUILD_DIR}/src/server.py"

  mcpb validate "${BUILD_DIR}/manifest.json"
  mcpb pack "${BUILD_DIR}" "${DIST_DIR}/markdown-vault-mcp-${VERSION}.mcpb"

  echo "built ${DIST_DIR}/markdown-vault-mcp-${VERSION}.mcpb"
  ```

- [ ] **Step 3: Make the script executable and run it.**

  ```bash
  chmod +x packaging/mcpb/build.sh
  VERSION=dev ./packaging/mcpb/build.sh
  ```

  Expected: `built .../dist/markdown-vault-mcp-dev.mcpb` with no errors from `mcpb validate` or `mcpb pack`.

- [ ] **Step 4: Inspect the bundle.**

  ```bash
  unzip -l packaging/mcpb/dist/markdown-vault-mcp-dev.mcpb
  ```

  Expected: lists `manifest.json`, `pyproject.toml`, `src/server.py`, **no** `server/lib/` or `server/venv/` directories.

- [ ] **Step 5: Commit.**

  The build artifacts must NOT be committed — `.gitignore` in Step 1 handles that.

  ```bash
  git add packaging/mcpb/build.sh packaging/mcpb/.gitignore
  git commit -m "feat(packaging): add local mcpb build script"
  ```

---

## Task 7: Claude Code plugin metadata — `plugin.json` (TDD)

**Files:**
- Create: `.claude-plugin/plugin/.claude-plugin/plugin.json`
- Modify: `tests/test_packaging_mcpb.py`

- [ ] **Step 1: Determine the current package version.**

  ```bash
  grep '^version' pyproject.toml
  ```

  Record the value — for example `1.20.1`. Use this literal in Step 3.

- [ ] **Step 2: Write the failing test.**

  Append to `tests/test_packaging_mcpb.py`:

  ```python
  def _load_plugin_json() -> dict:
      path = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
      return json.loads(path.read_text(encoding="utf-8"))


  def test_claude_code_plugin_json_shape() -> None:
      """plugin.json must carry the expected name, repo, and a concrete version."""
      plugin = _load_plugin_json()
      assert plugin["name"] == "markdown-vault-mcp"
      assert plugin["repository"] == "https://github.com/pvliesdonk/markdown-vault-mcp"
      assert plugin["license"] == "MIT"

      # Version must look like a real semver — not a template literal.
      version = plugin["version"]
      assert version != "${VERSION}"
      parts = version.split(".")
      assert len(parts) == 3 and all(p.isdigit() for p in parts), (
          f"expected X.Y.Z semver, got {version!r}"
      )
  ```

- [ ] **Step 3: Run the test and verify it fails.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_claude_code_plugin_json_shape -v
  ```

  Expected: FAILED — file missing.

- [ ] **Step 4: Create `plugin.json`.**

  Replace `1.20.1` with the value from Step 1 if it differs:

  ```bash
  mkdir -p .claude-plugin/plugin/.claude-plugin
  ```

  Create `.claude-plugin/plugin/.claude-plugin/plugin.json`:

  ```json
  {
    "name": "markdown-vault-mcp",
    "description": "MCP server for markdown vaults: FTS5 + semantic search, link graph, write/edit/git.",
    "version": "1.20.1",
    "author": { "name": "Peter van Liesdonk" },
    "homepage": "https://pvliesdonk.github.io/markdown-vault-mcp/",
    "repository": "https://github.com/pvliesdonk/markdown-vault-mcp",
    "license": "MIT",
    "keywords": ["markdown", "vault", "obsidian", "search", "mcp"]
  }
  ```

- [ ] **Step 5: Run the test and verify it passes.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_claude_code_plugin_json_shape -v
  ```

  Expected: PASSED.

- [ ] **Step 6: Commit.**

  ```bash
  git add .claude-plugin/plugin/.claude-plugin/plugin.json tests/test_packaging_mcpb.py
  git commit -m "feat(plugin): add Claude Code plugin.json metadata"
  ```

---

## Task 8: Claude Code `.mcp.json` with pinned `--from` (TDD)

This is the file whose version string must stay in lockstep with `plugin.json` — Task 11 extends the release workflow to enforce that.

**Files:**
- Create: `.claude-plugin/plugin/.mcp.json`
- Modify: `tests/test_packaging_mcpb.py`

- [ ] **Step 1: Write the failing test — parity with plugin.json.**

  Append to `tests/test_packaging_mcpb.py`:

  ```python
  import re


  def _load_plugin_mcp_json() -> dict:
      path = PLUGIN_DIR / ".mcp.json"
      return json.loads(path.read_text(encoding="utf-8"))


  def test_plugin_mcp_json_pinned_and_matches_plugin_version() -> None:
      """.mcp.json must pin --from markdown-vault-mcp[all]==<X.Y.Z> and match plugin.json."""
      mcp_cfg = _load_plugin_mcp_json()
      entry = mcp_cfg["markdown-vault-mcp"]
      assert entry["command"] == "uvx"

      args = entry["args"]
      assert "--from" in args, f"args must include --from, got {args}"
      from_index = args.index("--from")
      spec = args[from_index + 1]
      match = re.fullmatch(r"markdown-vault-mcp\[all\]==(\d+\.\d+\.\d+)", spec)
      assert match, f"unexpected --from spec: {spec!r}"

      plugin_version = _load_plugin_json()["version"]
      assert match.group(1) == plugin_version, (
          f".mcp.json pinned to {match.group(1)} but plugin.json is {plugin_version}"
      )

      env = entry["env"]
      assert "MARKDOWN_VAULT_MCP_SOURCE_DIR" in env
  ```

- [ ] **Step 2: Run the test and verify it fails.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_plugin_mcp_json_pinned_and_matches_plugin_version -v
  ```

  Expected: FAILED — file missing.

- [ ] **Step 3: Create `.mcp.json`.**

  Use the **same** version you put into `plugin.json` in Task 7. If Task 1 Step 4 verified that `${VAR:-default}` syntax is NOT supported, drop the `:-default` suffixes and instead document in Task 10 that users must set these env vars first.

  Create `.claude-plugin/plugin/.mcp.json`:

  ```json
  {
    "markdown-vault-mcp": {
      "command": "uvx",
      "args": [
        "--from", "markdown-vault-mcp[all]==1.20.1",
        "markdown-vault-mcp", "serve"
      ],
      "env": {
        "MARKDOWN_VAULT_MCP_SOURCE_DIR": "${MARKDOWN_VAULT_MCP_SOURCE_DIR}",
        "MARKDOWN_VAULT_MCP_READ_ONLY": "${MARKDOWN_VAULT_MCP_READ_ONLY:-true}",
        "EMBEDDING_PROVIDER": "${EMBEDDING_PROVIDER:-}",
        "MARKDOWN_VAULT_MCP_EXCLUDE": "${MARKDOWN_VAULT_MCP_EXCLUDE:-.obsidian/**,.trash/**,.git/**}"
      }
    }
  }
  ```

- [ ] **Step 4: Run the test and verify it passes.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py::test_plugin_mcp_json_pinned_and_matches_plugin_version -v
  ```

  Expected: PASSED.

- [ ] **Step 5: Run the full test file to make sure nothing regressed.**

  ```bash
  uv run pytest tests/test_packaging_mcpb.py -v
  ```

  Expected: all five assertions pass.

- [ ] **Step 6: Commit.**

  ```bash
  git add .claude-plugin/plugin/.mcp.json tests/test_packaging_mcpb.py
  git commit -m "feat(plugin): add Claude Code .mcp.json with pinned uvx --from"
  ```

---

## Task 9: `vault-workflow` SKILL.md

This is the value-add of the plugin beyond raw MCP tool registration — a behavioral guide for Claude Code.

**Files:**
- Create: `.claude-plugin/plugin/skills/vault-workflow/SKILL.md`

- [ ] **Step 1: Create the skill file.**

  ```bash
  mkdir -p .claude-plugin/plugin/skills/vault-workflow
  ```

  Create `.claude-plugin/plugin/skills/vault-workflow/SKILL.md`:

  ```markdown
  ---
  name: vault-workflow
  description: Use when the user asks you to search, read, or reason about notes in their markdown vault — guides when to use which vault tool and how to chain them for good results.
  ---

  # Working effectively with the markdown vault

  When the user mentions "my vault", "my notes", or asks a question that could
  be answered from their knowledge base, use the markdown-vault-mcp tools as
  follows.

  ## Search strategy

  - **Default to `search` with `mode="hybrid"`** — combines BM25 keyword and
    embedding similarity, gives the best recall for conceptual questions.
  - Fall back to `mode="keyword"` only when the user gives an exact phrase or
    tag they want matched literally.
  - If hybrid returns nothing and the query is a proper noun, retry with
    `mode="keyword"` — embeddings miss exact names.

  ## Reading and context

  - After finding a relevant note with `search`, call `get_context` on the top
    hit before reading the full body. Context returns backlinks, outlinks,
    similar notes, folder peers, and tags in one call — usually enough to
    answer without reading the file.
  - Only call `read` when the user asks for the text itself or when
    `get_context` does not give enough signal.

  ## Link-graph questions

  - "What notes reference X?" → `get_backlinks`.
  - "What does this note link to?" → `get_outlinks`.
  - "How are these two notes connected?" → `get_connection_path`.
  - "What is orphaned?" → `get_orphan_notes`.
  - "What is most cited?" → `get_most_linked`.

  ## Writes (only if read-only mode is disabled)

  - Prefer `edit` over `write` for targeted changes — `edit` fails safely if
    the old text is not unique, preventing accidental overwrites.
  - Use `rename(update_links=True)` for moves, never `write` to a new path plus
    `delete` of the old path — the `update_links` flag repairs internal
    references.
  - Never call `reindex` after writes; the server updates its index inline.

  ## Do not

  - Do not use `list_documents` as a search substitute — it is a flat
    enumeration, not ranked.
  - Do not read a note and then re-search for it; remember the path from the
    first result.
  ```

- [ ] **Step 2: Commit.**

  ```bash
  git add .claude-plugin/plugin/skills/vault-workflow/SKILL.md
  git commit -m "feat(plugin): add vault-workflow SKILL.md for Claude Code"
  ```

---

## Task 10: Plugin `README.md`

**Files:**
- Create: `.claude-plugin/plugin/README.md`

- [ ] **Step 1: Create the README.**

  Tailor the "Set env vars first" block below to the Task 1 Step 4 finding: if `${VAR:-default}` is NOT supported, expand the env-var setup block to explicitly require all four vars with example values.

  Create `.claude-plugin/plugin/README.md`:

  ```markdown
  # markdown-vault-mcp (Claude Code plugin)

  MCP server for markdown vaults: FTS5 + semantic search, link graph,
  write/edit/git.

  ## Prerequisites

  - [`uv`](https://docs.astral.sh/uv/) installed on your machine. The plugin's
    `.mcp.json` launches the server via `uvx`, which is distributed with `uv`.
  - A markdown directory (or Obsidian vault) you want to query.

  ## Install

  ```bash
  /plugin marketplace add pvliesdonk/claude-plugins
  /plugin install markdown-vault-mcp@pvliesdonk
  ```

  ## Configure

  Set `MARKDOWN_VAULT_MCP_SOURCE_DIR` in your shell profile before starting
  Claude Code. On macOS/Linux:

  ```bash
  echo 'export MARKDOWN_VAULT_MCP_SOURCE_DIR=/path/to/your/vault' >> ~/.zshrc
  ```

  On Windows PowerShell:

  ```powershell
  [Environment]::SetEnvironmentVariable(
      "MARKDOWN_VAULT_MCP_SOURCE_DIR",
      "C:\Users\You\Vault",
      "User")
  ```

  Optional environment variables:

  | Variable | Default | Purpose |
  |---|---|---|
  | `MARKDOWN_VAULT_MCP_READ_ONLY` | `true` | Disable write tools. |
  | `EMBEDDING_PROVIDER` | *(empty)* | `fastembed` / `ollama` / `openai`. Leave blank for keyword-only search. |
  | `MARKDOWN_VAULT_MCP_EXCLUDE` | `.obsidian/**,.trash/**,.git/**` | Glob patterns to skip. |

  For the full list of env vars, see the
  [Configuration reference](https://pvliesdonk.github.io/markdown-vault-mcp/configuration/).

  ## What you get

  - **Tools:** `search`, `read`, `get_context`, `get_backlinks`, `get_outlinks`,
    `get_similar`, `get_connection_path`, `get_recent`, `list_documents`, and
    (in write mode) `write`, `edit`, `rename`, `delete`.
  - **Skill:** `vault-workflow` tells Claude Code when to use hybrid vs.
    keyword search, when to call `get_context` before `read`, and how to use
    `rename(update_links=True)` correctly.
  - **Prompts:** `summarize`, `research`, `discuss`, `related`, `compare`
    (available as slash commands via MCP prompt surfacing).

  ## Updating

  ```bash
  /plugin update markdown-vault-mcp@pvliesdonk
  ```

  ## Documentation

  Full docs: <https://pvliesdonk.github.io/markdown-vault-mcp/>
  Issues: <https://github.com/pvliesdonk/markdown-vault-mcp/issues>
  License: MIT.
  ```

- [ ] **Step 2: Commit.**

  ```bash
  git add .claude-plugin/plugin/README.md
  git commit -m "docs(plugin): add Claude Code plugin README"
  ```

---

## Task 11: Extend the release job to bump all three manifests in lockstep

**Files:**
- Modify: `.github/workflows/release.yml` (lines 55-73, the "Update server.json to released version" step)

- [ ] **Step 1: Read the current step.**

  ```bash
  sed -n '55,74p' .github/workflows/release.yml
  ```

  Confirm it matches:

  ```yaml
  - name: Update server.json to released version
    if: steps.release.outputs.released == 'true'
    env:
      VERSION: ${{ steps.release.outputs.version }}
    run: |
      jq --arg v "$VERSION" '
        .version = $v |
        .packages |= map(
          if .registryType == "pypi" then .version = $v
          elif .registryType == "oci" then .identifier = ("ghcr.io/pvliesdonk/markdown-vault-mcp:v" + $v)
          else . end
        )
      ' server.json > server.json.tmp
      mv server.json.tmp server.json
      git config user.name "github-actions"
      git config user.email "actions@users.noreply.github.com"
      git add server.json
      git diff --cached --quiet || git commit -m "chore: update server.json to v${VERSION} [skip ci]"
      git push
  ```

- [ ] **Step 2: Replace the step with the extended version.**

  Use Edit to replace the entire step block with:

  ```yaml
  - name: Update versioned manifests to released version
    if: steps.release.outputs.released == 'true'
    env:
      VERSION: ${{ steps.release.outputs.version }}
    run: |
      # server.json (existing logic)
      jq --arg v "$VERSION" '
        .version = $v |
        .packages |= map(
          if .registryType == "pypi" then .version = $v
          elif .registryType == "oci" then .identifier = ("ghcr.io/pvliesdonk/markdown-vault-mcp:v" + $v)
          else . end
        )
      ' server.json > server.json.tmp
      mv server.json.tmp server.json

      # Claude Code plugin.json (new)
      jq --arg v "$VERSION" '.version = $v' \
        .claude-plugin/plugin/.claude-plugin/plugin.json > plugin.json.tmp
      mv plugin.json.tmp .claude-plugin/plugin/.claude-plugin/plugin.json

      # Claude Code .mcp.json — keep --from spec in lockstep with plugin.json (new)
      jq --arg v "$VERSION" '
        ."markdown-vault-mcp".args = [
          "--from", ("markdown-vault-mcp[all]==" + $v),
          "markdown-vault-mcp", "serve"
        ]
      ' .claude-plugin/plugin/.mcp.json > mcp.json.tmp
      mv mcp.json.tmp .claude-plugin/plugin/.mcp.json

      git config user.name "github-actions"
      git config user.email "actions@users.noreply.github.com"
      git add server.json \
              .claude-plugin/plugin/.claude-plugin/plugin.json \
              .claude-plugin/plugin/.mcp.json
      git diff --cached --quiet || git commit -m "chore: update manifests to v${VERSION} [skip ci]"
      git push
  ```

- [ ] **Step 3: Sanity-check the jq expressions locally against the real files.**

  ```bash
  VERSION=9.9.9
  jq --arg v "$VERSION" '.version = $v' \
    .claude-plugin/plugin/.claude-plugin/plugin.json
  jq --arg v "$VERSION" '
    ."markdown-vault-mcp".args = [
      "--from", ("markdown-vault-mcp[all]==" + $v),
      "markdown-vault-mcp", "serve"
    ]
  ' .claude-plugin/plugin/.mcp.json
  ```

  Expected: both commands print modified JSON to stdout with the version bumped to `9.9.9` (without writing any file).

- [ ] **Step 4: Commit.**

  ```bash
  git add .github/workflows/release.yml
  git commit -m "ci: bump plugin.json and .mcp.json alongside server.json on release"
  ```

---

## Task 12: Add `build-mcpb` and `publish-mcpb` release jobs

**Files:**
- Modify: `.github/workflows/release.yml` (append two new jobs)

- [ ] **Step 1: Locate the insertion point.**

  The new jobs go *after* the existing `publish-linux-packages` job and *before* `publish-registry`. Find the end of `publish-linux-packages`:

  ```bash
  grep -n "publish-linux-packages:\|publish-registry:" .github/workflows/release.yml
  ```

- [ ] **Step 2: Append the two new jobs.**

  Insert between `publish-linux-packages` and `publish-registry`:

  ```yaml
    build-mcpb:
      needs: release
      if: needs.release.outputs.released == 'true'
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
          with:
            ref: ${{ needs.release.outputs.tag }}
        - name: Install mcpb CLI
          run: npm install -g @anthropic-ai/mcpb@latest
        - name: Render templates
          env:
            VERSION: ${{ needs.release.outputs.version }}
          run: |
            mkdir -p build/mcpb/src
            envsubst < packaging/mcpb/manifest.json.in  > build/mcpb/manifest.json
            envsubst < packaging/mcpb/pyproject.toml.in > build/mcpb/pyproject.toml
            cp packaging/mcpb/src/server.py build/mcpb/src/server.py
        - name: Validate and pack
          env:
            VERSION: ${{ needs.release.outputs.version }}
          run: |
            mcpb validate build/mcpb/manifest.json
            mkdir -p dist
            mcpb pack build/mcpb "dist/markdown-vault-mcp-${VERSION}.mcpb"
        - uses: actions/upload-artifact@v4
          with:
            name: mcpb-bundle
            path: dist/markdown-vault-mcp-*.mcpb
            if-no-files-found: error

    publish-mcpb:
      needs: [release, build-mcpb]
      if: needs.release.outputs.released == 'true'
      runs-on: ubuntu-latest
      permissions:
        contents: write
      steps:
        - uses: actions/download-artifact@v4
          with:
            name: mcpb-bundle
            path: dist/
        - name: Upload to GitHub Release
          env:
            GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          run: |
            gh release upload \
              "${{ needs.release.outputs.tag }}" \
              dist/markdown-vault-mcp-*.mcpb \
              --clobber \
              --repo "${{ github.repository }}"
  ```

- [ ] **Step 3: Lint the YAML.**

  ```bash
  uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
  ```

  Expected: no errors printed.

- [ ] **Step 4: Commit.**

  ```bash
  git add .github/workflows/release.yml
  git commit -m "ci: add build-mcpb and publish-mcpb release jobs"
  ```

---

## Task 13: Add `publish-claude-plugin-pr` job and document the PAT secret

**Files:**
- Modify: `.github/workflows/release.yml` (append one new job)

- [ ] **Step 1: Confirm the PAT secret is created.**

  Before the job can run, `CLAUDE_PLUGINS_PAT` must exist as a repository secret in `pvliesdonk/markdown-vault-mcp`. If it does not exist yet:

  1. Go to <https://github.com/settings/personal-access-tokens/new>.
  2. Create a **fine-grained** PAT named `markdown-vault-mcp catalog bump`.
  3. Resource owner: `pvliesdonk`.
  4. Repository access: only `pvliesdonk/claude-plugins`.
  5. Permissions: **Contents: Read and write**, **Pull requests: Read and write**. Leave everything else at defaults.
  6. Copy the token.
  7. In `pvliesdonk/markdown-vault-mcp` → Settings → Secrets and variables → Actions → New repository secret: name `CLAUDE_PLUGINS_PAT`, paste the token.

  Note the token expiry date and add a calendar reminder — when the token expires, the `publish-claude-plugin-pr` job will start failing.

- [ ] **Step 2: Append the third job to release.yml.**

  Place it after `publish-mcpb` and before `publish-registry`:

  ```yaml
    publish-claude-plugin-pr:
      needs: release
      if: needs.release.outputs.released == 'true'
      runs-on: ubuntu-latest
      steps:
        - name: Checkout catalog repo
          uses: actions/checkout@v4
          with:
            repository: pvliesdonk/claude-plugins
            token: ${{ secrets.CLAUDE_PLUGINS_PAT }}
            path: catalog
        - name: Bump marketplace.json entry
          env:
            VERSION: ${{ needs.release.outputs.version }}
          run: |
            cd catalog
            jq --arg v "$VERSION" --arg ref "v$VERSION" '
              .plugins |= map(
                if .name == "markdown-vault-mcp"
                then .version = $v | .source.ref = $ref
                else . end
              )
            ' .claude-plugin/marketplace.json > marketplace.json.tmp
            mv marketplace.json.tmp .claude-plugin/marketplace.json
        - name: Create pull request
          uses: peter-evans/create-pull-request@v7
          with:
            path: catalog
            token: ${{ secrets.CLAUDE_PLUGINS_PAT }}
            branch: bump/markdown-vault-mcp-${{ needs.release.outputs.version }}
            title: "chore: bump markdown-vault-mcp to v${{ needs.release.outputs.version }}"
            body: |
              Auto-generated bump from [markdown-vault-mcp ${{ needs.release.outputs.tag }}](https://github.com/pvliesdonk/markdown-vault-mcp/releases/tag/${{ needs.release.outputs.tag }}).
            commit-message: "chore: bump markdown-vault-mcp to v${{ needs.release.outputs.version }}"
            committer: "github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>"
            author: "github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>"
  ```

- [ ] **Step 3: Lint the YAML.**

  ```bash
  uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
  ```

- [ ] **Step 4: Commit.**

  ```bash
  git add .github/workflows/release.yml
  git commit -m "ci: auto-open catalog bump PR on release"
  ```

---

## Task 14: Bootstrap the `pvliesdonk/claude-plugins` catalog repo

**This is manual and happens outside the main repo.** Perform these steps on your workstation; do not commit catalog content into `markdown-vault-mcp`.

**Files (in the new repo):**
- Create: `.claude-plugin/marketplace.json`
- Create: `README.md`
- Create: `LICENSE`

- [ ] **Step 1: Create the repo on GitHub.**

  ```bash
  gh repo create pvliesdonk/claude-plugins \
    --public \
    --description "Claude Code plugins maintained by pvliesdonk" \
    --license MIT \
    --clone
  cd claude-plugins
  ```

  Expected: clone lands in `./claude-plugins/` with a `LICENSE` file already present.

- [ ] **Step 2: Create `.claude-plugin/marketplace.json`.**

  Replace `1.20.1` with the currently-released version of `markdown-vault-mcp`.

  ```bash
  mkdir -p .claude-plugin
  ```

  Contents:

  ```json
  {
    "name": "pvliesdonk",
    "owner": {
      "name": "Peter van Liesdonk",
      "email": "peter@vanliesdonk.nl"
    },
    "metadata": {
      "description": "Claude Code plugins maintained by pvliesdonk",
      "version": "2026.04.10"
    },
    "plugins": [
      {
        "name": "markdown-vault-mcp",
        "source": {
          "source": "git-subdir",
          "url": "https://github.com/pvliesdonk/markdown-vault-mcp.git",
          "path": ".claude-plugin/plugin",
          "ref": "v1.20.1"
        },
        "description": "MCP server for markdown vaults: FTS5 + semantic search, link graph, write/edit/git.",
        "version": "1.20.1",
        "author": { "name": "Peter van Liesdonk" },
        "homepage": "https://pvliesdonk.github.io/markdown-vault-mcp/",
        "repository": "https://github.com/pvliesdonk/markdown-vault-mcp",
        "license": "MIT",
        "keywords": ["markdown", "vault", "obsidian", "search", "mcp"],
        "category": "knowledge-base"
      }
    ]
  }
  ```

- [ ] **Step 3: Create `README.md`.**

  ```markdown
  # pvliesdonk Claude Code plugin catalog

  Marketplace for Claude Code plugins maintained by [Peter van Liesdonk](https://github.com/pvliesdonk).

  ## Install

  ```
  /plugin marketplace add pvliesdonk/claude-plugins
  /plugin install <plugin-name>@pvliesdonk
  ```

  ## Available plugins

  | Plugin | Description |
  |---|---|
  | `markdown-vault-mcp` | MCP server for markdown vaults: FTS5 + semantic search, link graph, write/edit/git. |

  New releases of each plugin are bumped automatically by each upstream repo's release workflow.
  ```

- [ ] **Step 4: Validate the marketplace manifest.**

  ```bash
  jq empty .claude-plugin/marketplace.json
  ```

  Expected: no output (valid JSON). If `jq` reports an error, fix it before committing.

- [ ] **Step 5: Commit and push.**

  ```bash
  git add .claude-plugin/marketplace.json README.md
  git commit -m "feat: bootstrap pvliesdonk claude-plugins catalog"
  git push origin main
  ```

- [ ] **Step 6: Manually verify the marketplace installs.**

  From any Claude Code session:

  ```
  /plugin marketplace add pvliesdonk/claude-plugins
  ```

  Expected: Claude Code accepts the marketplace and lists `markdown-vault-mcp` as available.

  Do **not** install the plugin yet — the current tag `v1.20.1` does not have the plugin directory in its tree (Task 7 creates it on `main`). Installation will succeed after the next tag cut (Task 19).

- [ ] **Step 7: Return to the main repo directory.**

  ```bash
  cd /mnt/code/markdown-mcp
  ```

---

## Task 15: User-facing documentation updates

Lands in the same PR as the packaging work (per CLAUDE.md Documentation Discipline). Break into a single commit so the code/docs ship together.

**Files:**
- Modify: `README.md`
- Modify: `docs/guides/claude-desktop.md`
- Create: `docs/guides/claude-code-plugin.md`
- Modify: `docs/installation.md`
- Modify: `docs/index.md`
- Modify: `docs/configuration.md`
- Modify: `mkdocs.yml`

- [ ] **Step 1: Add an "Install" section to `README.md`.**

  Find the existing "Installation" or "Quick start" section near the top of `README.md` and add three tabs above it (or replace it if it is a single-tab Python-only section). Markdown:

  ````markdown
  ## Install

  === "Claude Desktop (one-click)"

      1. Download `markdown-vault-mcp-<version>.mcpb` from the [latest release](https://github.com/pvliesdonk/markdown-vault-mcp/releases/latest).
      2. Double-click to open in Claude Desktop.
      3. Fill in the "Vault directory" field and save.

      Requires Claude Desktop with `mcpb` manifest v0.4 support.

  === "Claude Code (plugin)"

      ```bash
      /plugin marketplace add pvliesdonk/claude-plugins
      /plugin install markdown-vault-mcp@pvliesdonk
      ```

      Requires [`uv`](https://docs.astral.sh/uv/) installed. Set
      `MARKDOWN_VAULT_MCP_SOURCE_DIR` in your shell profile before launching
      Claude Code.

  === "PyPI / Docker / Linux packages"

      See the [Installation guide](https://pvliesdonk.github.io/markdown-vault-mcp/installation/).
  ````

- [ ] **Step 2: Prepend "Option 0" to `docs/guides/claude-desktop.md`.**

  Locate the line `## Step 1: Basic read-only setup` (currently around line 12) and insert before it:

  ````markdown
  ## Option 0: One-click install (.mcpb)

  The fastest way to get started — no Python install, no manual config editing.

  1. Open the [latest release](https://github.com/pvliesdonk/markdown-vault-mcp/releases/latest) and download `markdown-vault-mcp-<version>.mcpb`.
  2. Double-click the file. Claude Desktop opens a configuration form.
  3. Fill in **Vault directory** (the only required field) and click **Save**.
  4. Restart Claude Desktop if prompted. The vault tools should appear in the
     tool list.

  !!! note "Which Claude Desktop versions?"
      The `.mcpb` bundle uses manifest v0.4 with `server.type: "uv"`. Claude
      Desktop supplies `uv` and resolves the server's Python dependencies on
      install — no user Python install required. If your Claude Desktop is
      older than the minimum listed in the bundle's `compatibility.claude_desktop`
      field, update to the latest version or use the manual config path below.

  !!! tip "Advanced users"
      The form exposes the fourteen most-tuned settings. For the full env-var
      surface (multiple vaults, OIDC, custom attachment extensions), use the
      manual config path in the options below.

  ---

  ## Option 1: Manual config

  The four-step manual setup below gives you full control over every env var
  and is the recommended path when you need features the one-click form does
  not expose.

  ````

  Then update the existing `## Step 1: Basic read-only setup` heading to stay as-is (it falls under Option 1).

- [ ] **Step 3: Create `docs/guides/claude-code-plugin.md`.**

  ```markdown
  # Claude Code plugin

  Install `markdown-vault-mcp` as a Claude Code plugin and get full vault tools
  (search, link graph, write/edit/git) plus a `vault-workflow` skill that
  teaches Claude Code how to use them effectively.

  ## Prerequisites

  - [`uv`](https://docs.astral.sh/uv/) installed. The plugin launches the
    server via `uvx`, which ships with `uv`.
  - A markdown directory (or Obsidian vault).
  - Claude Code version that supports the plugin marketplace.

  ## Install

  From any Claude Code session:

  ```
  /plugin marketplace add pvliesdonk/claude-plugins
  /plugin install markdown-vault-mcp@pvliesdonk
  ```

  The marketplace is hosted at
  [`pvliesdonk/claude-plugins`](https://github.com/pvliesdonk/claude-plugins)
  and sparse-clones the plugin source out of the main `markdown-vault-mcp`
  repo at a pinned release tag.

  ## Configure

  Set `MARKDOWN_VAULT_MCP_SOURCE_DIR` in your shell profile **before** starting
  Claude Code — the MCP launch config reads it from the environment.

  === "macOS / Linux"

      ```bash
      echo 'export MARKDOWN_VAULT_MCP_SOURCE_DIR=/path/to/your/vault' >> ~/.zshrc
      # reopen your terminal, then launch Claude Code
      ```

  === "Windows (PowerShell)"

      ```powershell
      [Environment]::SetEnvironmentVariable(
          "MARKDOWN_VAULT_MCP_SOURCE_DIR",
          "C:\Users\YourName\Documents\Vault",
          "User")
      # reopen PowerShell, then launch Claude Code
      ```

  Optional env vars (all have safe defaults):

  | Variable | Default | Purpose |
  |---|---|---|
  | `MARKDOWN_VAULT_MCP_READ_ONLY` | `true` | Set to `false` to enable `write`/`edit`/`delete`/`rename`. |
  | `EMBEDDING_PROVIDER` | *(empty)* | `fastembed`, `ollama`, or `openai`. Leave blank for keyword-only search. |
  | `MARKDOWN_VAULT_MCP_EXCLUDE` | `.obsidian/**,.trash/**,.git/**` | Glob patterns to skip. |

  For the full env-var reference, see [Configuration](../configuration.md).

  ## Verify

  In a Claude Code conversation, ask:

  > Search my vault for "meeting notes"

  Claude should use the `search` tool and return ranked results. If you get
  "server not found", double-check that `uv` is on your `PATH` and
  `MARKDOWN_VAULT_MCP_SOURCE_DIR` is set in the shell that launched Claude Code.

  ## The `vault-workflow` skill

  The plugin ships a `vault-workflow` SKILL.md that teaches Claude Code when
  to use hybrid vs. keyword search, to call `get_context` before `read`, and
  to use `rename(update_links=True)` instead of manual move+delete. You do not
  need to invoke it explicitly — Claude Code loads it automatically when you
  ask about your vault.

  ## Updating

  ```
  /plugin update markdown-vault-mcp@pvliesdonk
  ```

  The catalog repo receives an auto-PR on every upstream release; merge the
  bump PR and the next `/plugin update` picks up the new version.

  ## Uninstall

  ```
  /plugin uninstall markdown-vault-mcp@pvliesdonk
  /plugin marketplace remove pvliesdonk
  ```
  ```

- [ ] **Step 4: Add two rows to `docs/installation.md`.**

  After the existing "Linux Packages" section and before "Verify Installation", insert:

  ````markdown
  ## Claude Desktop (.mcpb)

  Download `markdown-vault-mcp-<version>.mcpb` from the [GitHub Releases](https://github.com/pvliesdonk/markdown-vault-mcp/releases) page and double-click to install in Claude Desktop. See the [Claude Desktop guide](guides/claude-desktop.md#option-0-one-click-install-mcpb).

  ## Claude Code (plugin)

  ```
  /plugin marketplace add pvliesdonk/claude-plugins
  /plugin install markdown-vault-mcp@pvliesdonk
  ```

  See the [Claude Code plugin guide](guides/claude-code-plugin.md).
  ````

- [ ] **Step 5: Update `docs/index.md` to mention both channels.**

  Find the features list or "Works with" section and add a row/bullet:

  ```markdown
  - **One-click install** for Claude Desktop (`.mcpb` bundle) and Claude Code (plugin marketplace).
  ```

- [ ] **Step 6: Add a callout to `docs/configuration.md`.**

  Near the top of the env-var reference table, insert:

  ```markdown
  !!! tip "Claude Desktop form vs. env vars"
      The `.mcpb` bundle exposes fourteen settings as a typed configuration
      form: `source_dir`, `read_only`, `server_name`, `exclude_patterns`,
      `state_path`, `embedding_provider`, `fastembed_model`, `ollama_host`,
      `ollama_model`, `openai_api_key`, `git_repo_url`, `git_token`,
      `git_push_delay_s`, and `log_level`. Any other env var below is
      available via direct host-config editing (advanced).
  ```

- [ ] **Step 7: Add the new guide to `mkdocs.yml`.**

  Find the `guides/` nav entry (around lines 59-68 for plugins section and 121-130 for the secondary nav) and add the Claude Code plugin guide. In the `plugins:` section around line 61, after `claude-desktop.md`:

  ```yaml
              - guides/claude-code-plugin.md: Claude Code plugin (one-command install via marketplace)
  ```

  And in the secondary nav around line 123:

  ```yaml
        - Claude Code Plugin: guides/claude-code-plugin.md
  ```

- [ ] **Step 8: Build the docs locally to catch errors.**

  ```bash
  uv run mkdocs build --strict
  ```

  Expected: clean build, no warnings. Fix any broken links or nav entries reported.

- [ ] **Step 9: Commit the docs batch.**

  ```bash
  git add README.md \
          docs/guides/claude-desktop.md \
          docs/guides/claude-code-plugin.md \
          docs/installation.md \
          docs/index.md \
          docs/configuration.md \
          mkdocs.yml
  git commit -m "docs: add Claude Desktop one-click + Claude Code plugin guides"
  ```

---

## Task 16: Update CLAUDE.md and SYNC.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `SYNC.md`

- [ ] **Step 1: Extend `CLAUDE.md` Documentation Discipline section.**

  Find the bulleted list under "Every issue, PR, and code change must consider documentation impact." Add after `docs/guides/*.md`:

  ```markdown
  - **`packaging/mcpb/**`** — Claude Desktop bundle templates. Changes to env vars, CLI args, or installation flow must be reflected in the `manifest.json.in` `user_config` or `mcp_config.env` sections.
  - **`.claude-plugin/plugin/**`** — Claude Code plugin source. New env vars or tool-usage patterns may need a `SKILL.md` or `README.md` update. The `plugin.json` and `.mcp.json` version strings are bumped by the release workflow — do not edit them in regular PRs.
  ```

- [ ] **Step 2: Extend `CLAUDE.md` Hard PR Acceptance Gates.**

  Find the numbered list under "Hard PR Acceptance Gates" and add a new gate:

  ```markdown
  6. **Plugin artifact parity** — if the PR touches env vars, the CLI, or the
     MCP tool surface, the mcpb `manifest.json.in` and the Claude Code plugin
     `README.md` / `SKILL.md` are reviewed for drift. `tests/test_packaging_mcpb.py`
     must still pass.
  ```

- [ ] **Step 3: Update `SYNC.md`.**

  Add to the "Pending ports" section:

  ```markdown
  - `packaging/mcpb/` — Claude Desktop bundle templates. Domain-independent (just the package name and description differ). Port to `image-generation-mcp` when that repo is ready.
  - `.claude-plugin/plugin/` — Claude Code plugin source and `vault-workflow` SKILL.md shape. Same story as mcpb: rename and describe, then ship.
  - `.github/workflows/release.yml` — the three new jobs (`build-mcpb`, `publish-mcpb`, `publish-claude-plugin-pr`) port 1:1 once the target repo has its own `packaging/mcpb/` and `.claude-plugin/plugin/` directories.
  ```

- [ ] **Step 4: Commit.**

  ```bash
  git add CLAUDE.md SYNC.md
  git commit -m "docs: update CLAUDE.md and SYNC.md for plugin packaging"
  ```

---

## Task 17: File follow-up issues

Per §9.4 of the spec, six issues must be filed as part of this work. File them after the PR opens (so they can reference the PR) but before it merges.

**Files:** none (all `gh issue create` commands).

- [ ] **Step 1: File issue: Claude Code slash commands.**

  ```bash
  gh issue create \
    --title "feat: Claude Code slash commands (/vault-orphans, /vault-map, /vault-daily)" \
    --body "Option C from the plugin brainstorm (see docs/superpowers/specs/2026-04-10-claude-plugins-design.md §2).

  Add structural Claude Code commands that do not duplicate existing MCP prompts:

  - \`/vault-orphans\` — run \`get_orphan_notes\` and surface a ranked list.
  - \`/vault-map\` — open the Graph Explorer MCP Apps view for the current note.
  - \`/vault-daily\` — open the daily note for today (create if missing, in write mode).

  Ships as \`.claude-plugin/plugin/commands/*.md\` alongside the existing \`skills/vault-workflow/\`."
  ```

- [ ] **Step 2: File issue: vault-curator subagent + auto-commit hook.**

  ```bash
  gh issue create \
    --title "feat: Claude Code vault-curator subagent + auto-commit hook" \
    --body "Option D from the plugin brainstorm (see docs/superpowers/specs/2026-04-10-claude-plugins-design.md §2).

  Add a \`vault-curator\` subagent that proactively maintains the vault (finds orphans, suggests links, tags). Add a post-write hook that auto-commits writes in non-managed-git mode.

  Ships as \`.claude-plugin/plugin/agents/vault-curator.md\` + \`hooks/*.md\`."
  ```

- [ ] **Step 3: File issue: auto-merge catalog PRs.**

  ```bash
  gh issue create \
    --title "chore: auto-merge catalog bump PRs on green CI" \
    --body "Escalation path if manual review of the catalog bump PR becomes tedious. Extend the \`publish-claude-plugin-pr\` job (see docs/superpowers/specs/2026-04-10-claude-plugins-design.md §7.4) to optionally enable \`gh pr merge --merge --auto\` on the created PR once required checks pass."
  ```

- [ ] **Step 4: File issue: community marketplace submission.**

  ```bash
  gh issue create \
    --title "chore: submit plugin to community marketplaces (claudemarketplaces.com, aitmpl.com, LobeHub)" \
    --body "Tier 2 of #113. Once the \`pvliesdonk/claude-plugins\` catalog has been stable for a few releases, submit \`markdown-vault-mcp\` to the community-run marketplaces. Each has a different submission process — this issue tracks the triage."
  ```

- [ ] **Step 5: File issue: schema tracker.**

  ```bash
  gh issue create \
    --title "chore: track mcpb manifest schema updates beyond v0.4" \
    --body "Long-lived tracker. When the mcpb spec advances past v0.4, update \`packaging/mcpb/manifest.json.in\` and bump \`compatibility.claude_desktop\` accordingly. Watch <https://github.com/anthropics/mcpb/releases> for changes."
  ```

- [ ] **Step 6: File cross-repo port issue against `image-generation-mcp`.**

  ```bash
  gh issue create \
    --repo pvliesdonk/image-generation-mcp \
    --title "chore: port mcpb + Claude Code plugin infra from markdown-vault-mcp" \
    --body "Port \`packaging/mcpb/\` and \`.claude-plugin/plugin/\` from markdown-vault-mcp to this repo. Follow SYNC.md in both repos. Source PR: pvliesdonk/markdown-vault-mcp#<this-PR>."
  ```

---

## Task 18: Pre-release dry-run

Before cutting the first real tag with this packaging, run through the manual checklist to catch anything CI cannot.

**Files:** none (verification task).

- [ ] **Step 1: Build the bundle locally with the current HEAD version.**

  ```bash
  VERSION=$(grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)
  VERSION="$VERSION" ./packaging/mcpb/build.sh
  ls -lh packaging/mcpb/dist/
  ```

  Expected: a `markdown-vault-mcp-<version>.mcpb` file around 30-50 KB.

- [ ] **Step 2: Install the bundle in Claude Desktop (real app).**

  1. Open Claude Desktop.
  2. Drag the `.mcpb` file into the Claude Desktop window (or double-click it from Finder/Explorer).
  3. Verify the configuration form appears with all 14 fields.
  4. Fill in `source_dir` with a test vault path (a small directory of `.md` files).
  5. Save and restart Claude Desktop if prompted.

  Expected: the vault tools appear in the tool list.

- [ ] **Step 3: Run a search from Claude Desktop.**

  Ask Claude: "Search my vault for a common word."

  Expected: ranked results come back. If nothing works, check Claude Desktop's MCP logs for the failure — usually `uv` not on PATH or `MARKDOWN_VAULT_MCP_SOURCE_DIR` still empty.

- [ ] **Step 4: Install the plugin locally in Claude Code.**

  Clone the catalog repo locally first (to test without waiting for a real release):

  ```bash
  git clone https://github.com/pvliesdonk/claude-plugins /tmp/claude-plugins-local
  ```

  In Claude Code:

  ```
  /plugin marketplace add file:///tmp/claude-plugins-local
  /plugin install markdown-vault-mcp@pvliesdonk
  ```

  Expected: install completes and the vault tools appear. This path will only work after Task 14 has pushed the catalog — if it fails with "plugin not found", the catalog does not yet have a `markdown-vault-mcp` entry at the pinned ref.

- [ ] **Step 5: Run a search from Claude Code.**

  Same as Step 3. Expected: results.

- [ ] **Step 6: Uninstall cleanly.**

  ```
  /plugin uninstall markdown-vault-mcp@pvliesdonk
  /plugin marketplace remove pvliesdonk
  ```

  In Claude Desktop, remove the extension via Settings → Extensions.

---

## Task 19: Open PR, land the code, cut a tag

**Files:** none (git/GitHub operations).

- [ ] **Step 1: Confirm the tree is clean and all tests pass.**

  ```bash
  git status
  uv run pytest -x -q
  uv run ruff check --fix .
  uv run ruff format .
  uv run ruff format --check .
  uv run mypy src/
  ```

  Expected: no uncommitted changes (or only the plan doc); all commands exit clean.

- [ ] **Step 2: Push the branch.**

  ```bash
  git push -u origin HEAD
  ```

- [ ] **Step 3: Open the PR.**

  ```bash
  gh pr create \
    --title "feat: Claude Desktop .mcpb and Claude Code plugin distribution" \
    --body "$(cat <<'EOF'
  ## Summary

  - Adds a Claude Desktop \`.mcpb\` bundle (single-file, \`server.type: \"uv\"\`) built and attached to every GitHub Release by new \`build-mcpb\` + \`publish-mcpb\` CI jobs.
  - Adds a Claude Code plugin source under \`.claude-plugin/plugin/\` with a \`vault-workflow\` SKILL.md. The plugin is hosted via \`git-subdir\` from a new \`pvliesdonk/claude-plugins\` catalog repo, bumped automatically on each release via \`publish-claude-plugin-pr\`.
  - Extends the \`release\` job to bump \`server.json\`, \`plugin.json\`, and \`.mcp.json\` in lockstep — all three files carry the same released version.
  - Docs: new \`docs/guides/claude-code-plugin.md\`, new \"Option 0: one-click\" section in \`docs/guides/claude-desktop.md\`, README install tabs, \`CLAUDE.md\` + \`SYNC.md\` updated.

  ## Design doc

  \`docs/superpowers/specs/2026-04-10-claude-plugins-design.md\` (approved).

  ## Test plan

  - [x] \`uv run pytest -x -q\` green
  - [x] \`uv run ruff check --fix && uv run ruff format --check\` clean
  - [x] \`uv run mypy src/\` clean
  - [x] Diff coverage ≥ 80% on new \`packaging/mcpb/\` and \`.claude-plugin/plugin/\` files
  - [x] \`./packaging/mcpb/build.sh\` produces a valid \`.mcpb\` locally
  - [x] Manual install in Claude Desktop verified (Task 18)
  - [x] Manual install in Claude Code verified (Task 18)
  - [ ] First tagged release publishes the bundle and opens a catalog bump PR (verified post-merge)

  Follow-up issues filed: #<commands>, #<subagent>, #<automerge>, #<marketplaces>, #<schema-tracker>, + port issue against image-generation-mcp.
  EOF
  )"
  ```

- [ ] **Step 4: Wait for CI.**

  Monitor the Actions tab. All required checks must go green:

  ```bash
  gh pr checks
  ```

  If any check fails, fix at the root cause — do not bypass with `--admin`. Common failures:
  - `ruff format --check`: re-run `uv run ruff format .` and push.
  - `diff-cover` below 80%: add more assertions to `tests/test_packaging_mcpb.py`.
  - YAML parse error: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"` locally.

- [ ] **Step 5: Address review feedback.**

  Fetch **both** inline review comments and PR-level conversation comments:

  ```bash
  gh api "repos/pvliesdonk/markdown-vault-mcp/pulls/<PR>/comments"
  gh api "repos/pvliesdonk/markdown-vault-mcp/issues/<PR>/comments"
  ```

  Both must be read and resolved before merging.

- [ ] **Step 6: Merge.**

  ```bash
  gh pr merge <PR> --merge --delete-branch
  ```

  (Repo ruleset disallows squash — must use `--merge`.)

- [ ] **Step 7: Manually trigger the release workflow.**

  If `python-semantic-release` does not auto-cut a tag on the new commit, trigger manually:

  ```bash
  gh workflow run release.yml
  ```

- [ ] **Step 8: Verify the release artifacts.**

  Once the release job finishes:

  1. Check <https://github.com/pvliesdonk/markdown-vault-mcp/releases/latest> for the attached `.mcpb` file.
  2. Check <https://github.com/pvliesdonk/claude-plugins/pulls> for the auto-PR.
  3. Merge the catalog PR (`gh pr merge --merge` in that repo).
  4. Run `/plugin marketplace update pvliesdonk && /plugin install markdown-vault-mcp@pvliesdonk` in Claude Code.

  Expected: install succeeds at the new version.

---

## Self-review

**Spec coverage check** (walk through §1-11 of the design doc):

| Spec section | Covered by |
|---|---|
| §1 Goals | Tasks 2-19 (both channels) |
| §2 Scope in/out | Tasks 2-16 in-scope; Task 17 files follow-ups for out-of-scope items |
| §3 Cross-repo architecture | Task 14 (catalog repo) + Tasks 7-10 (plugin source) |
| §4.1 Bundle contents | Tasks 3-6 |
| §4.2 manifest.json | Task 4 |
| §4.3 pyproject + shim | Tasks 3, 5 |
| §4.4 user_config field selection | Task 4 (manifest template) |
| §4.5 Build process | Task 6 (build.sh) + Task 12 (CI) |
| §5.1-5.5 Plugin layout/files | Tasks 7, 8, 9, 10 |
| §6 Marketplace repo | Task 14 |
| §7.1 Release job edit | Task 11 |
| §7.2 build-mcpb | Task 12 |
| §7.3 publish-mcpb | Task 12 |
| §7.4 publish-claude-plugin-pr | Task 13 |
| §7.5 PAT secret | Task 13 Step 1 |
| §8 Documentation updates | Tasks 15, 16 |
| §9.1 Local build test | Task 6 Step 3 |
| §9.2 CI smoke test | Tasks 2-8 (TDD through test file) |
| §9.3 Manual checklist | Task 18 |
| §9.4 Follow-up issues | Task 17 |
| §10 Risks 1 & 2 | Task 1 (verification gate) |
| §10 Risk 3 (PAT) | Task 13 Step 1 + calendar reminder |
| §10 Risks 4-6 | Documented-only; no code action needed |

Every section has a task. No gaps.

**Placeholder scan:** Searched plan for `TBD`, `TODO`, `FIXME`, `fill in`, "appropriate", "similar to Task". None found (only the word "later" which appears in follow-up discussion, not as a placeholder).

**Type consistency:** The test file grows one assertion per task:
- Task 2: `test_cli_main_import_target_exists`
- Task 3: `test_mcpb_server_shim_calls_main_serve`
- Task 4: `test_mcpb_manifest_template_valid_and_complete` + `_load_manifest_template` helper
- Task 5: `test_mcpb_pyproject_template_pins_versioned_package`
- Task 7: `test_claude_code_plugin_json_shape` + `_load_plugin_json` helper
- Task 8: `test_plugin_mcp_json_pinned_and_matches_plugin_version` + `_load_plugin_mcp_json` helper

The `_load_plugin_json` helper is defined in Task 7 and reused in Task 8's parity assertion. The `re` import is added in Task 8; the `json` and `Path` imports from Task 2 cover everything else. `REPO_ROOT`, `MCPB_DIR`, `PLUGIN_DIR` constants defined in Task 2 are used throughout. Consistent.

**Version string consistency:** Plan uses `1.20.1` as the initial committed version in Task 7 and Task 8 (and Task 14 for the catalog), with an explicit Step 1 in Task 7 to read the *real* current version from `pyproject.toml`. The release workflow in Task 11 bumps all three files in one jq step. `.mcp.json` and `plugin.json` parity is enforced by the test in Task 8.
