# Step 6: Scholar-MCP Retrofit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `fastmcp-server-template`'s CLI from argparse to typer (cut v1.0.3), then retrofit `scholar-mcp` onto that template + `fastmcp-pvl-core` in a single rebuild PR.

**Architecture:** Two sequential parts. Part A is a small template PR that replaces `cli.py.jinja` with a typer starter + adds typer to deps. Part B is a Step 5–shaped rebuild PR on scholar: `copier copy --overwrite` against v1.0.3, restore ~40 Class A domain files, rewrite `config.py` / `mcp_server.py` / `cli.py` to compose core primitives and use typer.

**Tech Stack:** copier ≥9, typer ≥0.12, fastmcp-pvl-core ≥1.0,<2, fastmcp[tasks] ≥3,<4, python-semantic-release, GitHub Actions.

**Working repos:**
- `/mnt/code/fastmcp-server-template` — Part A lands here on branch `feat/typer-cli`.
- `/mnt/code/scholar-mcp` — Part B lands here on branch `chore/adopt-fastmcp-template`.
- `/tmp/scholar-replay` — scratch replay destination for Part B Phase 1.

**Spec:** `docs/superpowers/specs/2026-04-21-step6-scholar-retrofit-design.md`

---

## Part A — Template typer rewrite

### Task A1: Branch + inspect current argparse cli.py.jinja

**Files:**
- No edits yet; just orientation.

- [ ] **Step 1: Clean branch on template**

```bash
cd /mnt/code/fastmcp-server-template
git checkout main
git pull --ff-only
git checkout -b feat/typer-cli
```

- [ ] **Step 2: Inspect current cli.py.jinja**

```bash
cat src/{{python_module}}/cli.py.jinja
wc -l src/{{python_module}}/cli.py.jinja
```

Expected: ~85 lines of argparse + `serve` subcommand + local `_normalise_http_path` wrapper.

### Task A2: Rewrite cli.py.jinja to typer

**Files:**
- Replace: `src/{{python_module}}/cli.py.jinja`

- [ ] **Step 1: Replace file contents**

Use `Write` tool with:

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
    verbose: bool = typer.Option(
        False, "-v", "--verbose", help="Enable debug logging."
    ),
) -> None:
    """Root callback — bootstraps logging for every subcommand."""
    configure_logging_from_env(verbose=verbose)


@app.command()
def serve(
    transport: str = typer.Option(
        "stdio", help="MCP transport (stdio / http / sse)."
    ),
    host: str = typer.Option("0.0.0.0", help="Bind host (http only)."),
    port: int = typer.Option(8000, help="Bind port (http only)."),
    http_path: str | None = typer.Option(
        None,
        "--http-path",
        "--path",
        help=(
            f"Mount path (http only, default: ${_ENV_PREFIX}_HTTP_PATH or /mcp)."
        ),
    ),
) -> None:
    """Run the MCP server."""
    import os

    from {{ python_module }}.mcp_server import build_event_store, create_server

    server = create_server(transport=transport)

    if transport == "http":
        import uvicorn

        path = normalise_http_path(
            http_path or os.environ.get(f"{_ENV_PREFIX}_HTTP_PATH")
        )
        uvicorn.run(
            server.http_app(path=path, event_store=build_event_store()),
            host=host,
            port=port,
        )
    else:
        server.run(transport=transport)


def main() -> None:
    """CLI entry point — used by ``[project.scripts]`` in pyproject.toml."""
    app()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify replace succeeded**

```bash
grep -n 'typer\|argparse' /mnt/code/fastmcp-server-template/src/{{python_module}}/cli.py.jinja | head -5
```

Expected: all `typer` imports visible; zero `argparse` references.

### Task A3: Add typer to pyproject.toml.jinja dependencies

**Files:**
- Modify: `pyproject.toml.jinja` (add typer to `[project].dependencies`)

- [ ] **Step 1: Add typer**

Use `Edit`:

- old_string: the `fastmcp-pvl-core>=1.0,<2` dependency line (or whichever identifies the existing deps)
- new_string: add `typer>=0.12` immediately after the core dep

Concretely, locate the deps block:

```toml
dependencies = [
    "fastmcp-pvl-core>=1.0,<2",
    # PROJECT-DEPS-START — add domain dependencies below; kept across copier update
    # PROJECT-DEPS-END
]
```

Change to:

```toml
dependencies = [
    "fastmcp-pvl-core>=1.0,<2",
    "typer>=0.12",
    # PROJECT-DEPS-START — add domain dependencies below; kept across copier update
    # PROJECT-DEPS-END
]
```

- [ ] **Step 2: Verify**

```bash
grep -n 'typer\|fastmcp-pvl-core' /mnt/code/fastmcp-server-template/pyproject.toml.jinja | head -5
```

Expected: both pinned, in that order.

### Task A4: Smoke render + gate locally

**Files:**
- None (render into `/tmp/template-typer-smoke`).

- [ ] **Step 1: Render**

```bash
rm -rf /tmp/template-typer-smoke && mkdir /tmp/template-typer-smoke
cd /mnt/code/fastmcp-server-template
git add src/{{python_module}}/cli.py.jinja pyproject.toml.jinja
git commit -m "wip: typer smoke" --no-verify
copier copy --trust --defaults --vcs-ref HEAD \
  --data project_name=example-mcp --data pypi_name=example-mcp \
  --data python_module=example_mcp --data env_prefix=EXAMPLE_MCP \
  --data human_name='Example MCP' --data domain_description='Example MCP server' \
  --data github_org=example --data docker_registry=ghcr.io/example \
  /mnt/code/fastmcp-server-template /tmp/template-typer-smoke 2>&1 | tail -3
```

Expected: copier render OK, files created.

- [ ] **Step 2: Gate rendered project**

```bash
cd /tmp/template-typer-smoke
uv sync --extra dev 2>&1 | tail -3
uv run ruff check . 2>&1 | tail -3
uv run ruff format --check . 2>&1 | tail -3
uv run mypy src/ 2>&1 | tail -3
uv run pytest -x -q 2>&1 | tail -5
```

Expected: all clean. If `tests/test_smoke.py` imports any argparse-era helper (e.g. `_normalise_http_path` from cli.py), it will fail; fix by updating the test to import from `fastmcp_pvl_core` or dropping the direct import.

- [ ] **Step 3: CLI help works**

```bash
cd /tmp/template-typer-smoke
uv run example-mcp --help | head -20
uv run example-mcp serve --help | head -20
```

Expected: typer help output showing `--verbose`, `serve` subcommand, `--transport`, `--host`, `--port`, `--http-path/--path`.

- [ ] **Step 4: Squash wip commit into clean commit**

```bash
cd /mnt/code/fastmcp-server-template
git reset --soft HEAD~1
git commit -m "$(cat <<'EOF'
feat(cli): rewrite template CLI from argparse to typer

Template's cli.py.jinja now uses typer.Typer with a root callback
that bootstraps logging and a serve subcommand that matches today's
behaviour (transport/host/port/http-path).  --http-path keeps --path
as an alias for backward compat.

Adds typer>=0.12 to [project].dependencies in pyproject.toml.jinja.
No changes to fastmcp-pvl-core — typer is a direct dep of generated
projects only.

Future projects rendered from v1.0.3+ get typer out of the box.  MV
and IG will see this as a diff on their next `copier update` pass
(not forced; they can adopt or skip).
EOF
)"
rm -rf /tmp/template-typer-smoke
```

### Task A5: Push + PR + merge + cut v1.0.3

**Files:**
- No edits.

- [ ] **Step 1: Push branch**

```bash
cd /mnt/code/fastmcp-server-template
git push -u origin feat/typer-cli
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(cli): rewrite template CLI from argparse to typer" --body "$(cat <<'EOF'
## Summary

Replace ``cli.py.jinja``'s argparse + single-function layout with a ``typer.Typer`` app that has a root callback (handles logging) and a ``serve`` subcommand.  Adds ``typer>=0.12`` to generated-project dependencies.

## Why

- User preference — typer/click is preferred over argparse for future projects (surfaced during Step 6 scholar-mcp brainstorm).
- Scholar already uses click; its retrofit will rewrite to typer and benefits from the template matching that convention from v1.0.3 onward.
- Template self-test CI already covers rendered-project build + gate, so the rewrite gets validated automatically.

## Non-goals

- No typer helpers in fastmcp-pvl-core.  Core stays minimal.
- No cascading rewrite of MV or IG CLIs — they'll see typer as a diff on their next ``copier update`` and can adopt or skip per cadence.

## Test plan

- [x] Render smoke: rendered project gates clean (ruff/format/mypy/pytest).
- [x] ``example-mcp --help`` and ``example-mcp serve --help`` show typer's help with all options preserved.
- [ ] CI green on this PR.
- [ ] After merge: cut template v1.0.3 (or next patch PSR picks), verify it on GH releases.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Wait for CI**

```bash
gh pr checks --watch
```

Expected: all required checks pass.

- [ ] **Step 4: Merge (after user go-ahead)**

Stop here and report the PR URL.  **User merges manually** so the merge decision stays explicit.

- [ ] **Step 5: Trigger template release workflow**

After merge, trigger PSR to cut `v1.0.3`:

```bash
cd /mnt/code/fastmcp-server-template
git checkout main && git pull --ff-only
gh workflow run release.yml
sleep 5
RUN_ID=$(gh run list --workflow release.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID"
```

Expected: PSR cuts the next patch release (likely `v1.0.3`).  If PSR reports `No release will be made`, re-trigger with `gh workflow run release.yml -f force=patch`.

- [ ] **Step 6: Verify tag**

```bash
git -C /mnt/code/fastmcp-server-template fetch --tags origin
git -C /mnt/code/fastmcp-server-template tag --sort=-v:refname | head -3
```

Expected: `v1.0.3` (or higher) at top of list.  **Record the exact tag** — Part B pins to it.

### Task A6: Record template version for Part B

**Files:**
- Create: `/tmp/scholar-template-version.txt`

- [ ] **Step 1: Write the pinned tag to a scratch file**

```bash
FINAL_TAG=$(git -C /mnt/code/fastmcp-server-template tag --sort=-v:refname | head -1)
echo "$FINAL_TAG" > /tmp/scholar-template-version.txt
cat /tmp/scholar-template-version.txt
```

Expected: a single line with `v1.0.3` (or whichever tag PSR cut).

---

## Part B — Scholar retrofit

### Task B1: Create scholar copier answers file

**Files:**
- Create: `/tmp/scholar-answers.yml`

- [ ] **Step 1: Write answers**

```bash
cat > /tmp/scholar-answers.yml <<'EOF'
project_name: scholar-mcp
pypi_name: pvliesdonk-scholar-mcp
python_module: scholar_mcp
env_prefix: SCHOLAR_MCP
human_name: Scholar MCP
domain_description: FastMCP server for Semantic Scholar with OpenAlex enrichment and docling PDF conversion
github_org: pvliesdonk
docker_registry: ghcr.io/pvliesdonk
EOF
python -c "import yaml; d = yaml.safe_load(open('/tmp/scholar-answers.yml')); assert len(d) == 8; print('ok')"
```

Expected: `ok`.

### Task B2: Prepare scratch replay dir + scholar branch + pre-retrofit tag

**Files:**
- Create: `/tmp/scholar-replay/` (empty).
- Branch: `/mnt/code/scholar-mcp` → `chore/adopt-fastmcp-template`.
- Tag: `step6-pre-retrofit` at HEAD of branch.

- [ ] **Step 1: Wipe + init scratch dir**

```bash
rm -rf /tmp/scholar-replay
mkdir -p /tmp/scholar-replay
git -C /tmp/scholar-replay init -q
```

- [ ] **Step 2: Sync scholar main**

```bash
cd /mnt/code/scholar-mcp
git checkout main
git pull --ff-only
git status
```

Expected: clean tree, on `main`, up to date with origin.

- [ ] **Step 3: Branch + tag**

```bash
cd /mnt/code/scholar-mcp
git checkout -b chore/adopt-fastmcp-template
git tag --force step6-pre-retrofit HEAD
```

The `step6-pre-retrofit` tag is the reference for `git show step6-pre-retrofit:<path>` restorations.

### Task B3: Render template into scratch dir

**Files:**
- Populate: `/tmp/scholar-replay/`.

- [ ] **Step 1: Checkout template at the pinned version**

```bash
FINAL_TAG=$(cat /tmp/scholar-template-version.txt)
git -C /mnt/code/fastmcp-server-template checkout "$FINAL_TAG"
git -C /mnt/code/fastmcp-server-template status
```

Expected: `HEAD detached at <FINAL_TAG>`, clean tree.

- [ ] **Step 2: Run copier copy**

```bash
FINAL_TAG=$(cat /tmp/scholar-template-version.txt)
copier copy --trust \
  --data-file /tmp/scholar-answers.yml \
  --vcs-ref "$FINAL_TAG" \
  /mnt/code/fastmcp-server-template \
  /tmp/scholar-replay
```

Expected: copier writes files non-interactively.

- [ ] **Step 3: Verify answers file + typer-based cli**

```bash
cat /tmp/scholar-replay/.copier-answers.yml
grep -n 'typer\|import typer' /tmp/scholar-replay/src/scholar_mcp/cli.py | head -3
```

Expected: `.copier-answers.yml` has `_commit: <FINAL_TAG>` + 8 answers.  `cli.py` has typer imports.

### Task B4: Capture diff + triage scaffold

**Files:**
- Create: `/tmp/scholar-replay-diff.sh`, `/tmp/scholar-replay-diff.txt`, `/tmp/scholar-replay-triage.md`.

- [ ] **Step 1: Write the diff helper**

```bash
cat > /tmp/scholar-replay-diff.sh <<'SHELL'
#!/usr/bin/env bash
set -u
REPLAY="${1:-/tmp/scholar-replay}"
SCHOLAR="${2:-/mnt/code/scholar-mcp}"
EXCLUDES=(
  --exclude=.git --exclude=.venv --exclude=node_modules
  --exclude=__pycache__ --exclude='.copier-answers.yml'
  --exclude='.ruff_cache' --exclude='.mypy_cache' --exclude='.pytest_cache'
  --exclude=htmlcov --exclude=coverage.xml --exclude=coverage.json
  --exclude='.coverage' --exclude=uv.lock --exclude=dist --exclude=build
  --exclude='*.egg-info' --exclude=.claude --exclude=site
)
diff -r "${EXCLUDES[@]}" "$REPLAY" "$SCHOLAR"
SHELL
chmod +x /tmp/scholar-replay-diff.sh
```

- [ ] **Step 2: Run + capture**

```bash
/tmp/scholar-replay-diff.sh | tee /tmp/scholar-replay-diff.txt | head -200
wc -l /tmp/scholar-replay-diff.txt
grep -c '^Only in /tmp/scholar-replay:' /tmp/scholar-replay-diff.txt
grep -c '^Only in /mnt/code/scholar-mcp:' /tmp/scholar-replay-diff.txt
grep -c '^diff -r' /tmp/scholar-replay-diff.txt
```

Expected: large diff (scholar has 50 module files, lots of domain).  Note the three counts.

- [ ] **Step 3: Scaffold triage log**

```bash
cat > /tmp/scholar-replay-triage.md <<'EOF'
# Scholar replay triage (Step 6 Phase B)

Generated: 2026-04-21
Template: pvliesdonk/fastmcp-server-template @ VERSION-FROM-FILE
Render target: /tmp/scholar-replay
Scholar source: /mnt/code/scholar-mcp @ main

## Phase 1 outcome

- Class A (domain content, no action): 0 (TBD)
- Class B (infra bug in scholar, fix during retrofit): 0
- Class C (hybrid + full-replacement hybrid): 0
- Class D (template bug — cut v1.0.x patch): 0
- Class E (acceptable divergence, document): 0

## Class A — Domain content (no action)

## Class B — Infra bug in scholar (adopt template version)

## Class C — Hybrid (preserve scholar content)

## Class D — Template bug (cut v1.0.x patch)

## Class E — Acceptable divergence (document + move on)

EOF
```

Fill in the template version in the scaffold:

```bash
sed -i "s/VERSION-FROM-FILE/$(cat /tmp/scholar-template-version.txt)/" /tmp/scholar-replay-triage.md
```

### Task B5: Classify every diff entry

**Files:**
- Modify: `/tmp/scholar-replay-triage.md`.

This is the substantive judgment work.  For every diff entry, file it into one of the 5 classes below.

- [ ] **Step 1: Walk the diff**

```bash
less /tmp/scholar-replay-diff.txt
```

- [ ] **Step 2: Apply the class rules**

Expected hotspots:

- **Class A** (`Only in /mnt/code/scholar-mcp:`): all 8 API client files (`_*_client.py`), all 5 enricher files (`_enricher_*.py`), standards sync files (`_standards_sync.py`, `_sync_{cc,cen,relaton}.py`, `_relaton_live.py`), 10 tool-split files (`_tools_*.py`), utility files (`_cache.py`, `_chapter_parser.py`, `_citation_formatter.py`, `_citation_names.py`, `_enrichment.py`, `_epo_xml.py`, `_patent_numbers.py`, `_pdf_url_resolver.py`, `_protocols.py`, `_rate_limiter.py`, `_record_types.py`, `_task_queue.py`, `_book_enrichment.py`), `_server_{deps,tools,resources,prompts}.py`, `tests/`, `docs/`, `examples/`.
- **Class B** (`Only in /tmp/scholar-replay:`): `.github/dependabot.yml` (if scholar lacks it), `.env.example`, CHANGELOG preamble, `.gitignore` `.claude/` entry, MCPB scaffold files (already in scholar; should be skipped).  Template scaffolds that shadow scholar modules: `tools.py`, `resources.py`, `prompts.py`, `server.py`, `domain.py`, `tests/test_smoke.py`, `tests/test_tools.py` → Class B (delete in Phase 2).
- **Class C** (`diff -r`): `pyproject.toml`, `CLAUDE.md`, `README.md`, `server.json`, `config.py`, `mcp_server.py`, `cli.py`, `mkdocs.yml`, `compose.yml`, `Dockerfile`, `docker-entrypoint.sh`, `tests/conftest.py`, all workflows, `.pre-commit-config.yaml`, `packaging/nfpm.yaml`, `packaging/scripts/postinstall.sh`, `packaging/mcpb/*` (scholar already has these, may differ), `__init__.py`.  Each is either a sentinel-based hybrid or a full-replacement hybrid (scholar's richer version wins).
- **Class D** (template bug): **none expected** (Step 5 already cleared the template's known gaps).  If any surface, stop and cut a template patch.
- **Class E** (acceptable divergence): `coverage-status.yml` workflow (scholar-specific, keep), `coverage.json` + `coverage.xml` at repo root (local artifacts, delete during retrofit), any `authlib/...` deps scholar pins that template doesn't.

- [ ] **Step 3: Write the classification into `/tmp/scholar-replay-triage.md`**

For each diff entry, add a line under the appropriate class with a one-line rationale.  Group domain file families where reasonable (e.g. "10 `_tools_*.py` files — Class A, domain-specific tool implementations").

- [ ] **Step 4: Fill in Phase 1 outcome counts**

Update the counts at the top of the triage log with the final per-class counts and note any `⚠️ NEEDS HUMAN CALL` items.

- [ ] **Step 5: Archive triage into scholar repo**

```bash
mkdir -p /mnt/code/scholar-mcp/docs/superpowers/notes
cp /tmp/scholar-replay-triage.md \
   /mnt/code/scholar-mcp/docs/superpowers/notes/2026-04-21-step6-replay-triage.md
```

The file will be committed as part of the Phase 2 retrofit.

- [ ] **Step 6: Stop if Class D > 0**

If any Class D findings: STOP.  Cut a template patch on `/mnt/code/fastmcp-server-template` per the Step 4/5 iteration pattern (branch, fix, PR, merge, cut `v1.0.N+1`, update `/tmp/scholar-template-version.txt`, re-render, re-triage).  Do NOT proceed to Phase 2 retrofit until Class D = 0.

### Task B6: Run `copier copy --overwrite` against scholar

**Files:**
- Modifies: many files in `/mnt/code/scholar-mcp`.
- Creates: `/mnt/code/scholar-mcp/.copier-answers.yml`.

- [ ] **Step 1: Run copier**

```bash
FINAL_TAG=$(cat /tmp/scholar-template-version.txt)
cd /mnt/code/scholar-mcp
copier copy --overwrite --trust \
  --data-file /tmp/scholar-answers.yml \
  --vcs-ref "$FINAL_TAG" \
  /mnt/code/fastmcp-server-template \
  .
```

Expected: copier reports files written; no prompts.

- [ ] **Step 2: Fix `_src_path` in `.copier-answers.yml`**

Local filesystem path breaks `copier update` from other checkouts.  Replace with the github URL:

```bash
sed -i 's|^_src_path: /mnt/code/fastmcp-server-template$|_src_path: https://github.com/pvliesdonk/fastmcp-server-template|' \
  /mnt/code/scholar-mcp/.copier-answers.yml
cat /mnt/code/scholar-mcp/.copier-answers.yml
```

Expected: `_src_path: https://github.com/pvliesdonk/fastmcp-server-template` and `_commit: <FINAL_TAG>`.

- [ ] **Step 3: Inspect overall scope of changes**

```bash
cd /mnt/code/scholar-mcp
git status
git diff --stat | tail -30
```

### Task B7: Restore pyproject.toml (add core + typer, drop click, rebuild extras)

**Files:**
- Modify: `/mnt/code/scholar-mcp/pyproject.toml`.

- [ ] **Step 1: Restore scholar's pre-retrofit pyproject.toml**

```bash
cd /mnt/code/scholar-mcp
git show step6-pre-retrofit:pyproject.toml > pyproject.toml
```

- [ ] **Step 2: Rewrite dependencies / extras**

Locate the `dependencies = [...]` block and replace with:

```toml
dependencies = [
    # fastmcp + httpx + uvicorn come transitively via fastmcp-pvl-core;
    # only list deps scholar uses DIRECTLY here.
    "fastmcp-pvl-core>=1.0,<2",
    "typer>=0.12",
    "httpx",
    "aiosqlite",
    "python-epo-ops-client>=4.2",
    "lxml>=5.0",
    "beautifulsoup4>=4.14.3",
]
```

Locate the `[project.optional-dependencies]` block and replace with:

```toml
[project.optional-dependencies]
mcp = ["fastmcp[tasks]>=3.2.0,<4"]
all = ["fastmcp[tasks]>=3.2.0,<4"]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
    "diff-cover>=9.0",
    "ruff>=0.1",
    "mypy>=1.0",
    "pip-audit>=2.7",
]
```

**Note:** `click>=8.0` removed (typer pulls click transitively); `uvicorn` dropped from `mcp`/`all` extras (transitive via fastmcp).

- [ ] **Step 3: Update project metadata**

Fix the scaffold placeholder `authors` line:

```toml
authors = [{ name = "Peter van Liesdonk" }]
```

- [ ] **Step 4: Add PSR build_command + assets**

Locate the `[tool.semantic_release]` block and update:

```toml
[tool.semantic_release]
version_toml = ["pyproject.toml:project.version"]
commit_parser = "angular"
tag_format = "v{version}"
# Bump versioned manifests (server.json) inside the release commit.
build_command = "python scripts/bump_manifests.py"
# PSR stages and commits files listed in `assets` alongside pyproject.toml
# and CHANGELOG.md, landing a single commit per release tag.
assets = [
    "server.json",
]
```

If the block is missing or partial, replace the full `[tool.semantic_release]` stanza.

- [ ] **Step 5: Verify**

```bash
cd /mnt/code/scholar-mcp
grep -nE 'fastmcp-pvl-core|typer|click|uvicorn|build_command|assets =' pyproject.toml | head -15
```

Expected: core pinned, typer pinned, no `click` in direct deps, no `uvicorn` in extras, PSR has `build_command` + `assets = ["server.json"]`.

### Task B8: Restore Class C hybrids (full-restore from pre-retrofit)

**Files:**
- `/mnt/code/scholar-mcp/{CLAUDE.md,README.md,server.json,mkdocs.yml,compose.yml,Dockerfile,docker-entrypoint.sh,tests/conftest.py,.pre-commit-config.yaml,packaging/nfpm.yaml,packaging/scripts/postinstall.sh,LICENSE,src/scholar_mcp/__init__.py}`

- [ ] **Step 1: Restore each file from pre-retrofit**

```bash
cd /mnt/code/scholar-mcp
for f in CLAUDE.md README.md server.json mkdocs.yml compose.yml Dockerfile \
         docker-entrypoint.sh tests/conftest.py .pre-commit-config.yaml \
         packaging/nfpm.yaml packaging/scripts/postinstall.sh LICENSE \
         src/scholar_mcp/__init__.py; do
  if git cat-file -e step6-pre-retrofit:"$f" 2>/dev/null; then
    git show step6-pre-retrofit:"$f" > "$f"
  fi
done
```

- [ ] **Step 2: Restore packaging/mcpb** (scholar already had its own mcpb scaffold; skip-if-exists should have honored it)

```bash
cd /mnt/code/scholar-mcp
git diff --name-only step6-pre-retrofit HEAD -- packaging/mcpb/ | while read f; do
  if git cat-file -e step6-pre-retrofit:"$f" 2>/dev/null; then
    git show step6-pre-retrofit:"$f" > "$f"
  fi
done
```

- [ ] **Step 3: Restore docs + examples trees**

```bash
cd /mnt/code/scholar-mcp
for d in docs examples; do
  git diff --name-only step6-pre-retrofit HEAD -- $d/ | while read f; do
    if git cat-file -e step6-pre-retrofit:"$f" 2>/dev/null; then
      git show step6-pre-retrofit:"$f" > "$f"
    fi
  done
done
```

- [ ] **Step 4: Accept template versions for workflows**

Workflows are the infra refresh.  For each workflow, `git diff step6-pre-retrofit -- .github/workflows/<name>` to confirm the template version is the one we want.  Expected: all workflows use template version.  If a workflow is scholar-specific and not in the template (e.g. `coverage-status.yml`), restore it:

```bash
cd /mnt/code/scholar-mcp
for f in coverage-status.yml; do
  if git cat-file -e step6-pre-retrofit:".github/workflows/$f" 2>/dev/null; then
    git show step6-pre-retrofit:".github/workflows/$f" > ".github/workflows/$f"
  fi
done
```

### Task B9: Rewrite config.py — ProjectConfig composition

**Files:**
- Replace: `/mnt/code/scholar-mcp/src/scholar_mcp/config.py`

- [ ] **Step 1: Write new config.py**

Use `Write` tool with:

```python
"""Project configuration for scholar-mcp.

Composes ``fastmcp_pvl_core.ServerConfig`` for transport/auth/event-store
fields; adds Scholar domain fields below.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from fastmcp_pvl_core import ServerConfig, env, parse_bool

logger = logging.getLogger(__name__)

_ENV_PREFIX = "SCHOLAR_MCP"


@dataclass
class ProjectConfig:
    """Scholar-mcp configuration loaded from environment variables.

    The ``server`` field carries generic FastMCP server config (transport,
    auth, event store).  Domain fields (API keys, cache dir, etc.) live
    directly on this dataclass.
    """

    # CONFIG-FIELDS-START — scholar domain fields; kept across copier update
    server: ServerConfig = field(default_factory=ServerConfig)
    server_name: str | None = None
    read_only: bool = True
    s2_api_key: str | None = None
    docling_url: str | None = None
    vlm_api_url: str | None = None
    vlm_api_key: str | None = None
    vlm_model: str = "gpt-4o"
    cache_dir: Path = field(default_factory=lambda: Path("/data/scholar-mcp"))
    contact_email: str | None = None
    epo_consumer_key: str | None = None
    epo_consumer_secret: str | None = None
    google_books_api_key: str | None = None
    github_token: str | None = None
    # CONFIG-FIELDS-END

    @property
    def epo_configured(self) -> bool:
        """True when both EPO OPS credentials are set."""
        return (
            self.epo_consumer_key is not None and self.epo_consumer_secret is not None
        )


def load_config() -> ProjectConfig:
    """Load configuration from environment variables.

    Reads all generic ``ServerConfig`` env vars (BASE_URL, BEARER_TOKEN,
    OIDC_*, EVENT_STORE_URL, etc.) plus scholar's domain fields — see
    ``fastmcp_pvl_core.ServerConfig.from_env`` for the generic set.
    """
    server = ServerConfig.from_env(env_prefix=_ENV_PREFIX)

    # CONFIG-FROM-ENV-START — scholar domain reads; kept across copier update
    server_name = env(_ENV_PREFIX, "SERVER_NAME")
    read_only = parse_bool(env(_ENV_PREFIX, "READ_ONLY", "true"))

    cache_dir = Path(env(_ENV_PREFIX, "CACHE_DIR") or "/data/scholar-mcp")

    # SCHOLAR_GITHUB_TOKEN (not SCHOLAR_MCP_GITHUB_TOKEN) — conventional
    # GitHub-tooling env name users expect.
    github_token = os.environ.get("SCHOLAR_GITHUB_TOKEN") or None

    config = ProjectConfig(
        server=server,
        server_name=server_name,
        read_only=read_only,
        s2_api_key=env(_ENV_PREFIX, "S2_API_KEY"),
        docling_url=env(_ENV_PREFIX, "DOCLING_URL"),
        vlm_api_url=env(_ENV_PREFIX, "VLM_API_URL"),
        vlm_api_key=env(_ENV_PREFIX, "VLM_API_KEY"),
        vlm_model=env(_ENV_PREFIX, "VLM_MODEL", "gpt-4o"),
        cache_dir=cache_dir,
        contact_email=env(_ENV_PREFIX, "CONTACT_EMAIL"),
        epo_consumer_key=env(_ENV_PREFIX, "EPO_CONSUMER_KEY"),
        epo_consumer_secret=env(_ENV_PREFIX, "EPO_CONSUMER_SECRET"),
        google_books_api_key=env(_ENV_PREFIX, "GOOGLE_BOOKS_API_KEY"),
        github_token=github_token,
    )
    # CONFIG-FROM-ENV-END

    logger.debug("load_config: read_only=%s cache_dir=%s", config.read_only, config.cache_dir)
    return config
```

- [ ] **Step 2: Verify**

```bash
cd /mnt/code/scholar-mcp
uv run python -c "from scholar_mcp.config import load_config, ProjectConfig, _ENV_PREFIX; c = ProjectConfig(); print('ok')"
```

Expected: `ok` (after `uv sync` — may need to run sync first; if import fails, skip this step and defer to the gate pass in Task B14).

### Task B10: Update consumers for ServerConfig → ProjectConfig rename

**Files:**
- `/mnt/code/scholar-mcp/src/scholar_mcp/_server_deps.py`
- Tests under `/mnt/code/scholar-mcp/tests/` that import `ServerConfig` from scholar's config.

- [ ] **Step 1: Find consumers**

```bash
cd /mnt/code/scholar-mcp
grep -rn 'from scholar_mcp.config import.*ServerConfig\|scholar_mcp\.config\.ServerConfig\|config\.ServerConfig' src/ tests/ | grep -v fastmcp_pvl_core | head -20
```

- [ ] **Step 2: Rename via sed**

```bash
cd /mnt/code/scholar-mcp
grep -rl 'from scholar_mcp.config import.*ServerConfig\|scholar_mcp\.config\.ServerConfig\|config\.ServerConfig' src/ tests/ 2>/dev/null | while read f; do
  sed -i 's/\(from scholar_mcp\.config import[^\n]*\)ServerConfig/\1ProjectConfig/g' "$f"
  sed -i 's/scholar_mcp\.config\.ServerConfig/scholar_mcp.config.ProjectConfig/g' "$f"
  sed -i 's/\bconfig\.ServerConfig\b/config.ProjectConfig/g' "$f"
  echo "updated: $f"
done
```

- [ ] **Step 3: Verify**

```bash
cd /mnt/code/scholar-mcp
grep -rn 'config\.ServerConfig\|from scholar_mcp\.config import.*ServerConfig' src/ tests/ | grep -v fastmcp_pvl_core
```

Expected: empty output (all renamed; only `fastmcp_pvl_core.ServerConfig` imports remain, which is correct).

### Task B11: Rewrite mcp_server.py as make_server()

**Files:**
- Replace: `/mnt/code/scholar-mcp/src/scholar_mcp/mcp_server.py`.

- [ ] **Step 1: Inspect current file**

```bash
wc -l /mnt/code/scholar-mcp/src/scholar_mcp/mcp_server.py
```

Expected: 475 lines.

- [ ] **Step 2: Replace contents with make_server() shape**

Use `Write` tool with:

```python
"""Scholar MCP — FastMCP server entry point.

Composes the primitives from ``fastmcp-pvl-core`` into scholar's
``make_server()``.  See https://gofastmcp.com/servers for the FastMCP
server surface and the fastmcp-pvl-core README for the helpers used here.
"""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from fastmcp import FastMCP
from fastmcp.server.event_store import EventStore
from fastmcp_pvl_core import (
    ServerConfig,
    build_auth,
    build_instructions,
    configure_logging_from_env,
    wire_middleware_stack,
)
from fastmcp_pvl_core import (
    build_event_store as _core_build_event_store,
)
from fastmcp_pvl_core import (
    resolve_auth_mode as _core_resolve_auth_mode,
)

from scholar_mcp._server_deps import make_service_lifespan
from scholar_mcp._server_prompts import register_prompts
from scholar_mcp._server_resources import register_resources
from scholar_mcp._server_tools import register_tools
from scholar_mcp.config import _ENV_PREFIX, ProjectConfig

logger = logging.getLogger(__name__)

_DEFAULT_SERVER_NAME = "scholar-mcp"


def _load_server_config() -> ServerConfig:
    """Compat helper — load ServerConfig slice from scholar env vars.

    Used by backward-compat wrappers ``_resolve_auth_mode`` / ``_build_*_auth``
    that preserve their historical zero-arg call shape for existing tests.
    """
    return ServerConfig.from_env(env_prefix=_ENV_PREFIX)


def _resolve_auth_mode() -> str | None:
    """Backward-compat wrapper — returns ``None`` when core returns ``"none"``."""
    mode = _core_resolve_auth_mode(_load_server_config())
    return None if mode == "none" else mode


def _build_remote_auth() -> object | None:
    """Backward-compat wrapper around ``fastmcp_pvl_core.build_remote_auth``."""
    from fastmcp_pvl_core import build_remote_auth

    return build_remote_auth(_load_server_config())


def _build_bearer_auth() -> object | None:
    """Backward-compat wrapper around ``fastmcp_pvl_core.build_bearer_auth``."""
    from fastmcp_pvl_core import build_bearer_auth

    return build_bearer_auth(_load_server_config())


def _build_oidc_auth() -> object | None:
    """Backward-compat wrapper around ``fastmcp_pvl_core.build_oidc_proxy_auth``."""
    from fastmcp_pvl_core import build_oidc_proxy_auth

    return build_oidc_proxy_auth(_load_server_config())


# Module-level re-export for tests that patch resolve_auth_mode.
resolve_auth_mode = _core_resolve_auth_mode


def build_event_store(url: str | None = None) -> EventStore:
    """Build an ``EventStore`` — thin shim over core's helper.

    Preserves the legacy zero-arg call shape used by cli.py.
    """
    return _core_build_event_store(_ENV_PREFIX, ServerConfig(event_store_url=url))


def make_server(
    *,
    transport: str = "stdio",
    config: ProjectConfig | None = None,
) -> FastMCP:
    """Construct the Scholar MCP FastMCP server.

    Args:
        transport: ``"stdio"`` / ``"http"`` / ``"sse"``.  Tools that depend
            on HTTP transport (e.g. artifact downloads) are wired only when
            transport != ``"stdio"``.
        config: Optional pre-loaded config; defaults to env-based load.

    Returns:
        A configured :class:`fastmcp.FastMCP` instance.
    """
    if config is None:
        from scholar_mcp.config import load_config

        config = load_config()
    configure_logging_from_env()

    auth = build_auth(config.server)
    auth_mode = _core_resolve_auth_mode(config.server) if auth is not None else "none"
    if auth_mode == "none":
        logger.warning(
            "No auth configured — server accepts unauthenticated connections"
        )
    else:
        logger.info("Auth enabled: mode=%s", auth_mode)

    try:
        pkg_ver = _pkg_version("pvliesdonk-scholar-mcp")
    except PackageNotFoundError:
        pkg_ver = "unknown"

    server_name = config.server_name or _DEFAULT_SERVER_NAME

    logger.info(
        "Server config: name=%s version=%s auth=%s mode=%s cache_dir=%s",
        server_name,
        pkg_ver,
        auth_mode,
        "read-only" if config.read_only else "read-write",
        config.cache_dir,
    )

    mcp = FastMCP(
        name=server_name,
        instructions=build_instructions(
            read_only=config.read_only,
            env_prefix=_ENV_PREFIX,
            domain_line=(
                "Scholar MCP — academic literature server: Semantic Scholar + "
                "OpenAlex + Crossref + OpenLibrary + Google Books + EPO (patents) "
                "+ standards (ISO/IEC/IEEE/CEN/CC) enrichment and docling PDF "
                "conversion.  Read-only tools are always available; write-tagged "
                "tools (cache writes) are hidden in read-only mode."
            ),
        ),
        lifespan=make_service_lifespan(config),
        auth=auth,
    )

    wire_middleware_stack(mcp)

    register_tools(mcp)
    register_resources(mcp)
    register_prompts(mcp)

    if config.read_only:
        mcp.disable(tags={"write"})

    return mcp


# Backward-compat alias: existing callers import `create_server`.
create_server = make_server
```

- [ ] **Step 3: Confirm line count dropped**

```bash
wc -l /mnt/code/scholar-mcp/src/scholar_mcp/mcp_server.py
```

Expected: ~175-200 lines (down from 475).

### Task B12: Rewrite cli.py click → typer (4 subcommands preserved)

**Files:**
- Replace: `/mnt/code/scholar-mcp/src/scholar_mcp/cli.py`.

- [ ] **Step 1: Write new cli.py**

Use `Write` tool with:

```python
"""Command-line interface for scholar-mcp.

Provides ``serve``, ``sync-standards``, and ``cache`` subcommands.  The
entry point is :func:`main`, registered as ``scholar-mcp`` in
``pyproject.toml``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx
import typer
from fastmcp_pvl_core import configure_logging_from_env, normalise_http_path

from scholar_mcp.config import _ENV_PREFIX

if TYPE_CHECKING:
    from scholar_mcp._standards_sync import Loader

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="scholar-mcp",
    help="Scholar MCP — academic literature server.",
    no_args_is_help=True,
    add_completion=False,
)
cache_app = typer.Typer(
    name="cache",
    help="Manage the Scholar MCP local cache.",
    no_args_is_help=True,
)
app.add_typer(cache_app, name="cache")


class _Body(StrEnum):
    """Standards bodies known to ``sync-standards``.  Case-insensitive on CLI."""

    ISO = "ISO"
    IEC = "IEC"
    IEEE = "IEEE"
    CEN = "CEN"
    CC = "CC"
    ALL = "all"


@app.callback()
def _root(
    verbose: bool = typer.Option(
        False, "-v", "--verbose", help="Enable debug logging."
    ),
) -> None:
    """Root callback — bootstraps logging for every subcommand."""
    configure_logging_from_env(verbose=verbose)
    if verbose:
        # httpx is noisy at DEBUG; keep it at WARNING.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


@app.command()
def serve(
    transport: str = typer.Option(
        "stdio", help="MCP transport (stdio / http / sse)."
    ),
    host: str = typer.Option("0.0.0.0", help="Bind host (http only)."),
    port: int = typer.Option(8000, help="Bind port (http only)."),
    http_path: str | None = typer.Option(
        None,
        "--http-path",
        "--path",
        help=(
            f"Mount path (http only, default: ${_ENV_PREFIX}_HTTP_PATH or /mcp)."
        ),
    ),
) -> None:
    """Run the MCP server."""
    try:
        from scholar_mcp.mcp_server import build_event_store, create_server
    except ImportError as exc:
        logger.error(
            "FastMCP is not installed. Install with: "
            "pip install pvliesdonk-scholar-mcp[mcp]"
        )
        raise typer.Exit(code=1) from exc

    server = create_server(transport=transport)
    env_http_path = os.environ.get(f"{_ENV_PREFIX}_HTTP_PATH")
    path = normalise_http_path(http_path or env_http_path)

    if transport != "http" and (
        host != "0.0.0.0" or port != 8000 or http_path is not None
    ):
        logger.warning("--host, --port and --path are only used with --transport http")

    if transport == "http":
        try:
            import uvicorn
        except ImportError as exc:
            logger.error(
                "HTTP transport requires uvicorn. Install with: "
                "pip install 'pvliesdonk-scholar-mcp[mcp]'"
            )
            raise typer.Exit(code=1) from exc

        event_store = build_event_store()
        app_ = server.http_app(path=path, event_store=event_store)
        uvicorn.run(
            app_,
            host=host,
            port=port,
            lifespan="on",
            timeout_graceful_shutdown=0,
        )
    else:
        from typing import Literal, cast as type_cast

        transport_literal = type_cast(
            "Literal['stdio', 'http', 'sse', 'streamable-http']", transport
        )
        server.run(transport=transport_literal)


@app.command("sync-standards")
def sync_standards(
    body: _Body = typer.Option(
        _Body.ALL,
        "--body",
        case_sensitive=False,
        help="Body to sync.  'all' runs every registered loader.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Bypass upstream-freshness checks and re-sync."
    ),
    cache_dir: Path | None = typer.Option(
        None, "--cache-dir", help="Override cache directory."
    ),
) -> None:
    """Sync Tier 2 standards catalogue data into the local cache.

    Safe to schedule under cron / launchd / systemd timers.

    Exit codes:
        0 — no changes OR synced with updates
        1 — hard failure (no body synced)
        3 — partial failure (some bodies succeeded, some did not)
    """
    from scholar_mcp._cache import ScholarCache
    from scholar_mcp._standards_sync import format_reports, run_sync
    from scholar_mcp.config import load_config

    async def _run() -> int:
        from scholar_mcp._standards_sync import SyncReport

        config = load_config()
        db_path = (cache_dir or config.cache_dir) / "cache.db"
        c = ScholarCache(db_path)
        await c.open()
        http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        loaders: list[Loader] = []
        reports: list[SyncReport] = []
        try:
            loaders = _select_loaders(
                body.value, http=http, token=config.github_token
            )
            reports = await run_sync(loaders, c, force=force)
        finally:
            await http.aclose()
            await c.close()

        typer.echo(format_reports(reports))

        if not loaders:
            return 0
        failures = [r for r in reports if r.errors]
        successes = [r for r in reports if not r.errors]
        if failures and not successes:
            return 1
        if failures and successes:
            return 3
        return 0

    exit_code = asyncio.run(_run())
    raise typer.Exit(code=exit_code)


@cache_app.command("stats")
def cache_stats(
    cache_dir: Path | None = typer.Option(
        None, "--cache-dir", help="Override cache directory."
    ),
) -> None:
    """Show cache statistics (row counts, file size)."""
    from scholar_mcp._cache import ScholarCache
    from scholar_mcp.config import load_config

    async def _run() -> None:
        config = load_config()
        db_path = (cache_dir or config.cache_dir) / "cache.db"
        if not db_path.exists():
            typer.echo("No cache database found.")
            return
        c = ScholarCache(db_path)
        await c.open()
        stats = await c.stats()
        await c.close()
        for key, val in stats.items():
            typer.echo(f"{key}: {val}")

    asyncio.run(_run())


@cache_app.command("clear")
def cache_clear(
    older_than: int | None = typer.Option(
        None,
        "--older-than",
        help="Only remove entries older than this many days.",
    ),
    cache_dir: Path | None = typer.Option(
        None, "--cache-dir", help="Override cache directory."
    ),
) -> None:
    """Clear cache entries.

    Without ``--older-than``, wipes all cached data (preserves id_aliases).
    With ``--older-than N``, removes only entries older than N days.
    """
    from scholar_mcp._cache import ScholarCache
    from scholar_mcp.config import load_config

    async def _run() -> None:
        config = load_config()
        db_path = (cache_dir or config.cache_dir) / "cache.db"
        if not db_path.exists():
            typer.echo("No cache database found.")
            return
        c = ScholarCache(db_path)
        await c.open()
        await c.clear(older_than_days=older_than)
        await c.close()
        if older_than is not None:
            typer.echo(f"Cache cleared (older than {older_than} days).")
        else:
            typer.echo("Cache cleared.")

    asyncio.run(_run())


def _select_loaders(
    body: str, *, http: httpx.AsyncClient, token: str | None
) -> list[Loader]:
    """Return loaders matching *body* ('all' returns every registered).

    All loaders share the passed-in ``httpx.AsyncClient``; the caller is
    responsible for closing it.
    """
    from scholar_mcp._sync_cc import CCLoader
    from scholar_mcp._sync_cen import CENLoader
    from scholar_mcp._sync_relaton import RelatonLoader

    registered: list[Loader] = cast(
        "list[Loader]",
        [
            RelatonLoader("ISO", http=http, token=token),
            RelatonLoader("IEC", http=http, token=token),
            RelatonLoader("IEEE", http=http, token=token),
            CCLoader(http=http),
            CENLoader(),
        ],
    )
    if body.upper() == "ALL":
        return registered
    return [loader for loader in registered if loader.body == body.upper()]


def main() -> None:
    """CLI entry point — used by ``[project.scripts]`` in pyproject.toml."""
    app()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify help works**

```bash
cd /mnt/code/scholar-mcp
uv sync --all-extras --dev 2>&1 | tail -3
uv run scholar-mcp --help 2>&1 | head -15
uv run scholar-mcp serve --help 2>&1 | head -15
uv run scholar-mcp sync-standards --help 2>&1 | head -15
uv run scholar-mcp cache --help 2>&1 | head -10
uv run scholar-mcp cache stats --help 2>&1 | head -10
```

Expected: all help texts show typer output with the documented options.

### Task B13: Delete template scaffold files that shadow scholar modules

**Files:**
- Delete: `src/scholar_mcp/{server,domain,tools,resources,prompts}.py`, `tests/test_smoke.py`, `tests/test_tools.py`.
- Delete: `coverage.json`, `coverage.xml` at repo root (Class E cleanup).

- [ ] **Step 1: Delete template scaffolds + coverage artifacts**

```bash
cd /mnt/code/scholar-mcp
for f in \
  src/scholar_mcp/server.py \
  src/scholar_mcp/domain.py \
  src/scholar_mcp/tools.py \
  src/scholar_mcp/resources.py \
  src/scholar_mcp/prompts.py \
  tests/test_smoke.py \
  tests/test_tools.py \
  coverage.json \
  coverage.xml; do
  if [ -f "$f" ]; then
    rm "$f"
    echo "deleted: $f"
  fi
done
```

- [ ] **Step 2: Ensure coverage artifacts are gitignored**

```bash
cd /mnt/code/scholar-mcp
grep -q '^coverage\.json$' .gitignore || echo 'coverage.json' >> .gitignore
grep -q '^coverage\.xml$' .gitignore || echo 'coverage.xml' >> .gitignore
```

- [ ] **Step 3: Ensure scripts/bump_manifests.py exists** (template v1.0.3+ ships it)

```bash
cd /mnt/code/scholar-mcp
ls scripts/bump_manifests.py 2>&1
```

If not present, copy from the rendered replay:

```bash
mkdir -p scripts
if [ ! -f scripts/bump_manifests.py ]; then
  cp /tmp/scholar-replay/scripts/bump_manifests.py scripts/bump_manifests.py
  chmod +x scripts/bump_manifests.py
fi
```

### Task B14: Cleanup check — no domain deletions

**Files:**
- No edits; validation only.

- [ ] **Step 1: Inspect deletions**

```bash
cd /mnt/code/scholar-mcp
git status --porcelain | grep '^ D' | head -30
```

- [ ] **Step 2: Restore any accidentally-deleted domain files**

For each `D` line that's a Class A domain module (clients, enrichers, tools_*, utilities, _server_*), restore:

```bash
# Example; run for each accidentally-deleted path
git checkout step6-pre-retrofit -- path/to/file.py
```

### Task B15: Run the gate — iterate until green

**Files:**
- No edits (unless fixes needed).

- [ ] **Step 1: uv sync**

```bash
cd /mnt/code/scholar-mcp
uv sync --all-extras --dev 2>&1 | tail -5
```

Expected: resolver succeeds.  `fastmcp-pvl-core` pulled.  `typer` pulled.

- [ ] **Step 2: ruff check**

```bash
cd /mnt/code/scholar-mcp
uv run ruff check --fix . 2>&1 | tail -5
```

- [ ] **Step 3: ruff format**

```bash
cd /mnt/code/scholar-mcp
uv run ruff format . 2>&1 | tail -3
uv run ruff format --check . 2>&1 | tail -3
```

- [ ] **Step 4: mypy**

```bash
cd /mnt/code/scholar-mcp
uv run mypy src/ 2>&1 | tail -5
```

- [ ] **Step 5: pytest**

```bash
cd /mnt/code/scholar-mcp
uv run pytest -x -q 2>&1 | tail -10
```

Common failures + fixes:

- Tests import `ServerConfig` from scholar's config → Task B10 sed pass missed the file; re-run.
- Tests use `from click.testing import CliRunner` → migrate to `from typer.testing import CliRunner` (same API).
- Tests patch `scholar_mcp.mcp_server._build_bearer_auth` or similar → those wrappers still exist for backward compat; no change.
- Tests patch `scholar_mcp.cli._normalise_http_path` → replace with `from fastmcp_pvl_core import normalise_http_path` in the test, or the test no longer needs the patch.
- `sync-standards` tests invoking `click.Choice` → update to the new `_Body` StrEnum or `typer.testing.CliRunner`.
- `cache` tests calling commands via click → use `typer.testing.CliRunner` with `runner.invoke(app, ["cache", "stats", ...])`.

Iterate: fix the issue, re-run from step 1.  Do not skip gate failures.

### Task B16: Audit — confirm no duplicate infra code

**Files:**
- No edits.

- [ ] **Step 1: Grep for hand-rolled auth / instructions / event store**

```bash
cd /mnt/code/scholar-mcp
grep -rn '^def _build_bearer_auth\|^def _build_oidc_auth\|^def _build_remote_auth\|^def _resolve_auth_mode\|^def _build_default_instructions' src/
```

Expected: each pattern appears AT MOST in `mcp_server.py` as a thin wrapper delegating to core (for backward-compat only).  No substantive local implementations.

- [ ] **Step 2: Grep for hand-rolled normalise_http_path**

```bash
cd /mnt/code/scholar-mcp
grep -rn '_normalise_http_path\|_DEFAULT_HTTP_PATH' src/
```

Expected: zero hits.

- [ ] **Step 3: Confirm mcp_server.py size**

```bash
wc -l /mnt/code/scholar-mcp/src/scholar_mcp/mcp_server.py
```

Expected: ≤ 220 lines.

### Task B17: Commit the retrofit

**Files:**
- Create a commit on `chore/adopt-fastmcp-template`.

- [ ] **Step 1: Stage everything**

```bash
cd /mnt/code/scholar-mcp
git add -A
git status
```

Confirm the staged set looks right (no `.venv`, no `__pycache__`).

- [ ] **Step 2: Commit**

```bash
FINAL_TAG=$(cat /tmp/scholar-template-version.txt)
git commit -m "$(cat <<EOF
chore: adopt fastmcp-server-template $FINAL_TAG + fastmcp-pvl-core

Rebuild scholar-mcp onto the copier template + fastmcp-pvl-core in a
single PR.  Template $FINAL_TAG ships a typer-based cli.py starter;
scholar's click CLI is rewritten to typer in the same step.

Adopted (template):
- .copier-answers.yml pinning template $FINAL_TAG
- .github/dependabot.yml, .env.example, CHANGELOG preamble
- Refreshed CI/release/docs workflows
- Refreshed Dockerfile/entrypoint/packaging

Adopted (fastmcp-pvl-core):
- config.py: ProjectConfig composes ServerConfig (rename from local
  ServerConfig); load_config() uses core's env/parse_bool.
- mcp_server.py: 475 → ~200 lines.  make_server() composes build_auth,
  wire_middleware_stack, build_instructions, configure_logging_from_env,
  resolve_auth_mode from fastmcp-pvl-core.  Thin backward-compat
  wrappers kept for existing tests.
- cli.py: 327 → ~330 lines (similar size; rewrite is click→typer, not
  reduction).  Preserves all 4 subcommands (serve, sync-standards,
  cache stats, cache clear).  sync-standards exit codes 0/1/3 emitted
  via typer.Exit.  --body is case-insensitive via StrEnum.
- pyproject.toml: drop click (pulled transitively by typer), drop
  uvicorn from extras (transitive via fastmcp), add fastmcp-pvl-core
  and typer as direct deps, add PSR build_command + assets = ["server.json"].

Preserved (domain):
- All 8 API clients, 5 enrichers, 10 _tools_*.py files
- Standards sync subsystem (_standards_sync, _sync_*, _relaton_live)
- Utility modules (_cache, _chapter_parser, _citation_formatter, etc.)
- _server_{deps,tools,resources,prompts}.py
- Full tests/ and docs/ trees

Phase B replay triage archived at
docs/superpowers/notes/2026-04-21-step6-replay-triage.md.
Spec: pvliesdonk/markdown-vault-mcp repo, docs/superpowers/specs/2026-04-21-step6-scholar-retrofit-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds, pre-commit hooks pass.

### Task B18: Push + PR + iterate reviews

**Files:**
- No edits (review iteration).

- [ ] **Step 1: Push**

```bash
cd /mnt/code/scholar-mcp
git push -u origin chore/adopt-fastmcp-template
```

- [ ] **Step 2: Open PR**

```bash
FINAL_TAG=$(cat /tmp/scholar-template-version.txt)
gh pr create \
  --title "chore: adopt fastmcp-server-template $FINAL_TAG + fastmcp-pvl-core" \
  --body "$(cat <<EOF
## Summary

Step 6 of the fastmcp-pvl-core extraction — scholar-mcp retrofits onto the copier template and fastmcp-pvl-core in a single PR.

## Two-step decoupling

1. **Template v1.0.3** shipped earlier in this cycle with a typer-based \`cli.py\` starter (argparse → typer rewrite, user preference).
2. **This PR** pins \`.copier-answers.yml\` to \`$FINAL_TAG\` and rewrites scholar's click CLI to typer to match the template's new shape.

## Test plan

- [x] \`uv run pytest -x -q\` — all tests pass
- [x] \`uv run ruff check .\` — clean
- [x] \`uv run ruff format --check .\` — clean
- [x] \`uv run mypy src/\` — clean
- [x] Grep audit: no duplicate auth / middleware / logging / event-store code left in \`scholar_mcp/\`
- [x] CLI help: \`scholar-mcp {serve,sync-standards,cache stats,cache clear} --help\` all work
- [ ] CI green on PR

## Spec / plan

\`docs/superpowers/specs/2026-04-21-step6-scholar-retrofit-design.md\` (MV repo).
\`docs/superpowers/plans/2026-04-21-step6-scholar-retrofit-implementation.md\` (MV repo).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch CI**

```bash
gh pr checks --watch
```

- [ ] **Step 4: Address any claude-review / gemini / CI failures**

Iterate with separate fix commits on this branch until CI is green.  Patterns from Step 5:
- Claude-review finds server_name / env-var bypass → fix on this branch.
- Gemini finds typer-specific issues (case_sensitive, typer.Exit vs sys.exit) → fix.
- CI flake on Python 3.14 → rerun failed jobs.
- Dependency Audit CVEs → if transitive, bump via `uv lock --upgrade-package <name>` and commit.

### Task B19: Merge the retrofit PR (after user go-ahead)

**Files:**
- No edits.

- [ ] **Step 1: Stop and report**

Report PR URL + CI status to user.  Do NOT merge autonomously — scholar main merge is a high-stakes decision.

- [ ] **Step 2: After user says go**

```bash
gh pr merge --merge
cd /mnt/code/scholar-mcp
git checkout main && git pull --ff-only
git branch -D chore/adopt-fastmcp-template
git tag --delete step6-pre-retrofit
```

### Task B20: Cut `v1.x.x-rc.N` smoke release

**Files:**
- No edits.

- [ ] **Step 1: Confirm main is green**

```bash
cd /mnt/code/scholar-mcp
git checkout main && git pull --ff-only
gh run list --branch main --limit 3
```

- [ ] **Step 2: Trigger prerelease**

```bash
cd /mnt/code/scholar-mcp
gh workflow run release.yml -f force=minor -f prerelease=true
sleep 5
RUN_ID=$(gh run list --workflow release.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID"
```

**Note:** scholar already has `v1.7.0-rc.1` and `v1.7.0-rc.2` tags.  PSR will bump past them — expected rc tag is `v1.8.0-rc.1` (or higher if retries).

- [ ] **Step 3: Verify rc artifacts**

```bash
git -C /mnt/code/scholar-mcp fetch --tags origin
RC_TAG=$(git -C /mnt/code/scholar-mcp tag --sort=-v:refname | head -1)
echo "rc tag: $RC_TAG"
gh release view "$RC_TAG" --json tagName,isPrerelease,assets \
  -q '{tag: .tagName, isPrerelease, assets: [.assets[].name]}'
docker manifest inspect "ghcr.io/pvliesdonk/scholar-mcp:$RC_TAG" \
  | jq -c '.manifests[].platform' | head -3
git -C /mnt/code/scholar-mcp show "$RC_TAG:server.json" | jq '.version'
```

Expected: `isPrerelease: true`, Docker multi-arch, `server.json.version == RC_TAG stripped of the "v" prefix` (proves the bump_manifests script works).

- [ ] **Step 4: Smoke the rc image**

```bash
docker pull "ghcr.io/pvliesdonk/scholar-mcp:$RC_TAG"
docker rm -f scholar-rc-smoke 2>/dev/null
docker run -d --name scholar-rc-smoke -p 18003:8000 \
  "ghcr.io/pvliesdonk/scholar-mcp:$RC_TAG" \
  scholar-mcp serve --transport http --host 0.0.0.0 --port 8000
sleep 10
docker logs scholar-rc-smoke 2>&1 | grep -E 'version|listening|Uvicorn|Server config|ERROR' | head -6
curl -sS -o /dev/null -w 'status=%{http_code}\n' http://localhost:18003/mcp
docker rm -f scholar-rc-smoke
```

Expected: log shows `Server config: name=scholar-mcp version=<rc-tag> ...` and `Uvicorn running on http://0.0.0.0:8000`.  Curl returns any status (server is up).

- [ ] **Step 5: Stop and report**

Report rc tag + smoke status + MCP Registry skipped (rc-gated).  Wait for user go-ahead before Phase 3b stable.

### Task B21: Cut stable release (after user go-ahead)

**Files:**
- No edits.

- [ ] **Step 1: Confirm rc smoke green** (Task B20 all ticked).

- [ ] **Step 2: Trigger stable release with `force=minor`**

```bash
cd /mnt/code/scholar-mcp
gh workflow run release.yml -f force=minor -f prerelease=false
sleep 5
RUN_ID=$(gh run list --workflow release.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID"
```

**Why `force=minor` + `prerelease=false`:** PSR bumps from the highest existing tag, including prereleases.  Scholar has `v1.7.0-rc.2` + the new rc from Task B20 (e.g. `v1.8.0-rc.1`).  `force=minor` produces `v1.9.0` (or higher) stable.  The version number is intentionally accepted even if higher than expected — per the Step 5 lesson memorized in `feedback_psr_promote_rc_no_force.md`.

- [ ] **Step 3: Verify all six publish targets**

```bash
STABLE=$(git -C /mnt/code/scholar-mcp tag --sort=-v:refname | grep -v rc | head -1)
echo "stable: $STABLE"
echo "=== PyPI ==="
curl -sS https://pypi.org/pypi/pvliesdonk-scholar-mcp/json | jq -r '.info.version'
echo "=== GHCR ==="
docker manifest inspect "ghcr.io/pvliesdonk/scholar-mcp:$STABLE" \
  | jq -c '.manifests[].platform' | head -3
echo "=== MCP Registry ==="
curl -sS "https://registry.modelcontextprotocol.io/v0/servers?search=scholar-mcp" \
  | jq '.servers[] | .server | select(.name=="io.github.pvliesdonk/scholar-mcp") | .version' \
  | tail -5
echo "=== Linux packages ==="
gh release view "$STABLE" --json assets -q '.assets[].name' | grep -E '\.(deb|rpm)$'
echo "=== GH release ==="
gh release view "$STABLE" --json tagName,isPrerelease,assets \
  -q '{tag: .tagName, isPrerelease, asset_count: (.assets | length)}'
echo "=== MCPB ==="
gh release view "$STABLE" --json assets -q '.assets[].name' | grep -i '\.mcpb$'
```

Expected: all six green.  If publish-registry fails with "duplicate version", the bump_manifests script misbehaved — STOP and investigate.

### Task B22: Update handoff memory + MEMORY.md

**Files:**
- Modify: `/home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/fastmcp_pvl_core_extraction_handoff.md`.
- Modify: `/home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/MEMORY.md`.

- [ ] **Step 1: Mark Step 6 DONE in the handoff**

Replace the existing Step 6 line in `fastmcp_pvl_core_extraction_handoff.md`:

```markdown
- **Step 6 — Migrate scholar-mcp** ...
```

with:

```markdown
- **Step 6 — DONE 2026-04-21.** scholar-mcp retrofitted onto fastmcp-server-template vX.Y.Z + fastmcp-pvl-core in a single rebuild PR (PR #N on scholar).  ``mcp_server.py`` 475 → ~200 lines; ``ServerConfig`` renamed to ``ProjectConfig``; click CLI rewritten to typer preserving all 4 subcommands (serve, sync-standards, cache stats, cache clear) with exit-code semantics (0/1/3 via typer.Exit) and case-insensitive --body via StrEnum.  Template PR: typer rewrite (argparse → typer) shipped as v1.0.3 with the template gaining ``typer>=0.12`` direct dep.  v1.X.0 stable shipped to all six targets.  Triage archived at ``/mnt/code/scholar-mcp/docs/superpowers/notes/2026-04-21-step6-replay-triage.md``.  Spec: ``docs/superpowers/specs/2026-04-21-step6-scholar-retrofit-design.md``.  Plan: ``docs/superpowers/plans/2026-04-21-step6-scholar-retrofit-implementation.md``.
```

(Fill in the real template tag and scholar version from Tasks A6 and B21.)

- [ ] **Step 2: Update MEMORY.md status line**

Find:

```markdown
- [fastmcp-pvl-core Extraction Handoff](fastmcp_pvl_core_extraction_handoff.md) — Steps 1-5 **DONE** ...
```

Replace with:

```markdown
- [fastmcp-pvl-core Extraction Handoff](fastmcp_pvl_core_extraction_handoff.md) — Steps 1-6 **DONE** 2026-04-21 (core v1.0.0 + template v1.0.3 (typer) + MV v1.27.0 + IG v1.8.0 + **scholar vX.Y.Z**).  Steps 7-8 (kroki-mcp retrofit + SYNC.md retire) remain.
```

- [ ] **Step 3: Size check**

```bash
wc -c /home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/MEMORY.md
```

Expected: < 25000 bytes.  If over, prune older PR entries per Step 4/5 precedent.

### Task B23: Walk success criteria + announce completion

**Files:**
- No edits.

- [ ] **Step 1: Walk the 10 success criteria in the spec**

For each, verify:

1. Template PR merged, v1.0.3 cut — Task A5/A6.
2. Scholar replay diff Class A/C/E only — Task B5 triage.
3. `.copier-answers.yml` pinned, on main — Task B6/B19.
4. Retrofit commit passes full gate — Task B15.
5. fastmcp-pvl-core used in `make_server()` — Task B16 grep audit.
6. `mcp_server.py` ≤ 220 lines — `wc -l`.
7. `cli.py` typer with 4 subcommands — Task B12.
8. rc smoke passed — Task B20.
9. Stable on all 6 targets — Task B21.
10. Memory updated — Task B22.

- [ ] **Step 2: Announce**

Post a one-line summary naming scholar's stable version + tag + next step (Step 7 — kroki-mcp).

---

## Notes

- **Iteration loops:** Tasks B15 (gate) and B18 (CI/review iteration) are the main loops.  Budget 2-4 gate cycles during B15 for typer coercion fixes; budget 1-3 review-fix commits in B18.
- **Critical rules** (repeated from previous plans):
  - NEVER `--admin` on gh commands.
  - NEVER merge the retrofit PR without explicit user go-ahead.
  - NEVER trigger stable release without user go-ahead (irreversible on PyPI).
  - When PSR refuses with "No release will be made", use `force=minor` (or appropriate) rather than pushing trivial commits.
  - Template gaps discovered mid-retrofit → cut a template v1.0.N+1 patch before continuing, do not monkeypatch scholar directly.
