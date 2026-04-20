# Step 4: Bootstrap-Replay Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate `fastmcp-server-template` v1.0.0 against `markdown-vault-mcp` v1.25.0 via copier-replay, retrofit MV onto the template, then prove the release pipeline still works end-to-end.

**Architecture:** Procedural, three-phase validation. Phase 1 renders the template into a throwaway dir and iteratively patches the template until its output matches MV's infra (domain diffs excepted). Phase 2 runs `copier copy --overwrite` against MV on a branch, restores domain content in hybrid sentinel-block files, gates, and merges. Phase 3 cuts `v1.26.0-rc.1` as Docker+MCPB smoke, then promotes to `v1.26.0` stable (PyPI + GHCR + MCP Registry + Linux packages + GH release + MCPB).

**Tech Stack:** copier ≥9, uv, python-semantic-release (PSR), GitHub Actions, Docker/GHCR, PyPI, MCP Registry, nfpm (Linux packaging), MCPB packaging.

**Working repos:**
- `/mnt/code/markdown-mcp` — target (MV retrofit lands here)
- `/mnt/code/fastmcp-server-template` — template source (patches land here if needed)
- `/tmp/mv-replay` — scratch replay destination (throwaway)

**Spec:** `docs/superpowers/specs/2026-04-21-step4-bootstrap-replay-design.md`

---

## Phase A — Setup

### Task A1: Create MV's copier answers file

**Files:**
- Create: `/tmp/mv-answers.yml`

- [ ] **Step 1: Write the answers file**

Exact content (spec §"MV's copier answers"):

```bash
cat > /tmp/mv-answers.yml <<'EOF'
project_name: markdown-vault-mcp
pypi_name: markdown-vault-mcp
python_module: markdown_vault_mcp
env_prefix: MARKDOWN_VAULT_MCP
human_name: Markdown Vault MCP
domain_description: Generic markdown collection MCP server with FTS5 + semantic search
github_org: pvliesdonk
docker_registry: ghcr.io/pvliesdonk
EOF
```

- [ ] **Step 2: Verify it parses as YAML**

```bash
python -c "import yaml; print(yaml.safe_load(open('/tmp/mv-answers.yml')))"
```

Expected: dict with all 8 keys printed; no exceptions.

### Task A2: Ensure template repo is on the v1.0.0 tag

**Files:**
- No edits; verification only.

- [ ] **Step 1: Fetch tags and check out v1.0.0**

```bash
git -C /mnt/code/fastmcp-server-template fetch --tags origin
git -C /mnt/code/fastmcp-server-template checkout v1.0.0
git -C /mnt/code/fastmcp-server-template status
```

Expected: `HEAD detached at v1.0.0`, clean tree.

- [ ] **Step 2: Confirm copier can read the template**

```bash
copier --version
```

Expected: `copier 9.x.x` or higher. If missing: `uv tool install copier` or `pipx install copier`.

### Task A3: Prepare scratch replay dir

**Files:**
- Create: `/tmp/mv-replay/` (empty)

- [ ] **Step 1: Wipe any prior replay dir**

```bash
rm -rf /tmp/mv-replay
mkdir -p /tmp/mv-replay
```

- [ ] **Step 2: Initialize as empty git repo (copier needs a target to exist)**

```bash
cd /tmp/mv-replay && git init -q && cd -
```

Expected: `.git/` exists; `git -C /tmp/mv-replay status` shows clean empty repo.

---

## Phase B — Replay + iterative template patches

### Task B1: Render template into scratch dir

**Files:**
- Populate: `/tmp/mv-replay/` (from template)

- [ ] **Step 1: Run copier copy**

```bash
copier copy --trust \
  --data-file /tmp/mv-answers.yml \
  --vcs-ref v1.0.0 \
  /mnt/code/fastmcp-server-template \
  /tmp/mv-replay
```

Expected: copier runs non-interactively (all answers provided), writes files,
ends with `Copying took …`. No prompts.

- [ ] **Step 2: Verify the answers file landed**

```bash
test -f /tmp/mv-replay/.copier-answers.yml && \
  cat /tmp/mv-replay/.copier-answers.yml
```

Expected: yaml with `_src_path`, `_commit: v1.0.0`, and the 8 answer keys.

- [ ] **Step 3: Sanity-check generated tree**

```bash
ls /tmp/mv-replay
ls /tmp/mv-replay/src/markdown_vault_mcp
```

Expected: top-level files (`pyproject.toml`, `README.md`, `CLAUDE.md`,
`Dockerfile`, `compose.yml`, `server.json`, `.github/`, `src/`, `tests/`,
`docs/`, `packaging/`, `scripts/`, etc.). Under `src/`, the module directory
should carry the MV name (`markdown_vault_mcp`), not `{{python_module}}`.

### Task B2: Write diff-capture helper

**Files:**
- Create: `/tmp/mv-replay-diff.sh`

- [ ] **Step 1: Write the helper**

```bash
cat > /tmp/mv-replay-diff.sh <<'SHELL'
#!/usr/bin/env bash
# Diff /tmp/mv-replay against /mnt/code/markdown-mcp, excluding
# noise (vcs, build, cache, vendored, coverage, answers file).
set -u
REPLAY="${1:-/tmp/mv-replay}"
MV="${2:-/mnt/code/markdown-mcp}"
EXCLUDES=(
  --exclude=.git
  --exclude=.venv
  --exclude=node_modules
  --exclude=__pycache__
  --exclude='.copier-answers.yml'
  --exclude='.ruff_cache'
  --exclude='.mypy_cache'
  --exclude='.pytest_cache'
  --exclude='htmlcov'
  --exclude=coverage.xml
  --exclude='.coverage'
  --exclude=uv.lock
  --exclude=dist
  --exclude=build
  --exclude='*.egg-info'
  --exclude='static/app.html'          # vendored SPA output
  --exclude=.claude
  --exclude='.copier-answers.yml.old'
)
diff -r "${EXCLUDES[@]}" "$REPLAY" "$MV"
SHELL
chmod +x /tmp/mv-replay-diff.sh
```

- [ ] **Step 2: Run it once to capture the baseline diff**

```bash
/tmp/mv-replay-diff.sh | tee /tmp/mv-replay-diff.txt | head -200
wc -l /tmp/mv-replay-diff.txt
```

Expected: large diff (hundreds to thousands of lines, MV has >1000 tests and
domain-heavy code); no script errors.

### Task B3: Create diff-triage log

**Files:**
- Create: `/tmp/mv-replay-triage.md`

- [ ] **Step 1: Scaffold the triage log**

```bash
cat > /tmp/mv-replay-triage.md <<'EOF'
# Step 4 Phase 1 Diff Triage

Template render: `/tmp/mv-replay` (copier copy of
fastmcp-server-template v1.0.0 with MV's answers).
MV: `/mnt/code/markdown-mcp` @ v1.25.0.

Diff source: `/tmp/mv-replay-diff.txt`

## Class A — Domain content (no action)

(Files that only exist in MV because they implement vault features.)

## Class B — Infra bug in MV (fix MV during retrofit)

## Class C — Hybrid file, domain content preserved via sentinels

## Class D — Infra bug in template (cut v1.0.x patch)

## Class E — Acceptable divergence (document + move on)

EOF
```

- [ ] **Step 2: Commit the empty triage log to the replay scratch dir** (so
  git history on /tmp/mv-replay stays clean if we re-render)

Actually, the triage log lives in `/tmp`, not in any repo — no commit needed.
Continue to Task B4.

### Task B4: Classify every diff entry

**Files:**
- Modify: `/tmp/mv-replay-triage.md`

This task is manual and high-judgment. For each diff entry in
`/tmp/mv-replay-diff.txt`, file it into one of the 5 classes in the triage
log. Use the guidance below.

- [ ] **Step 1: Read the full diff and split into entries**

```bash
less /tmp/mv-replay-diff.txt
```

Diff entries look like `Only in X: Y`, `Only in Y: X`, or `diff -r A/f B/f`.

- [ ] **Step 2: For each `Only in /mnt/code/markdown-mcp: <X>` entry**

Decision rule:
- File implements vault/FTS5/embeddings/MCP-Apps/managers logic → **Class A**.
- File is infra the template should have produced but didn't → **Class D**
  (note it, fix template in Task B5).
- File is deliberately MV-only infra the template shouldn't produce → **Class E**
  (document reason).

Examples (from spec §"Expected C-class hotspots" and general knowledge):
- `src/markdown_vault_mcp/collection.py` → A
- `src/markdown_vault_mcp/fts_index.py` → A
- `src/markdown_vault_mcp/vector_index.py` → A
- `src/markdown_vault_mcp/managers/*.py` → A
- `src/markdown_vault_mcp/scanner.py`, `providers.py`, `tracker.py` → A
- `src/markdown_vault_mcp/_server_apps.py`, `_icons.py`, `_server_tools.py`,
  `_server_resources.py`, `_server_prompts.py` → A (MV-specific composition)
- `src/markdown_vault_mcp/artifacts.py`, `git.py` → A
- `src/markdown_vault_mcp/static/` (icons, app.html, app.src.html) → A
- `tests/test_*.py` for vault features → A
- `docs/design.md`, `docs/guides/*`, `docs/tools/*`, `docs/resources.md`,
  `docs/prompts.md`, `docs/configuration.md` etc. → A
- `SYNC.md` → E (retires in Step 8; keep for now)

- [ ] **Step 3: For each `Only in /tmp/mv-replay: <X>` entry**

Decision rule:
- Template produced a file MV doesn't have, but MV *should* have it → **Class B**.
- Template produced a file MV doesn't have, deliberately different → **Class E**.

- [ ] **Step 4: For each `diff -r <template> <mv>` entry**

Decision rule:
- Diff is entirely within sentinel blocks (`PROJECT-DEPS-START..END`,
  `CONFIG-FIELDS-START..END`, `DOMAIN-START..END`, etc.) → **Class C**.
- Diff shows template-produced scaffolding replaced by MV's full implementation
  of the same file's purpose (e.g., `tools.py`, `resources.py`, `prompts.py`) → **Class C**.
- Diff shows template produced wrong infra (missing line, wrong default) → **Class D**.
- Diff is MV has richer infra than template *should* have (e.g., extra
  server.json env vars for vault-specific config) → **Class C** if in a hybrid
  file with sentinels / **Class E** otherwise (document why template
  shouldn't carry it).

- [ ] **Step 5: Save the triage log**

The triage log at `/tmp/mv-replay-triage.md` now has every diff entry filed
into exactly one class. Verify:

```bash
grep -c '^- ' /tmp/mv-replay-triage.md
```

Expected: non-zero; the count should roughly match (give or take grouping)
the number of distinct paths in `/tmp/mv-replay-diff.txt`.

### Task B5: Apply template patches for Class D items — iterate

**Files:**
- Modify (in `/mnt/code/fastmcp-server-template`): whichever template files
  are wrong, per Class D findings.

This task is an **iterative loop**. Each iteration: pick the Class D items,
patch the template, cut `v1.0.N` patch release, re-render, re-diff, re-triage.
Stop when only Class A/C/E remain.

- [ ] **Step 1: If the Class D list in `/tmp/mv-replay-triage.md` is empty, skip to Task B6.**

- [ ] **Step 2: Check out a patch branch on the template**

```bash
cd /mnt/code/fastmcp-server-template
git checkout main
git pull --ff-only
git checkout -b fix/mv-replay-findings-NNN   # replace NNN per iteration
```

- [ ] **Step 3: Apply each Class D fix**

For each Class D item in the triage log, edit the corresponding `.jinja`
file under `/mnt/code/fastmcp-server-template`. Keep edits minimal; the
goal is to close the diff, not to reshape the template.

Commit each logical fix as `fix(template): <what>`. Example:

```bash
cd /mnt/code/fastmcp-server-template
# edit Dockerfile.jinja ...
git add Dockerfile.jinja
git commit -m "fix(template): add gosu install to Dockerfile

Template was missing the gosu binary copy that the entrypoint
depends on.  Surfaced by mv-replay diff (Class D)."
```

- [ ] **Step 4: Run the template's self-test CI locally**

```bash
cd /mnt/code/fastmcp-server-template
# This is what template-ci.yml does in CI; run it as a smoke test.
rm -rf /tmp/template-selftest
mkdir -p /tmp/template-selftest
copier copy --trust --defaults \
  --data project_name=example-mcp \
  --data pypi_name=example-mcp \
  --data python_module=example_mcp \
  --data env_prefix=EXAMPLE_MCP \
  --data human_name='Example MCP' \
  --data domain_description='Example MCP server' \
  --data github_org=example \
  --data docker_registry=ghcr.io/example \
  /mnt/code/fastmcp-server-template \
  /tmp/template-selftest
cd /tmp/template-selftest
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest -x -q
cd -
```

Expected: all checks pass. If any fails, the template patch introduced a
regression — fix before continuing.

- [ ] **Step 5: Push the branch and open a PR**

```bash
cd /mnt/code/fastmcp-server-template
git push -u origin fix/mv-replay-findings-NNN
gh pr create --repo pvliesdonk/fastmcp-server-template \
  --title "fix(template): mv-replay findings iteration NNN" \
  --body "$(cat <<'EOF'
## Summary

Patch batch found via Step 4 bootstrap-replay of the template against
markdown-vault-mcp v1.25.0.  Each fix closes a Class D diff entry in
`/tmp/mv-replay-triage.md`.

## Diffs closed

<bulleted list — one line per Class D item resolved>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Wait for CI green, then merge via the repo's normal PR flow (squash or
merge per repo rules).

- [ ] **Step 6: Cut a patch release**

```bash
gh workflow run release.yml \
  --repo pvliesdonk/fastmcp-server-template \
  -f prerelease=false
```

Wait for completion. Verify the new tag landed:

```bash
git -C /mnt/code/fastmcp-server-template fetch --tags origin
git -C /mnt/code/fastmcp-server-template tag --sort=-v:refname | head -3
```

Expected: new `v1.0.N` tag visible (PSR increments from v1.0.0 → v1.0.1
on first `fix:` commit, v1.0.2 on the next, etc.).

- [ ] **Step 7: Re-render into scratch dir using the new tag**

```bash
NEW_TAG=$(git -C /mnt/code/fastmcp-server-template tag --sort=-v:refname | head -1)
echo "Re-rendering with $NEW_TAG"
git -C /mnt/code/fastmcp-server-template checkout "$NEW_TAG"
rm -rf /tmp/mv-replay
mkdir -p /tmp/mv-replay && git -C /tmp/mv-replay init -q
copier copy --trust \
  --data-file /tmp/mv-answers.yml \
  --vcs-ref "$NEW_TAG" \
  /mnt/code/fastmcp-server-template \
  /tmp/mv-replay
```

- [ ] **Step 8: Re-run the diff and re-triage**

```bash
/tmp/mv-replay-diff.sh | tee /tmp/mv-replay-diff.txt | head -200
# Update /tmp/mv-replay-triage.md: Class D items that are closed should
# be struck through / removed; any newly-surfaced diffs triaged fresh.
```

- [ ] **Step 9: If Class D is now empty, move to Task B6. Otherwise, loop back to Step 1 of this task.**

Budget guidance: expect 2-3 iterations. If you're on iteration 5+, the
template has deeper issues than a patch series can fix — stop and
escalate.

### Task B6: Freeze Phase 1 outcome

**Files:**
- Modify: `/tmp/mv-replay-triage.md` (add summary)

- [ ] **Step 1: Record the final template version used**

```bash
FINAL_TAG=$(git -C /mnt/code/fastmcp-server-template tag --sort=-v:refname | head -1)
echo "Final template version for retrofit: $FINAL_TAG"
echo "$FINAL_TAG" > /tmp/mv-replay-template-version.txt
```

- [ ] **Step 2: Append a summary to the triage log**

Add a section at the top of `/tmp/mv-replay-triage.md`:

```markdown
## Phase 1 outcome

- Final template version: vX.Y.Z
- Iterations run: N
- Class D findings fixed: M
- Class E acceptable divergences: list them here with one-line rationale

**Gate:** Diff contains only Class A and approved Class C/E entries.
Phase 1 DONE.
```

Fill in the numbers from actual results.

- [ ] **Step 3: Copy triage log into MV repo for archival**

```bash
mkdir -p /mnt/code/markdown-mcp/docs/superpowers/notes
cp /tmp/mv-replay-triage.md \
   /mnt/code/markdown-mcp/docs/superpowers/notes/2026-04-21-step4-replay-triage.md
```

(Will be committed as part of the Phase 2 retrofit PR.)

---

## Phase C — Retrofit to MV

### Task C1: Set up the retrofit branch

**Files:**
- Branch: `/mnt/code/markdown-mcp` → `chore/adopt-fastmcp-template`

- [ ] **Step 1: Start from a clean main**

```bash
cd /mnt/code/markdown-mcp
git checkout main
git pull --ff-only
git status
```

Expected: `On branch main`, clean tree or only the untracked plan/spec docs.

- [ ] **Step 2: Create the retrofit branch**

```bash
git checkout -b chore/adopt-fastmcp-template
```

### Task C2: Stage MV's current state for rollback reference

**Files:**
- No edits; we just capture a reference.

- [ ] **Step 1: Tag current HEAD locally so we can diff against it**

```bash
git tag --force step4-pre-retrofit HEAD
```

Later we'll use `git diff step4-pre-retrofit..HEAD -- <file>` to inspect
what copier overwrote on a per-file basis.

### Task C3: Run `copier copy --overwrite` against MV

**Files:**
- Modifies: many files in `/mnt/code/markdown-mcp` (copier-driven)
- Creates: `/mnt/code/markdown-mcp/.copier-answers.yml`

- [ ] **Step 1: Check out the final template version**

```bash
FINAL_TAG=$(cat /tmp/mv-replay-template-version.txt)
git -C /mnt/code/fastmcp-server-template checkout "$FINAL_TAG"
```

- [ ] **Step 2: Run copier copy --overwrite**

```bash
cd /mnt/code/markdown-mcp
copier copy --overwrite --trust \
  --data-file /tmp/mv-answers.yml \
  --vcs-ref "$FINAL_TAG" \
  /mnt/code/fastmcp-server-template \
  .
```

Expected: copier reports files written. `.copier-answers.yml` appears at
the repo root. No prompts (answers file supplies everything).

- [ ] **Step 3: Verify .copier-answers.yml pins the template version**

```bash
cat /mnt/code/markdown-mcp/.copier-answers.yml
```

Expected: contains `_src_path: /mnt/code/fastmcp-server-template` (or the
URL form if using github ref) and `_commit: <FINAL_TAG>`, plus the 8
answer keys.

- [ ] **Step 4: Inspect the overall scope of changes**

```bash
cd /mnt/code/markdown-mcp
git status
git diff --stat | tail -30
```

Expected: many files `Modified`, `Added`, or `Deleted`. The answers file
is new. Do NOT commit yet — Task C4 restores domain content.

### Task C4: Restore domain content in Class C hybrid files

**Files:**
- `/mnt/code/markdown-mcp/pyproject.toml` (sentinel: PROJECT-DEPS, PROJECT-EXTRAS)
- `/mnt/code/markdown-mcp/src/markdown_vault_mcp/config.py` (sentinel: CONFIG-FIELDS, CONFIG-FROM-ENV)
- `/mnt/code/markdown-mcp/CLAUDE.md` (sentinel: DOMAIN)
- `/mnt/code/markdown-mcp/README.md` (full replacement; the template version is a stub)
- `/mnt/code/markdown-mcp/src/markdown_vault_mcp/tools.py`, `resources.py`, `prompts.py` (full replacement)
- `/mnt/code/markdown-mcp/server.json` (vault-specific env vars added back to PyPI+OCI packages)
- `/mnt/code/markdown-mcp/docs/` (restore MV's MkDocs site where template only provides skeleton)
- `/mnt/code/markdown-mcp/Dockerfile` (keep if diff is Class C; fix template if Class D)

Each sub-step below is one Class C hotspot. Run `git diff step4-pre-retrofit -- <path>` first to see exactly what copier overwrote, then restore domain content.

- [ ] **Step 1: pyproject.toml — restore MV deps and extras between sentinels**

```bash
cd /mnt/code/markdown-mcp
git diff step4-pre-retrofit -- pyproject.toml | less
```

Look for the blocks:
- `# PROJECT-DEPS-START` … `# PROJECT-DEPS-END`
- `# PROJECT-EXTRAS-START` … `# PROJECT-EXTRAS-END`

Restore MV's dependencies (everything between these sentinels in the
pre-retrofit version) into the post-copier file. Use `git show step4-pre-retrofit:pyproject.toml > /tmp/pyproject.pre.toml` to get the reference, then copy the sentinel block contents into the new file.

- [ ] **Step 2: src/markdown_vault_mcp/config.py — restore between sentinels**

```bash
git diff step4-pre-retrofit -- src/markdown_vault_mcp/config.py | less
```

Look for `# CONFIG-FIELDS-START`/`END` and `# CONFIG-FROM-ENV-START`/`END`.
Also restore MV's auth wrapper functions (`build_bearer_auth`,
`build_oidc_auth`, `build_remote_auth`, `resolve_auth_mode`) — the test
suite locks these in as MV-domain content (spec §"Expected C-class hotspots").

- [ ] **Step 3: CLAUDE.md — restore between DOMAIN sentinels**

```bash
git diff step4-pre-retrofit -- CLAUDE.md | less
```

Look for `<!-- DOMAIN-START -->` … `<!-- DOMAIN-END -->`. Restore all MV
project-specific content (large blocks) between these markers.

- [ ] **Step 4: README.md — full restore**

```bash
git show step4-pre-retrofit:README.md > README.md
```

Template produces a stub; MV has a full docs entry. Full replace is correct.

- [ ] **Step 5: src/markdown_vault_mcp/tools.py, resources.py, prompts.py — full restore**

```bash
for f in src/markdown_vault_mcp/tools.py src/markdown_vault_mcp/resources.py src/markdown_vault_mcp/prompts.py; do
  git show step4-pre-retrofit:"$f" > "$f"
done
```

These are in `_skip_if_exists` in the template, so copier should not have
overwritten them if MV already had them. Verify:

```bash
git diff step4-pre-retrofit -- src/markdown_vault_mcp/tools.py src/markdown_vault_mcp/resources.py src/markdown_vault_mcp/prompts.py
```

Expected: no diff (they were skipped). If they *did* change, the template's
`_skip_if_exists` list is wrong — flag as Class D, fix template, restart retrofit.

- [ ] **Step 6: server.json — merge domain env vars**

```bash
git diff step4-pre-retrofit -- server.json | less
```

MV has many vault-specific env vars (`EVENT_STORE_URL`, `APP_DOMAIN`,
`ATTACHMENT_EXTENSIONS`, `MAX_ATTACHMENT_SIZE_MB`, git-related vars,
embedding-provider vars, etc.) in both PyPI and OCI packages. Template
produces the generic baseline.

Choose approach:
- If MV already had sentinel blocks in server.json.jinja → restore inside them.
- If not (most likely for now) → full restore from `step4-pre-retrofit` and
  file a follow-up issue to sentinel-ize server.json in the template.

Simple path:

```bash
git show step4-pre-retrofit:server.json > server.json
```

- [ ] **Step 7: src/markdown_vault_mcp/mcp_server.py — full restore**

```bash
git diff step4-pre-retrofit -- src/markdown_vault_mcp/mcp_server.py
```

Template's `make_server()` is generic; MV's has vault-specific tool/resource/
prompt wiring (`_server_tools`, `_server_resources`, `_server_prompts`,
`_server_apps`, SPA registration, read_only gating). Full restore:

```bash
git show step4-pre-retrofit:src/markdown_vault_mcp/mcp_server.py \
  > src/markdown_vault_mcp/mcp_server.py
```

Also restore sibling MV-domain modules:

```bash
for f in \
  src/markdown_vault_mcp/_server_apps.py \
  src/markdown_vault_mcp/_server_deps.py \
  src/markdown_vault_mcp/_server_tools.py \
  src/markdown_vault_mcp/_server_resources.py \
  src/markdown_vault_mcp/_server_prompts.py \
  src/markdown_vault_mcp/_icons.py \
  src/markdown_vault_mcp/artifacts.py \
  src/markdown_vault_mcp/git.py; do
  if git cat-file -e step4-pre-retrofit:"$f" 2>/dev/null; then
    git show step4-pre-retrofit:"$f" > "$f"
  fi
done
```

(If any path doesn't exist pre-retrofit, skip it; the `git cat-file -e`
check guards that.)

- [ ] **Step 8: cli.py — inspect and decide**

```bash
git diff step4-pre-retrofit -- src/markdown_vault_mcp/cli.py
```

Per spec, MV's cli.py already uses core's `configure_logging_from_env` and
`normalise_http_path` — so it should be close to template-compatible.

- If diff is small and template-produced version works → keep template version.
- If diff shows MV has vault-specific CLI features (e.g., `--vault` flag,
  reindex commands) → full restore from `step4-pre-retrofit`.

Apply the chosen resolution.

- [ ] **Step 9: docs/ — restore MV's MkDocs site**

```bash
git diff step4-pre-retrofit -- docs/ | head -100
```

MV has a full published MkDocs site (design.md, tools/, guides/,
configuration.md, installation.md, index.md, resources.md, prompts.md,
plus superpowers/ specs and plans). Template produces a skeleton.

Restore every MV doc file the template wasn't supposed to own:

```bash
# Use git to restore all tracked docs/ files from the pre-retrofit ref,
# EXCEPT any new files the template legitimately added at a path MV didn't have.
git diff --name-only step4-pre-retrofit HEAD -- docs/ | while read f; do
  if git cat-file -e step4-pre-retrofit:"$f" 2>/dev/null; then
    git show step4-pre-retrofit:"$f" > "$f"
  fi
done
```

Double-check `mkdocs.yml` separately — it was probably rewritten by the
template. Restore MV's version:

```bash
if git cat-file -e step4-pre-retrofit:mkdocs.yml 2>/dev/null; then
  git show step4-pre-retrofit:mkdocs.yml > mkdocs.yml
fi
```

- [ ] **Step 10: Dockerfile / docker-entrypoint.sh / compose.yml — verify**

```bash
git diff step4-pre-retrofit -- Dockerfile docker-entrypoint.sh compose.yml
```

Per spec: template should produce MV's exact shape (PUID/PGID entrypoint
+ gosu). If diff shows template produced a simpler version, that's
**Class D** — stop retrofit, go back to Task B5 with the finding.

If the template version matches (or the only diffs are cosmetic), keep
the template version.

- [ ] **Step 11: Restore all Class A domain files that copier didn't write**

Most domain files are only in MV and copier never touched them, so no
restore needed. But verify nothing went missing:

```bash
git status --porcelain | grep '^ D' | head -30
```

Any `D` lines indicate files copier (or our restore steps) deleted. For
every line that's a Class A domain path, `git checkout step4-pre-retrofit -- <path>`
to restore it.

- [ ] **Step 12: Sanity-check what remains staged for commit**

```bash
git status
git diff --stat HEAD
```

Expected: the diff should now be much smaller — ideally just:
- `.copier-answers.yml` (new)
- `docs/superpowers/notes/2026-04-21-step4-replay-triage.md` (new, copied in B6)
- Infra files that legitimately changed (`.github/workflows/*.yml`,
  `Dockerfile`, `pyproject.toml` template-owned sections, `CLAUDE.md`
  template-owned sections, etc.)
- Zero domain changes under `src/markdown_vault_mcp/collection.py` etc.

### Task C5: Run the gate locally

**Files:**
- No edits; validation only.

- [ ] **Step 1: Install deps**

```bash
cd /mnt/code/markdown-mcp
uv sync --all-extras --dev
```

Expected: clean sync, no resolver errors.

- [ ] **Step 2: Ruff check --fix**

```bash
uv run ruff check --fix .
```

Expected: exit 0 or only auto-fixed items.

- [ ] **Step 3: Ruff format**

```bash
uv run ruff format .
```

Expected: may reformat files; exit 0.

- [ ] **Step 4: Ruff format --check**

```bash
uv run ruff format --check .
```

Expected: `All done!` / exit 0.

- [ ] **Step 5: mypy**

```bash
uv run mypy src/
```

Expected: `Success: no issues found in N source files`.

- [ ] **Step 6: pytest**

```bash
uv run pytest -x -q
```

Expected: all ~1395 tests pass. If any fail: the retrofit has silently
broken something. Typical culprits: sentinel-block restoration missed a
function, import paths shifted, test fixture paths stale.

- [ ] **Step 7: Resolve failures if any**

If the gate fails, restore the relevant domain content (most commonly via
`git checkout step4-pre-retrofit -- <path>`) and re-run. Do not skip gate
failures; they indicate the retrofit is incomplete.

### Task C6: Commit the retrofit

**Files:**
- Create: commit on `chore/adopt-fastmcp-template`

- [ ] **Step 1: Stage everything**

```bash
cd /mnt/code/markdown-mcp
git add -A
git status
```

Verify the staged set matches expectations (answers file + infra files +
triage note; no spurious domain edits).

- [ ] **Step 2: Commit**

```bash
FINAL_TAG=$(cat /tmp/mv-replay-template-version.txt)
git commit -m "$(cat <<EOF
chore: adopt fastmcp-server-template $FINAL_TAG

Bootstraps MV onto the copier template via \`copier copy --overwrite\`.
Generated files (including .github/workflows, Dockerfile, CLAUDE.md
template-owned sections, pyproject.toml template-owned sections) are
now managed by the template; future \`copier update\` runs will merge
template updates back into MV.

Domain content preserved:
- src/markdown_vault_mcp/* (all vault/FTS5/embeddings/MCP-Apps modules)
- server.json env vars
- Full MkDocs site under docs/
- README.md
- CLAUDE.md DOMAIN-sentinel block
- pyproject.toml PROJECT-DEPS + PROJECT-EXTRAS sentinel blocks
- config.py CONFIG-FIELDS + CONFIG-FROM-ENV sentinel blocks plus
  auth wrapper functions

Phase 1 replay triage archived at
docs/superpowers/notes/2026-04-21-step4-replay-triage.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; pre-commit hooks (ruff, mypy, etc.) pass.

### Task C7: Push the branch and open the retrofit PR

**Files:**
- No edits; PR creation.

- [ ] **Step 1: Push**

```bash
cd /mnt/code/markdown-mcp
git push -u origin chore/adopt-fastmcp-template
```

- [ ] **Step 2: Open PR**

```bash
FINAL_TAG=$(cat /tmp/mv-replay-template-version.txt)
gh pr create \
  --title "chore: adopt fastmcp-server-template $FINAL_TAG" \
  --body "$(cat <<EOF
## Summary

Step 4 of the fastmcp-pvl-core extraction: MV adopts the copier
template.  Future template updates will flow in via \`copier update\`.

- Replay was run against MV v1.25.0; triage log archived at
  \`docs/superpowers/notes/2026-04-21-step4-replay-triage.md\`.
- All infra diffs were closed via template patches.  Final template
  version: \`$FINAL_TAG\`.
- Domain content preserved in hybrid sentinel-block files and full-file
  restores (see commit body for full list).

## Test plan

- [x] \`uv run pytest -x -q\` — all tests pass
- [x] \`uv run ruff check .\` — clean
- [x] \`uv run ruff format --check .\` — clean
- [x] \`uv run mypy src/\` — clean
- [ ] CI green on PR
- [ ] Post-merge: \`v1.26.0-rc.1\` smoke release (Step 4 Phase 3a)
- [ ] Post-merge: \`v1.26.0\` stable release (Step 4 Phase 3b)

## Spec

\`docs/superpowers/specs/2026-04-21-step4-bootstrap-replay-design.md\`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Wait for CI**

```bash
gh pr checks --watch
```

Expected: all required checks green (build, ruff, mypy, tests, codecov/patch
via diff-cover, claude-review, gemini-code-assist).

### Task C8: Merge the retrofit PR

**Files:**
- Merges branch into `main`.

- [ ] **Step 1: Merge (repo allows only merge commits, not squash)**

```bash
gh pr merge --merge
```

- [ ] **Step 2: Update local main**

```bash
git checkout main
git pull --ff-only
git branch -D chore/adopt-fastmcp-template
git tag --delete step4-pre-retrofit
```

---

## Phase D — Release pipeline validation 3a (v1.26.0-rc.1)

### Task D1: Trigger the prerelease workflow

**Files:**
- No edits; workflow dispatch.

- [ ] **Step 1: Confirm main is green**

```bash
cd /mnt/code/markdown-mcp
git checkout main
git pull --ff-only
gh run list --branch main --limit 3
```

Expected: latest `release.yml`/CI runs show completed successfully.

- [ ] **Step 2: Trigger prerelease workflow**

```bash
gh workflow run release.yml \
  -f prerelease=true \
  -f prerelease_token=rc
```

- [ ] **Step 3: Watch the run**

```bash
sleep 5
gh run list --workflow release.yml --limit 1
RUN_ID=$(gh run list --workflow release.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID"
```

Expected: workflow completes successfully. PSR cuts `v1.26.0-rc.1`.
PyPI publish step is skipped (MV's PSR config gates PyPI on prereleases).

### Task D2: Verify prerelease artifacts

**Files:**
- No edits; verification only.

- [ ] **Step 1: Verify the tag and version**

```bash
git -C /mnt/code/markdown-mcp fetch --tags origin
git -C /mnt/code/markdown-mcp tag --sort=-v:refname | head -3
```

Expected: `v1.26.0-rc.1` present.

- [ ] **Step 2: Verify GitHub release and MCPB asset**

```bash
gh release view v1.26.0-rc.1 --json tagName,prerelease,assets
```

Expected: `prerelease: true`, `assets` contains an `.mcpb` file.

- [ ] **Step 3: Verify Docker image published multi-arch**

```bash
docker manifest inspect ghcr.io/pvliesdonk/markdown-vault-mcp:v1.26.0-rc.1 \
  | jq '.manifests[].platform'
```

Expected: at least `linux/amd64` and `linux/arm64` entries.

- [ ] **Step 4: Verify server.json bump**

```bash
git show v1.26.0-rc.1:server.json | jq '.version, .packages[].version'
```

Expected: all three values are `"1.26.0-rc.1"`.

- [ ] **Step 5: Verify single release commit**

```bash
git show --stat v1.26.0-rc.1 | head -30
```

Expected: single commit contains `pyproject.toml`, `CHANGELOG.md`,
`server.json` bumps. (Not split across multiple commits.)

- [ ] **Step 6: Verify PyPI was NOT published**

```bash
curl -s https://pypi.org/pypi/markdown-vault-mcp/json | jq '.releases | keys' \
  | grep '1.26.0-rc.1' && echo "UNEXPECTED: rc on PyPI" || echo "OK: rc not on PyPI"
```

Expected: `OK: rc not on PyPI`.

### Task D3: Smoke-test the rc image

**Files:**
- Create: `/tmp/smoke-vault/` (throwaway)

- [ ] **Step 1: Prepare throwaway vault**

```bash
rm -rf /tmp/smoke-vault
mkdir -p /tmp/smoke-vault
cat > /tmp/smoke-vault/hello.md <<'EOF'
---
title: Hello
tags: [smoke-test]
---

# Hello

Smoke test note for v1.26.0-rc.1.
EOF
```

- [ ] **Step 2: Run stdio transport smoke**

```bash
docker run --rm -i \
  -v /tmp/smoke-vault:/data/vault:ro \
  -e MARKDOWN_VAULT_MCP_VAULT_PATH=/data/vault \
  ghcr.io/pvliesdonk/markdown-vault-mcp:v1.26.0-rc.1 \
  --help
```

Expected: CLI help output from `markdown-vault-mcp`; container exits 0.

- [ ] **Step 3: Run HTTP transport smoke**

```bash
docker run -d --name mv-rc-smoke \
  -v /tmp/smoke-vault:/data/vault \
  -p 18000:8000 \
  -e MARKDOWN_VAULT_MCP_VAULT_PATH=/data/vault \
  ghcr.io/pvliesdonk/markdown-vault-mcp:v1.26.0-rc.1 \
  --http --port 8000
sleep 8
docker logs mv-rc-smoke | tail -20
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:18000/mcp
docker rm -f mv-rc-smoke
```

Expected: container starts, logs show `Server config: version=1.26.0-rc.1`
and `Server listening on http://0.0.0.0:8000/mcp`. `curl` returns an HTTP
status (probably `406` or `401` — both fine; it means MCP is up, we just
didn't send a valid MCP request).

- [ ] **Step 4: Decide go/no-go**

- All three checks green → proceed to Phase E.
- Any check fails → fix forward:
  - For workflow bugs: file an issue, do NOT block Step 4; see spec
    §"Rollback stance".
  - For template bugs surfaced only at release time: rollback Task C8
    is not feasible (already merged). File an issue, add a follow-up
    commit on main, cut `v1.26.0-rc.2`.

---

## Phase E — Release pipeline validation 3b (v1.26.0 stable)

### Task E1: Trigger the stable release workflow

**Files:**
- No edits; workflow dispatch.

- [ ] **Step 1: Confirm rc smoke was green**

Verify Phase D is complete (all of D1/D2/D3 ticked). Do not start Phase E
until D is done.

- [ ] **Step 2: Trigger stable workflow**

```bash
gh workflow run release.yml -f prerelease=false
```

- [ ] **Step 3: Watch the run**

```bash
sleep 5
RUN_ID=$(gh run list --workflow release.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID"
```

Expected: all publish jobs succeed (pypi-publish, docker-publish,
publish-registry, publish-linux-packages, mcpb-publish, release).

### Task E2: Verify all six publish targets

**Files:**
- No edits; verification only.

- [ ] **Step 1: PyPI**

```bash
curl -sS https://pypi.org/pypi/markdown-vault-mcp/json \
  | jq -r '.info.version'
```

Expected: `1.26.0`.

- [ ] **Step 2: GHCR**

```bash
docker manifest inspect ghcr.io/pvliesdonk/markdown-vault-mcp:v1.26.0 \
  | jq '.manifests[].platform'
```

Expected: `linux/amd64` + `linux/arm64` entries.

- [ ] **Step 3: MCP Registry**

```bash
curl -sS "https://registry.modelcontextprotocol.io/v0/servers?search=markdown-vault-mcp" \
  | jq '.servers[] | select(.name=="io.github.pvliesdonk/markdown-vault-mcp") | .versions[0]'
```

Expected: a version entry for `1.26.0`.

- [ ] **Step 4: Linux packages**

```bash
gh release view v1.26.0 --json assets -q '.assets[].name' | grep -E '\.(deb|rpm)$'
```

Expected: at least one `.deb` and one `.rpm` (architecture-tagged).

- [ ] **Step 5: GitHub release with CHANGELOG**

```bash
gh release view v1.26.0 --json tagName,name,body -q '.body' | head -40
```

Expected: CHANGELOG entry for v1.26.0 (likely empty `Features`/populated
`Other` sections — the retrofit was a chore commit).

- [ ] **Step 6: MCPB**

```bash
gh release view v1.26.0 --json assets -q '.assets[].name' | grep -i '\.mcpb$'
```

Expected: one `.mcpb` asset.

- [ ] **Step 7: Cross-check all six**

If any of E2 steps 1-6 failed, file a release-pipeline follow-up issue.
Per spec §"Rollback stance", E failure does NOT block Step 4 closure,
but the issue must be tracked.

---

## Phase F — Closeout

### Task F1: Update the extraction handoff memory

**Files:**
- Modify: `/home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/fastmcp_pvl_core_extraction_handoff.md`

- [ ] **Step 1: Read current memory**

```bash
cat /home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/fastmcp_pvl_core_extraction_handoff.md
```

- [ ] **Step 2: Update Step 4 status to DONE**

Replace any pending-Step-4 language with a DONE block that records:
- Final template version used for retrofit.
- MV version shipped on the retrofit (1.26.0).
- Any v1.0.x template patches cut and why (one line each).
- Explicit next step: Step 5 (migrate image-generation-mcp onto copier scaffold).

Use the Edit tool against the memory file. Example new block:

```markdown
## Step 4 — DONE 2026-04-21

- Template replay vs MV v1.25.0 closed via N template patches
  (v1.0.1, v1.0.2, ... if any) — see
  `docs/superpowers/notes/2026-04-21-step4-replay-triage.md` in
  markdown-mcp.
- MV retrofitted via `copier copy --overwrite` on branch
  `chore/adopt-fastmcp-template`; `.copier-answers.yml` pins
  template vX.Y.Z.
- MV v1.26.0 released (PyPI + GHCR + MCP Registry + Linux packages +
  GH release + MCPB).  Release pipeline validated end-to-end.

**Next:** Step 5 — migrate `image-generation-mcp` onto
`fastmcp-server-template` via same bootstrap-replay flow.
```

- [ ] **Step 3: Update MEMORY.md index line for the handoff memory**

```bash
grep 'fastmcp_pvl_core_extraction_handoff' \
  /home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/MEMORY.md
```

Adjust the one-line hook so it reads "Steps 1-4 DONE; Steps 5-8 remain"
(was "Steps 1-3 DONE").

### Task F2: Update project status line in MEMORY.md

**Files:**
- Modify: `/home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/MEMORY.md`

- [ ] **Step 1: Add a project-status line for v1.26.0**

Find the existing "PR #403 merged…" / "v1.25.0 released…" block in
`MEMORY.md` and append:

```markdown
- PR #<retrofit-PR> merged: chore: adopt fastmcp-server-template vX.Y.Z
  (Step 4 of fastmcp-pvl-core extraction).  `.copier-answers.yml` now
  governs MV's infra; future template changes land via `copier update`.
- **v1.26.0 released 2026-04-21** — first release after copier adoption.
```

Fill in the real PR number from `gh pr view chore/adopt-fastmcp-template`
and the real template version.

- [ ] **Step 2: Verify MEMORY.md size is still under 24.4KB**

```bash
wc -c /home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/MEMORY.md
```

Expected: < 25000 bytes. If over, prune older lines (the file already
warns it's at the limit).

### Task F3: Confirm Step 4 success criteria

**Files:**
- No edits; final checklist.

- [ ] **Step 1: Walk the spec's Success criteria (§"Success criteria")**

For each of the 6 criteria, verify:

1. Replay diff contained only Class A/C/E — check triage log summary.
2. `.copier-answers.yml` exists, pinned, committed on main — `git log --all -- .copier-answers.yml`.
3. Retrofit commit passed gate — CI run on retrofit PR green.
4. `v1.26.0-rc.1` smoke passed — Task D2/D3 green.
5. `v1.26.0` stable shipped to all six targets — Task E2 green.
6. Memory updated — Task F1 complete.

- [ ] **Step 2: Announce Step 4 complete**

Post a one-line summary to the user describing what was released and
what Step 5 will cover.

---

## Notes on iteration/looping

Tasks B5 and (rarely) B6 are the only looping sections. Every other task
is linear. If Task C5 (gate) fails, the usual fix is inside Task C4
(restore missed sentinel content) — treat C4 and C5 as a tight loop
until C5 is green, then proceed to C6.

If Task C5 failure is caused by a template bug (not a restore miss), the
rollback is:
1. `git reset --hard step4-pre-retrofit` on the retrofit branch.
2. Jump back to Task B5 with the new finding.
3. Cut another template patch.
4. Restart at Task C3 with the new template version.

## Cross-cutting: do NOT squash-merge

MV's repo ruleset only allows merge commits, not squash (see CLAUDE.md
"Repo Ruleset Notes"). The retrofit PR must be merged via
`gh pr merge --merge` — never `--squash`, and never `--admin`.
