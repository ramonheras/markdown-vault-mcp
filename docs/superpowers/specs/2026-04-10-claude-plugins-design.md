# Design: Claude Desktop and Claude Code plugin distribution

- **Status:** Approved (brainstorming), pending implementation plan
- **Date:** 2026-04-10
- **Author:** Peter van Liesdonk (with Claude)
- **Scope:** Packaging only — no server code, CLI, or env-var changes.

## 1. Overview and goals

Ship `markdown-vault-mcp` through two first-party plugin channels in addition to
the existing PyPI / Docker / MCP Registry / Linux-package routes:

1. **Claude Desktop** — a single-file `.mcpb` bundle uploaded to each GitHub
   Release, giving desktop users a one-click install with a typed configuration
   form.
2. **Claude Code** — a marketplace-discoverable plugin that registers the MCP
   server via `.mcp.json` and layers a `vault-workflow` skill on top so
   Claude Code uses the vault tools effectively by default.

Both channels are packaging, not feature work. The server, CLI, and env-var
contract stay unchanged. Both pin to the same semantic version produced by
`python-semantic-release` and publish automatically as part of the existing
release pipeline. Discoverability issue #113 (Tier 2/3 directories) is unrelated
and stays open.

**Non-goals:** MCP Registry changes (already live), replacing the manual setup
in `docs/guides/claude-desktop.md` (we add an "Option 0" section, not a
rewrite), shipping commands/agents/hooks in the Claude Code plugin (deferred —
see §9).

## 2. Scope

**In scope (this spec):**

- `packaging/mcpb/` directory with manifest template, `pyproject.toml` template,
  and entry shim for the `.mcpb` bundle.
- `.claude-plugin/plugin/` directory in the `markdown-vault-mcp` repo
  containing the Claude Code plugin source (`plugin.json`, `.mcp.json`,
  `skills/vault-workflow/SKILL.md`, `README.md`).
- New `pvliesdonk/claude-plugins` repository, bootstrapped with
  `.claude-plugin/marketplace.json` referencing the plugin via `git-subdir`.
- Three new jobs in `.github/workflows/release.yml` (`build-mcpb`,
  `publish-mcpb`, `publish-claude-plugin-pr`) wired into the existing release
  graph, plus a one-line edit to the existing `release` job's manifest bump.
- Documentation: "Option 0: one-click" section added to
  `docs/guides/claude-desktop.md`; new `docs/guides/claude-code-plugin.md`;
  `README.md` install section updated with both plugin commands; `docs/index.md`
  and `docs/installation.md` updated; `CLAUDE.md` release gate extended;
  `SYNC.md` updated for the cross-repo port.
- Local build script and CI smoke test for the new packaging files.

**Out of scope (follow-up issues filed as part of this work):**

- Claude Code slash commands (`/vault-orphans`, `/vault-map`, `/vault-daily`) —
  option C from the brainstorm.
- Claude Code `vault-curator` subagent and auto-commit hook — option D from the
  brainstorm.
- Auto-merge on green CI for catalog bump PRs — escalation path if manual
  review becomes tedious.
- Submission to community marketplaces (claudemarketplaces.com, aitmpl.com,
  LobeHub, etc.) — add to Tier 2 of issue #113 once the catalog is stable.
- Cross-repo port of plugin infrastructure to `image-generation-mcp` per
  SYNC.md.
- Long-lived tracker for future mcpb manifest schema updates beyond v0.4.

## 3. Cross-repo architecture

Two repositories, with a clear separation between plugin source and catalog.

```
pvliesdonk/markdown-vault-mcp                 (source of truth)
├── src/markdown_vault_mcp/                   # existing Python package
├── .claude-plugin/
│   └── plugin/                               # Claude Code plugin source
│       ├── .claude-plugin/
│       │   └── plugin.json                   # plugin metadata (version bumped by release)
│       ├── .mcp.json                         # MCP server launch config
│       ├── skills/
│       │   └── vault-workflow/
│       │       └── SKILL.md                  # when/how to use vault tools
│       └── README.md
├── packaging/
│   └── mcpb/                                 # Claude Desktop bundle source
│       ├── manifest.json.in                  # template, ${VERSION} substituted at build
│       ├── pyproject.toml.in                 # template, pins markdown-vault-mcp[all]==${VERSION}
│       ├── src/
│       │   └── server.py                     # 3-line shim: main(["serve"])
│       └── build.sh                          # local build/validate helper
├── tests/
│   └── test_packaging_mcpb.py                # smoke test
└── .github/workflows/release.yml             # extended with 3 new jobs + 1 edit


pvliesdonk/claude-plugins                     (new catalog repo — no plugin code)
├── .claude-plugin/
│   └── marketplace.json                      # references plugin via git-subdir + pinned ref
├── README.md
└── LICENSE
```

**Rationale:**

- **Plugin source next to the server code** means one PR can touch both sides
  when the env-var contract changes; no "update plugin.json separately" drift.
- **The catalog repo is 90% `marketplace.json`.** Adding a second plugin later
  (e.g. `image-generation-mcp` via SYNC.md) is a one-line PR, not a new repo.
- **`git-subdir` sparse-clones** just `.claude-plugin/plugin/` out of the main
  repo, so installing the plugin does not pull down `src/`, `tests/`, or the
  git history. This is documented in the Claude Code plugin-sources reference.
- **Tag-based pinning** (`ref: "vX.Y.Z"`) gives reproducible installs and lets
  the catalog follow at its own cadence if we ever need to hold back a bad
  release.

**Install flow for end users:**

Claude Desktop: download `markdown-vault-mcp-<version>.mcpb` from the GitHub
Release → double-click → Claude Desktop opens the config form → fill
`source_dir` → done.

Claude Code:

```
/plugin marketplace add pvliesdonk/claude-plugins
/plugin install markdown-vault-mcp@pvliesdonk
# then set MARKDOWN_VAULT_MCP_SOURCE_DIR in the shell profile (documented)
```

The marketplace name is **`pvliesdonk`** — author-branded, room to grow, not on
the reserved list.

## 4. Claude Desktop `.mcpb` bundle

Approximately 30 KB once zipped.

### 4.1 Bundle contents

```
markdown-vault-mcp-<version>.mcpb   (ZIP)
├── manifest.json                   # rendered from manifest.json.in at build time
├── pyproject.toml                  # rendered from pyproject.toml.in at build time
└── src/
    └── server.py                   # committed as-is
```

### 4.2 `manifest.json`

Rendered from `packaging/mcpb/manifest.json.in` via `envsubst` with `${VERSION}`
substituted. Uses `server.type: "uv"` (manifest spec v0.4) so the host manages
Python and dependencies; the bundle itself carries no wheels.

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
        "MARKDOWN_VAULT_MCP_SOURCE_DIR":      "${user_config.source_dir}",
        "MARKDOWN_VAULT_MCP_READ_ONLY":       "${user_config.read_only}",
        "MARKDOWN_VAULT_MCP_SERVER_NAME":     "${user_config.server_name}",
        "MARKDOWN_VAULT_MCP_EXCLUDE":         "${user_config.exclude_patterns}",
        "MARKDOWN_VAULT_MCP_STATE_PATH":      "${user_config.state_path}",
        "EMBEDDING_PROVIDER":                 "${user_config.embedding_provider}",
        "OLLAMA_HOST":                        "${user_config.ollama_host}",
        "MARKDOWN_VAULT_MCP_OLLAMA_MODEL":    "${user_config.ollama_model}",
        "MARKDOWN_VAULT_MCP_FASTEMBED_MODEL": "${user_config.fastembed_model}",
        "OPENAI_API_KEY":                     "${user_config.openai_api_key}",
        "MARKDOWN_VAULT_MCP_GIT_REPO_URL":    "${user_config.git_repo_url}",
        "MARKDOWN_VAULT_MCP_GIT_TOKEN":       "${user_config.git_token}",
        "MARKDOWN_VAULT_MCP_GIT_PUSH_DELAY_S":"${user_config.git_push_delay_s}",
        "FASTMCP_LOG_LEVEL":                  "${user_config.log_level}"
      }
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

The `user_config` object (elided above) is defined in full in §4.4.

The `claude_desktop` minimum version is provisional — the implementation plan
must verify which Claude Desktop version first supports `manifest_version 0.4`
with `server.type: "uv"` and adjust this constraint. See §10 Risk 1.

### 4.3 `pyproject.toml` and entry shim

`packaging/mcpb/pyproject.toml.in` (rendered at build time):

```toml
[project]
name = "markdown-vault-mcp-mcpb"
version = "${VERSION}"
requires-python = ">=3.10"
dependencies = [
  "markdown-vault-mcp[all]==${VERSION}",
]
```

`packaging/mcpb/src/server.py` (committed as-is, not templated):

```python
from markdown_vault_mcp.cli import main

if __name__ == "__main__":
    main(["serve"])
```

The `[all]` extra pulls in embeddings, git, fetch, and auth dependencies. `uv`
on the host resolves the tree on install; FastEmbed's ONNX runtime is
platform-specific, but `uv` fetches the right wheel per platform, so the single
`.mcpb` file still works on macOS/Windows/Linux Intel/ARM without per-platform
builds.

### 4.4 `user_config` field selection

Fourteen fields total. Only `source_dir` is required. Every other field has a
sensible default or can be left blank.

| Key | Type | Required | Default | Sensitive | Notes |
|---|---|---|---|---|---|
| `source_dir` | directory | **yes** | `${DOCUMENTS}/Vault` | — | The only truly required input. |
| `read_only` | boolean | no | `true` | — | Safe default; user opts into writes. |
| `server_name` | string | no | `markdown-vault-mcp` | — | Shown in Claude's tool list. |
| `exclude_patterns` | string | no | `.obsidian/**,.trash/**,.git/**` | — | CSV glob. |
| `state_path` | directory | no | *(empty)* | — | Blank uses `.markdown_vault_mcp/` next to the vault. |
| `embedding_provider` | string | no | *(empty = disabled)* | — | `fastembed` / `ollama` / `openai`. Allowed values listed in the field `description`. |
| `fastembed_model` | string | no | `BAAI/bge-small-en-v1.5` | — | |
| `ollama_host` | string | no | `http://localhost:11434` | — | |
| `ollama_model` | string | no | `nomic-embed-text` | — | |
| `openai_api_key` | string | no | *(empty)* | **yes** | Stored in OS keychain by the host. |
| `git_repo_url` | string | no | *(empty)* | — | Enables managed-git mode. |
| `git_token` | string | no | *(empty)* | **yes** | PAT; only relevant with `git_repo_url`. |
| `git_push_delay_s` | number | no | `30` | — | `min: 0`, `max: 3600`. |
| `log_level` | string | no | `INFO` | — | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |

**Fields deliberately omitted from `user_config`** (kept as plain env vars —
power users who need them edit the generated host MCP config or set shell env
vars): `INDEX_PATH`, `EMBEDDINGS_PATH` (derived from `STATE_PATH`),
`INDEXED_FIELDS`, `REQUIRED_FIELDS`, `ATTACHMENT_EXTENSIONS`,
`MAX_ATTACHMENT_SIZE_MB`, `TEMPLATES_FOLDER`, `PROMPTS_FOLDER`,
`GIT_COMMIT_NAME`, `GIT_COMMIT_EMAIL`, `GIT_USERNAME`, `GIT_PULL_INTERVAL_S`,
`GIT_LFS`, `FASTEMBED_CACHE_DIR`, `OLLAMA_CPU_ONLY`, `APP_DOMAIN`,
`EVENT_STORE_URL`, all OIDC/auth vars (HTTP-only — irrelevant for stdio
plugins), `BEARER_TOKEN`.

That is roughly 27 additional env vars (18 named above plus nine OIDC/auth
variables). The form exposes only what a first-time desktop user actually
tunes. Advanced users are pointed at `docs/configuration.md`.

### 4.5 Build process

Executed by the `build-mcpb` CI job (§7) and also by the local helper
`packaging/mcpb/build.sh`:

```bash
npm install -g @anthropic-ai/mcpb@latest
mkdir -p build/mcpb/src
VERSION="${VERSION:-dev}" envsubst < packaging/mcpb/manifest.json.in   > build/mcpb/manifest.json
VERSION="${VERSION:-dev}" envsubst < packaging/mcpb/pyproject.toml.in  > build/mcpb/pyproject.toml
cp packaging/mcpb/src/server.py build/mcpb/src/server.py

mcpb validate build/mcpb/manifest.json
mcpb pack build/mcpb "dist/markdown-vault-mcp-${VERSION}.mcpb"
```

`mcpb validate` enforces the schema before packing; a bad manifest fails the
build immediately.

## 5. Claude Code plugin

### 5.1 Plugin layout

```
.claude-plugin/plugin/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json
├── skills/
│   └── vault-workflow/
│       └── SKILL.md
└── README.md
```

### 5.2 `plugin.json`

Committed as a concrete file in the repo (not a template). Version is bumped
in place by the release workflow in lockstep with the package — see §7.1.
Initial committed value is whatever the then-current release is:

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

### 5.3 `.mcp.json`

Single-server config, delegates to `uvx`. Committed as a concrete file (not a
template); the version string is bumped in place by the release workflow in
lockstep with `plugin.json` — see §7.1. Initial committed value matches the
then-current release:

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

Pinning the version in `--from` ensures the installed plugin always runs the
same server version it was tagged against — no accidental drift to a newer
PyPI release mid-session. The `[all]` extra brings in embeddings, git, fetch,
and auth dependencies. Power users can override `args` in their personal
Claude Code settings if they want the slim install or a floating version.

**Prereq:** `uv` must be installed on the user's machine. Documented in the
plugin `README.md` and in the new `docs/guides/claude-code-plugin.md`.

The `${VAR:-default}` shell-style substitution above depends on whether
Claude Code supports shell-default syntax in `.mcp.json` env values. If not, the
fallback is bare `${VAR}` plus a prominent "set this env var first" block in
the README. This is a verification step in the implementation plan — see §10
Risk 2.

### 5.4 `skills/vault-workflow/SKILL.md`

The value-add beyond raw tool registration. Outline:

```markdown
---
name: vault-workflow
description: Use when the user asks you to search, read, or reason about notes
  in their markdown vault — guides when to use which vault tool and how to
  chain them for good results.
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
  similar notes, folder peers, and tags in one call — usually enough to answer
  without reading the file.
- Only call `read` when the user asks for the text itself or when
  `get_context` does not give enough signal.

## Link-graph questions
- "What notes reference X?" → `get_backlinks`.
- "What does this note link to?" → `get_outlinks`.
- "How are these two notes connected?" → `get_connection_path`.
- "What is orphaned?" → `get_orphan_notes`.
- "What is most cited?" → `get_most_linked`.

## Writes (only if read-only mode is disabled)
- Prefer `edit` over `write` for targeted changes — it fails safely if the
  old text is not unique, preventing accidental overwrites.
- Use `rename(update_links=True)` for moves, never `write` to new path plus
  `delete` old path — the `update_links` flag repairs internal references.
- Never call `reindex` after writes; the server updates its index inline.

## Do not
- Do not use `list_documents` as a search substitute — it is a flat
  enumeration, not ranked.
- Do not read a note and then re-search for it; remember the path from the
  first result.
```

### 5.5 `README.md`

One page: prereqs (`uv` install), install command, setting
`MARKDOWN_VAULT_MCP_SOURCE_DIR`, link to the main documentation site, brief
list of the tools it exposes. Does not duplicate `docs/tools/index.md`.

## 6. Marketplace repository (`pvliesdonk/claude-plugins`)

New repo. Minimal contents:

```
pvliesdonk/claude-plugins/
├── .claude-plugin/
│   └── marketplace.json
├── README.md
└── LICENSE                # MIT
```

### 6.1 `marketplace.json`

Bumped by auto-PR on each release of `markdown-vault-mcp`:

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

The `ref` and top-level `version` are both bumped by each release. The
`metadata.version` field of the marketplace itself advances lazily — only when
multiple plugins change together.

### 6.2 Future expansion

When `image-generation-mcp` ships a plugin (tracked by a follow-up issue per
SYNC.md), it is added as a second entry under `plugins` in the same file. One
PR, one added block, no structural change.

## 7. Release pipeline wiring

All changes in `.github/workflows/release.yml`. The existing `release` job
gains one edit; three new jobs are added and slot in after `release` runs.

### 7.1 Edit to existing `release` job

The "Update server.json to released version" step is extended to also bump the
plugin manifest atomically, so every tag is internally consistent:

```yaml
- name: Update versioned manifests to released version
  if: steps.release.outputs.released == 'true'
  env:
    VERSION: ${{ steps.release.outputs.version }}
  run: |
    # server.json (existing logic, unchanged)
    jq --arg v "$VERSION" '
      .version = $v |
      .packages |= map(
        if .registryType == "pypi" then .version = $v
        elif .registryType == "oci" then .identifier = ("ghcr.io/pvliesdonk/markdown-vault-mcp:v" + $v)
        else . end
      )
    ' server.json > server.json.tmp && mv server.json.tmp server.json

    # plugin.json (new)
    jq --arg v "$VERSION" '.version = $v' \
      .claude-plugin/plugin/.claude-plugin/plugin.json > plugin.json.tmp
    mv plugin.json.tmp .claude-plugin/plugin/.claude-plugin/plugin.json

    # .mcp.json — keep the pinned --from spec in lockstep with plugin.json (new)
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

### 7.2 New job: `build-mcpb`

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
        mcpb pack build/mcpb "dist/markdown-vault-mcp-${VERSION}.mcpb"
    - uses: actions/upload-artifact@v4
      with:
        name: mcpb-bundle
        path: dist/markdown-vault-mcp-*.mcpb
```

### 7.3 New job: `publish-mcpb`

Attaches the `.mcpb` to the GitHub Release.

```yaml
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
      run: gh release upload "${{ needs.release.outputs.tag }}" dist/markdown-vault-mcp-*.mcpb --clobber
      env:
        GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 7.4 New job: `publish-claude-plugin-pr`

Opens a PR against `pvliesdonk/claude-plugins` to bump the plugin entry:

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
          Auto-generated bump from [markdown-vault-mcp#${{ needs.release.outputs.tag }}](https://github.com/pvliesdonk/markdown-vault-mcp/releases/tag/${{ needs.release.outputs.tag }}).
        commit-message: "chore: bump markdown-vault-mcp to v${{ needs.release.outputs.version }}"
```

### 7.5 New secret

`CLAUDE_PLUGINS_PAT` — a **fine-grained** PAT scoped to `pvliesdonk/claude-plugins`
with `contents: write` and `pull-requests: write`. Preferred over a classic
PAT with blanket `repo` scope. Creation added to the implementation plan.

### 7.6 Updated job graph

```
release ──┬─> publish-pypi ─┐
          ├─> publish-docker ┤─> publish-registry
          ├─> publish-linux-packages
          ├─> build-mcpb ──> publish-mcpb
          └─> publish-claude-plugin-pr
```

Three new jobs run in parallel with the existing ones; no new bottleneck.

## 8. Documentation updates

All shipped in the same PR(s) as the packaging work, per the repo's
Documentation Discipline rule.

- **`README.md`** — add an "Install" section near the top with three tabs:
  one-click (Claude Desktop), Claude Code plugin, PyPI/Docker (existing).
- **`docs/guides/claude-desktop.md`** — insert **Option 0: one-click install
  (.mcpb)** before the existing Step 1. The existing four steps stay as
  "Option 1: Manual config" for users who need advanced control (multiple
  vaults, OIDC, etc.) the `user_config` form does not expose.
- **`docs/guides/claude-code-plugin.md`** — *new file*. Walkthrough: prereqs
  (`uv`), `/plugin marketplace add pvliesdonk/claude-plugins`,
  `/plugin install markdown-vault-mcp@pvliesdonk`, setting
  `MARKDOWN_VAULT_MCP_SOURCE_DIR` in shell profile, verifying the `search`
  tool appears, pointer to the SKILL.md-driven workflow.
- **`docs/installation.md`** — add two rows to the install methods table:
  "Claude Desktop (.mcpb)" and "Claude Code (plugin)".
- **`docs/index.md`** — feature list and "Works with" row mention both plugin
  formats.
- **`docs/configuration.md`** — add a callout explaining which env vars are
  exposed in the Claude Desktop form vs. which require direct env-var editing.
- **`CLAUDE.md`** — extend Documentation Discipline with the new files as
  user-facing surfaces that must stay in sync. Add a Hard PR Acceptance Gate
  bullet about plugin release artifacts.
- **`SYNC.md`** — add `packaging/mcpb/` and `.claude-plugin/plugin/` to the
  pending ports section for `image-generation-mcp`. The plugin infrastructure
  is domain-independent and cross-postable.
- **`CHANGELOG.md`** — auto-generated by `python-semantic-release`; no manual
  edit.

## 9. Testing, verification, and follow-up issues

### 9.1 Local build test

`packaging/mcpb/build.sh` (new) mirrors the CI job: renders templates with
`VERSION=dev`, runs `mcpb validate` and `mcpb pack`. Fast feedback without
pushing a tag.

### 9.2 CI smoke test

A new test file `tests/test_packaging_mcpb.py` that:

1. Imports `from markdown_vault_mcp.cli import main` (verifies the shim's
   import target exists).
2. Reads `packaging/mcpb/src/server.py` and asserts it calls
   `main(["serve"])`.
3. Parses `packaging/mcpb/manifest.json.in` as JSON (with `${VERSION}`
   replaced by a placeholder literal) and asserts required mcpb fields are
   present.
4. Parses `.claude-plugin/plugin/.claude-plugin/plugin.json` and asserts its
   `name` matches the package name.
5. Parses `.claude-plugin/plugin/.mcp.json` and asserts the
   `markdown-vault-mcp` entry contains `--from markdown-vault-mcp[all]==<ver>`
   in its `args` and that the `<ver>` matches the sibling `plugin.json`
   version (catches release-workflow bugs that bump only one file).

Keeps patch coverage ≥ 80% for the new `packaging/mcpb/` files and catches
drift between the package CLI and the plugin shim.

### 9.3 Manual pre-release checklist

Added to `docs/deployment/` or the release runbook:

1. Tag a dry-run release to a scratch branch.
2. Download the `.mcpb` artifact.
3. Install it in Claude Desktop on macOS, verify the config form renders with
   all 14 fields and the `source_dir` picker works.
4. Start the server, run a `search` call, verify results.
5. In Claude Code, `/plugin marketplace add file:///path/to/local/claude-plugins/clone`
   and `/plugin install markdown-vault-mcp@pvliesdonk`, verify the server
   registers and tools appear.

### 9.4 Follow-up issues filed as part of this work

| # | Title | Purpose |
|---|---|---|
| 1 | `feat: Claude Code slash commands (/vault-orphans, /vault-map, /vault-daily)` | Option C from the brainstorm. Structural commands that do not duplicate MCP prompts. |
| 2 | `feat: Claude Code vault-curator subagent + auto-commit hook` | Option D from the brainstorm. Proactive vault maintenance. |
| 3 | `chore: auto-merge marketplace catalog PRs on green CI` | Escalation path if manual review becomes tedious. |
| 4 | `chore: submit plugin to community marketplaces` | Add to Tier 2 of issue #113 once the catalog is stable. |
| 5 | `chore: port mcpb + Claude Code plugin infra to image-generation-mcp` | Cross-repo port per SYNC.md (filed against the other repo). |
| 6 | `chore: track mcpb manifest schema updates beyond v0.4` | Long-lived tracker to revisit when the spec advances. |

## 10. Risks and open questions

1. **`server.type: "uv"` adoption in shipping Claude Desktop.** The mcpb
   MANIFEST spec labels `type: "uv"` as "v0.4+" and promises "no user Python
   installation required", implying the host provides `uv`. What is not
   documented is *which* Claude Desktop version first supports
   `manifest_version 0.4`. **Mitigation:** the implementation plan's first
   task is to empirically verify this against the latest Claude Desktop on
   macOS and Windows. If 0.4 is not yet supported, the fallback is
   `server.type: "python"` with vendored wheels in `server/lib/`. That path
   cannot reasonably bundle FastEmbed (ONNX runtime is platform-specific and
   models are GB-sized), so the fallback `.mcpb` ships keyword search only,
   and semantic search is documented as a "install from PyPI directly" path.
   This is the single most important verification before implementation.

2. **`${VAR:-default}` substitution in Claude Code `.mcp.json`.** The env-var
   forwarding pattern in §5.3 assumes Claude Code supports shell-style default
   substitution in `env` values. If only bare `${VAR}` is supported, users get
   an empty string when the env var is unset, which breaks `source_dir`.
   **Mitigation:** verify against the Claude Code plugins reference during
   implementation. Fall back to bare `${MARKDOWN_VAULT_MCP_SOURCE_DIR}` plus a
   prominent "you must set this env var first" block in the plugin README.

3. **`CLAUDE_PLUGINS_PAT` secret management.** Fine-grained PATs expire. A
   silently-expired token makes `publish-claude-plugin-pr` fail but the
   PyPI / Docker / Registry jobs succeed, leaving the catalog stale without
   loud notification. **Mitigation:** the auto-PR job runs last in its branch
   of the graph; a failure shows red on the Actions tab. Consider a webhook
   alert on that specific job failure in a follow-up if it becomes a problem.

4. **Marketplace name collision.** `pvliesdonk` is not on the reserved list,
   but Claude Code install uses `name@marketplace`, and if two marketplaces
   named `pvliesdonk` existed in a user's install it would cause confusion.
   Low risk given it is the author's GitHub username. No action beyond
   choosing a distinctive name.

5. **Plugin cache staleness on user machines.** Claude Code caches plugins at
   `~/.claude/plugins/cache/` and users need `/plugin update` to pick up new
   `git-subdir` refs. Users who never update stay pinned. **Mitigation:**
   document the update command prominently in the plugin README and the
   Claude Code guide.

6. **Scope creep into workflow territory.** Once `vault-workflow` ships, the
   temptation will be to grow it into the Zettelkasten guide. **Mitigation:**
   the skill stays tool-usage-focused ("when to use hybrid search"); the
   Zettelkasten guide stays content-focused ("how to structure your vault").
   This boundary is captured in §2 scope.

## 11. Approval

Brainstorming sessions walked through scope (single spec for both channels),
bundling strategy (`server.type: "uv"`), Claude Code plugin scope (thin
wrapper + one skill), marketplace hosting (separate `pvliesdonk/claude-plugins`
repo), and release automation (auto-PR to the catalog). All sections above
were reviewed section-by-section and approved before writing this document.

Next step: invoke `superpowers:writing-plans` to turn this design into a
concrete implementation plan with verification checkpoints, starting with the
§10 Risk 1 verification task.
