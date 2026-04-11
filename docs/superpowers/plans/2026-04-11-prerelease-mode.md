# Pre-release Mode for Release Workflow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `prerelease` boolean input to `.github/workflows/release.yml` that runs the full release pipeline (semantic-release, Docker, mcpb bundle) while skipping PyPI, the Linux packages, the Claude Code catalog PR, the MCP Registry publish, and the manifest-bump commit. Defaults to `true` so real releases become an explicit opt-in.

**Architecture:** Single workflow file edited in place. Step-level and job-level `if:` gates keyed off `inputs.prerelease`. Docker tags use `docker/metadata-action`'s native `enable=<bool>` modifier. Two small docs updates accompany the change (per `CLAUDE.md` Documentation Discipline).

**Tech Stack:** GitHub Actions YAML, `python-semantic-release@v10.5.3`, `docker/metadata-action@v5`, `mcpb` bundle toolchain (unchanged).

**Spec:** `docs/superpowers/specs/2026-04-11-prerelease-mode-release-workflow-design.md`

**Branch:** `feat/prerelease-mode` (already created from `main`, spec already committed as `6dc2c14`).

---

## Prerequisites — read before starting

1. You are working on branch `feat/prerelease-mode` in `/mnt/code/markdown-mcp`. Confirm with `git status` and `git branch --show-current`.
2. The target file is `.github/workflows/release.yml`. This workflow has 8 jobs today: `release`, `publish-pypi`, `publish-docker`, `publish-linux-packages`, `build-mcpb`, `publish-mcpb`, `publish-claude-plugin-pr`, `publish-registry`.
3. Read the spec end to end before touching the file — the matrix in §Job-by-job behavior is load-bearing.
4. There are **no Python changes** in this plan. `pytest`, `mypy`, and `ruff` will all be no-ops for coverage, but they still must pass the repo's existing pre-commit hooks on commit.
5. Patch coverage (diff-cover) has nothing to cover — no `.py` lines are touched. CI's `codecov/patch` status will post success automatically (see `.github/workflows/coverage-status.yml`).

---

## Task 1: Add `prerelease` input to `workflow_dispatch`

**Files:**
- Modify: `.github/workflows/release.yml:3-14`

- [ ] **Step 1: Open the file and locate the `workflow_dispatch` block**

The current block (lines 3–14) looks like:

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
```

- [ ] **Step 2: Add the `prerelease` input directly after the `force` input**

Replace the block above with:

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

Note the **`default: true`**. This is intentional: real releases become an explicit opt-in. Do not change this default to `false`.

- [ ] **Step 3: Sanity-check YAML syntax**

Run:

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo OK
```

Expected output: `OK`

If you see a YAML parse error, re-read the block — indentation must match the surrounding file (2-space indent, inputs nested under `workflow_dispatch:`).

---

## Task 2: Thread `prerelease` through to `python-semantic-release`

**Files:**
- Modify: `.github/workflows/release.yml:46-53`

- [ ] **Step 1: Locate the `Semantic Version Release` step**

The current step looks like:

```yaml
      - name: Semantic Version Release
        id: release
        uses: python-semantic-release/python-semantic-release@v10.5.3
        with:
          github_token: ${{ secrets.RELEASE_TOKEN }}
          git_committer_name: "github-actions"
          git_committer_email: "actions@users.noreply.github.com"
          force: ${{ inputs.force }}
```

- [ ] **Step 2: Add `prerelease` and `prerelease_token` inputs**

Replace with:

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

The `prerelease_token: rc` literal produces version strings of the form `1.21.0-rc.1`, `1.21.0-rc.2`, etc. These versions trigger the GitHub Release to be marked as a pre-release automatically.

- [ ] **Step 3: Re-run YAML syntax check**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo OK
```

Expected: `OK`.

---

## Task 3: Gate the "Update versioned manifests" step on pre-release

**Files:**
- Modify: `.github/workflows/release.yml:55-56`

- [ ] **Step 1: Locate the step**

Find the step beginning:

```yaml
      - name: Update versioned manifests to released version
        if: steps.release.outputs.released == 'true'
```

(currently around line 55–56)

- [ ] **Step 2: Extend the `if:` condition**

Replace the `if:` line with:

```yaml
      - name: Update versioned manifests to released version
        if: steps.release.outputs.released == 'true' && !inputs.prerelease
```

The rest of the step body (the `env:`, `run:` block, the jq rewrites, the `git tag -f` force-move) is unchanged.

**Why:** the committed manifest bump is only consumed by `publish-registry` (server.json) and `publish-claude-plugin-pr` (plugin.json / .mcp.json). Both are skipped on pre-release (Task 4). The mcpb bundle reads its version from `${VERSION}` env var via `envsubst` at build time, so it doesn't need a committed manifest. Skipping this step keeps `main` free of `rc.N` version strings in checked-in JSON files.

- [ ] **Step 3: Verify the step's `run:` block was not touched**

Run:

```bash
git diff .github/workflows/release.yml
```

After Tasks 1, 2, and 3, the diff should contain roughly three small hunks:

1. `workflow_dispatch` inputs — one added block (~6 lines) for the new `prerelease` input.
2. `Semantic Version Release` step — two added `with:` lines (`prerelease:`, `prerelease_token:`).
3. `Update versioned manifests` step — one modified line (the `if:`).

The jq rewrites, the `env:` block, and the `git tag -f` force-move inside the step `run:` body must all be unchanged. If you see the body in the diff, revert and re-do this step surgically.

---

## Task 4: Gate downstream jobs on pre-release

**Files:**
- Modify: `.github/workflows/release.yml` — four job `if:` lines (`publish-pypi`, `publish-linux-packages`, `publish-claude-plugin-pr`, `publish-registry`)

- [ ] **Step 1: Gate `publish-pypi`**

Find (around line 114–116):

```yaml
  publish-pypi:
    needs: release
    if: needs.release.outputs.released == 'true'
```

Change the `if:` to:

```yaml
  publish-pypi:
    needs: release
    if: needs.release.outputs.released == 'true' && !inputs.prerelease
```

- [ ] **Step 2: Gate `publish-linux-packages`**

Find (around line 259–261):

```yaml
  publish-linux-packages:
    needs: release
    if: needs.release.outputs.released == 'true'
```

Change the `if:` to:

```yaml
  publish-linux-packages:
    needs: release
    if: needs.release.outputs.released == 'true' && !inputs.prerelease
```

- [ ] **Step 3: Gate `publish-claude-plugin-pr`**

Find (around line 366–368):

```yaml
  publish-claude-plugin-pr:
    needs: release
    if: needs.release.outputs.released == 'true'
```

Change the `if:` to:

```yaml
  publish-claude-plugin-pr:
    needs: release
    if: needs.release.outputs.released == 'true' && !inputs.prerelease
```

- [ ] **Step 4: Gate `publish-registry`**

Find (around line 403–405):

```yaml
  publish-registry:
    needs: [release, publish-pypi, publish-docker]
    if: needs.release.outputs.released == 'true'
```

Change the `if:` to:

```yaml
  publish-registry:
    needs: [release, publish-pypi, publish-docker]
    if: needs.release.outputs.released == 'true' && !inputs.prerelease
```

**Important:** leave `needs: [release, publish-pypi, publish-docker]` alone. On pre-release, `publish-pypi` is skipped; `publish-registry` sees a skipped-dependency and is itself skipped by the `if:` (plus the `needs` chain). Don't be tempted to remove `publish-pypi` from `needs:`.

- [ ] **Step 5: Confirm `build-mcpb` and `publish-mcpb` were NOT changed**

Neither of these jobs gets an additional gate. They run in **both** modes. Verify with two separate commands:

```bash
grep -A2 '^  build-mcpb:' .github/workflows/release.yml
grep -A2 '^  publish-mcpb:' .github/workflows/release.yml
```

Expected: both `if:` lines should still read `if: needs.release.outputs.released == 'true'` exactly (no trailing `&& !inputs.prerelease`).

- [ ] **Step 6: YAML syntax check**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo OK
```

Expected: `OK`.

---

## Task 5: Rewrite `publish-docker` tag block with `enable=` modifiers

**Files:**
- Modify: `.github/workflows/release.yml:207-216` (the `Extract metadata (tags, labels)` step)

- [ ] **Step 1: Locate the current `tags:` block**

```yaml
      - name: Extract metadata (tags, labels)
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=raw,value=latest
            type=raw,value=v${{ steps.version.outputs.version }}
            type=raw,value=v${{ steps.version.outputs.minor }}
            type=raw,value=v${{ steps.version.outputs.major }}
          labels: |
            org.opencontainers.image.title=markdown-vault-mcp
            org.opencontainers.image.description=Generic markdown vault MCP server with FTS5 + semantic search
            org.opencontainers.image.vendor=pvliesdonk
            io.modelcontextprotocol.server.name=io.github.pvliesdonk/markdown-vault-mcp
```

- [ ] **Step 2: Replace only the `tags:` block, leaving `labels:` untouched**

New `tags:` block (replace the five lines from `tags: |` through the fourth `type=raw,value=v...` line — **do not** touch `labels:`):

```yaml
          tags: |
            type=raw,value=v${{ steps.version.outputs.version }}
            type=raw,value=latest,enable=${{ !inputs.prerelease }}
            type=raw,value=v${{ steps.version.outputs.minor }},enable=${{ !inputs.prerelease }}
            type=raw,value=v${{ steps.version.outputs.major }},enable=${{ !inputs.prerelease }}
            type=raw,value=unstable,enable=${{ inputs.prerelease }}
```

Key points:
- The full versioned tag (`type=raw,value=v${{ steps.version.outputs.version }}`) is now the **first** line and has **no** `enable=` — it always publishes (as `:v1.21.0` for stable or `:v1.21.0-rc.1` for pre-release).
- `:latest`, `:v1.21`, `:v1` each get `enable=${{ !inputs.prerelease }}` — they publish on stable, skip on pre-release.
- `:unstable` gets `enable=${{ inputs.prerelease }}` — publishes on pre-release only.
- `docker/metadata-action` evaluates the `enable=` expression and, when false, omits that tag from the output entirely.

- [ ] **Step 3: YAML syntax check**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo OK
```

Expected: `OK`.

- [ ] **Step 4: Cross-check the whole diff**

Run:

```bash
git diff .github/workflows/release.yml
```

Review every hunk. Expected changes, in order top-to-bottom of the file:

1. `workflow_dispatch` inputs: `prerelease` block added (Task 1).
2. `Semantic Version Release` step: 2 new `with:` inputs (Task 2).
3. `Update versioned manifests` step: `if:` extended (Task 3).
4. `publish-pypi` job: `if:` extended (Task 4.1).
5. `publish-docker` → `Extract metadata` step: `tags:` block rewritten (Task 5.2).
6. `publish-linux-packages` job: `if:` extended (Task 4.2).
7. `publish-claude-plugin-pr` job: `if:` extended (Task 4.3).
8. `publish-registry` job: `if:` extended (Task 4.4).

Total modified hunks: **~8**. Total added lines: ~10–12. If you see any unexpected hunks (e.g. whitespace-only changes, re-ordered lines, touched `labels:`), revert them before proceeding.

---

## Task 6: Run repo-wide verification gates

**Files:**
- None modified — this task only runs checks.

These are the `CLAUDE.md` Hard PR Acceptance Gates, run locally before commit. Everything except pre-commit hooks is a no-op for this PR (no `.py` changed), but run them anyway to catch accidents.

- [ ] **Step 1: Run pytest**

```bash
uv run pytest -x -q
```

Expected: all tests pass. There should be no new test output because no Python changed.

- [ ] **Step 2: Run ruff check + format**

```bash
uv run ruff check --fix .
uv run ruff format .
uv run ruff format --check .
```

Expected: "All checks passed" / "N files already formatted". No files should be auto-modified. If any file outside `.github/workflows/release.yml` shows up as modified, something went wrong — revert it.

- [ ] **Step 3: Run mypy**

```bash
uv run mypy src/
```

Expected: "Success: no issues found".

- [ ] **Step 4: YAML syntax check (final)**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo OK
```

Expected: `OK`.

---

## Task 7: Commit the workflow changes

**Files:**
- Stage: `.github/workflows/release.yml`

- [ ] **Step 1: Stage only the workflow file**

```bash
git add .github/workflows/release.yml
git status
```

Expected: one staged file (`.github/workflows/release.yml`). No other modified or untracked files in the stage.

- [ ] **Step 2: Commit with a conventional-commit message**

```bash
git commit -m "$(cat <<'EOF'
feat(ci): add prerelease mode to release workflow

Add a `prerelease` boolean input to workflow_dispatch (default: true)
that threads through to python-semantic-release and gates PyPI, linux
packages, the Claude Code catalog PR, the MCP Registry publish, and
the versioned-manifest commit. On pre-release the Docker tags also
switch: :latest / :v1.21 / :v1 are suppressed, :unstable + :vX.Y.Z-rc.N
are pushed instead.

Semantic-release uses prerelease_token: rc so versions are formatted
as 1.21.0-rc.1. The GitHub Release is automatically marked as a
pre-release. build-mcpb and publish-mcpb run unchanged in both modes —
the mcpb bundle gets its version via envsubst from the release output
so no committed manifest bump is required.

Closes #352. Supersedes #351.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Confirm the commit**

```bash
git log -1 --stat
```

Expected: a single file changed (`.github/workflows/release.yml`), roughly 10–12 insertions and 4 deletions.

---

## Task 8: Update `docs/design.md` — add Release Channels subsection

**Files:**
- Modify: `docs/design.md` — insert new `### Release channels` subsection under `## Deployment`, after `### Write + Git Integration`

- [ ] **Step 1: Locate the insertion point**

The `## Deployment` section in `docs/design.md` currently contains two subsections (use `grep -n '^###' docs/design.md` to find exact line numbers):

- `### Docker` (~ line 1410)
- `### Write + Git Integration` (~ line 1432)

Insert a new subsection `### Release channels` **after** `### Write + Git Integration` and **before** `### Future Work` (~ line 1514).

- [ ] **Step 2: Insert the new subsection**

Use the Edit tool to add, right before the `### Future Work` line:

```markdown
### Release channels

The release workflow (`.github/workflows/release.yml`) publishes two
distinct channels via a single `workflow_dispatch` trigger:

- **Stable** (`prerelease: false`): full pipeline. semantic-release
  cuts a `vX.Y.Z` tag, PyPI receives the wheel + sdist, the Docker
  image publishes `:latest`, `:vX.Y.Z`, `:v1.21`, `:v1`, `.deb`/`.rpm`
  packages attach to the GitHub Release, the Claude Code catalog PR
  opens in `pvliesdonk/claude-plugins`, and the MCP Registry receives
  the new `server.json`. Intended for promoting a verified build to
  every distribution surface.

- **Pre-release** (`prerelease: true`, the dispatch default):
  exercises the full pipeline without touching public catalogs.
  semantic-release cuts a `vX.Y.Z-rc.N` tag and marks the GitHub
  Release as a pre-release. The Docker image publishes `:unstable`
  and `:vX.Y.Z-rc.N` only — `:latest`, `:v1.21`, `:v1` never move on
  a pre-release. The mcpb bundle is built and attached to the
  pre-release for manual smoke-test in Claude Desktop. PyPI, linux
  packages, the Claude Code catalog PR, and the MCP Registry publish
  are all skipped. This is the default dispatch mode so real releases
  require an explicit opt-out.

The `build-mcpb` job runs unchanged in both modes: it reads
`needs.release.outputs.version` (which already carries the rc suffix
on pre-release) and threads it through `envsubst '${VERSION}'` into
`packaging/mcpb/manifest.json.in` and `pyproject.toml.in`. No
committed manifest bump is needed for the bundle.

```

- [ ] **Step 3: Confirm the insertion**

```bash
grep -A2 '^### Release channels' docs/design.md | head -5
```

Expected: the heading line plus two lines from the paragraph.

---

## Task 9: Update `docs/installation.md` — mention `:unstable` Docker tag

**Files:**
- Modify: `docs/installation.md` around line 56

- [ ] **Step 1: Use the Edit tool on `docs/installation.md`**

The `old_string` to match (a single line):

```
The Docker image uses `[all]` (MCP + FastEmbed + API embeddings). Semantic search is available by default with FastEmbed and can switch to Ollama/OpenAI when configured.
```

The `new_string` to replace it with (4 additional content lines + surrounding blank line, preserving the original line at the top):

```
The Docker image uses `[all]` (MCP + FastEmbed + API embeddings). Semantic search is available by default with FastEmbed and can switch to Ollama/OpenAI when configured.

For early adopters who want to test unreleased changes, an `:unstable` tag is published by the release workflow's pre-release mode. It tracks the latest release candidate and may include in-progress features. The floating `:latest`, `:vN`, and `:vN.M` tags only move on stable releases.

~~~bash
docker pull ghcr.io/pvliesdonk/markdown-vault-mcp:unstable
~~~
```

**Critical:** replace the `~~~bash` / `~~~` fences in `new_string` with triple backticks (``` ```bash ``` / ``` ``` ```) when you invoke the Edit tool. The tildes here exist only so this plan file's own Markdown renders — the actual file must use backticks to match the rest of `docs/installation.md`.

- [ ] **Step 2: Confirm the insertion**

```bash
grep -n ':unstable' docs/installation.md
```

Expected: 2 matches — one in prose, one in the code block.

---

## Task 10: Re-run verification gates for docs changes

- [ ] **Step 1: Run pre-commit-relevant checks**

```bash
uv run pytest -x -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo OK
```

Expected: all green. Docs changes touch no code, so these are all no-ops.

- [ ] **Step 2: Build the docs locally (optional but recommended)**

```bash
uv run mkdocs build --strict 2>&1 | tail -20
```

Expected: "INFO - Documentation built". If `--strict` flags any warnings from the new content (broken links, unknown headings), fix them in `docs/design.md` or `docs/installation.md` before committing.

If `mkdocs` is not installed in the dev env, skip this step and rely on the `docs.yml` CI job to validate.

---

## Task 11: Commit the docs changes

**Files:**
- Stage: `docs/design.md`, `docs/installation.md`

- [ ] **Step 1: Stage both docs files**

```bash
git add docs/design.md docs/installation.md
git status
```

Expected: two staged files.

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: document stable and pre-release channels for the release workflow

Add a `Release channels` subsection to docs/design.md describing the
stable vs. pre-release distinction, what each dispatch mode produces,
and why the mcpb bundle needs no committed manifest bump on pre-release.

Mention the `:unstable` Docker tag in docs/installation.md so early
adopters have a documented channel for testing release-candidate
builds without tracking `:latest`.

Closes #352 (docs portion).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Confirm**

```bash
git log --oneline -3
```

Expected: three commits on the branch — the spec (from earlier), the workflow change (Task 7), and the docs change (Task 11).

---

## Task 12: Push and open the pull request

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/prerelease-mode
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(ci): add prerelease mode to release workflow" --body "$(cat <<'EOF'
## Summary

- Add a `prerelease` boolean input to `release.yml`'s `workflow_dispatch` (defaults to `true` — real releases are now an explicit opt-in).
- Thread `prerelease` through to `python-semantic-release@v10.5.3` with `prerelease_token: rc`, producing `vX.Y.Z-rc.N` tags marked as GitHub Pre-releases.
- Skip `publish-pypi`, `publish-linux-packages`, `publish-claude-plugin-pr`, `publish-registry`, and the manifest-bump step on pre-release.
- Conditional Docker tags via `docker/metadata-action`'s native `enable=<bool>` modifier: pre-release pushes `:unstable` + `:vX.Y.Z-rc.N` only; floating stable tags (`:latest`, `:v1.21`, `:v1`) never move on a pre-release.
- `build-mcpb` / `publish-mcpb` run unchanged in both modes — the mcpb bundle reads its version from `needs.release.outputs.version` via `envsubst`, so no committed manifest is needed.
- Doc updates: `docs/design.md` gains a `Release channels` subsection, `docs/installation.md` mentions the `:unstable` Docker tag.

Closes #352. Supersedes #351.

## Test plan

- [ ] Verify the GitHub Actions dispatch form renders the `prerelease` checkbox pre-checked.
- [ ] Dispatch on this branch with `prerelease: true` and confirm: `vX.Y.Z-rc.N` tag created, GitHub Pre-release created with `.mcpb` + SBOM attached, Docker image pushed as `:unstable` + `:vX.Y.Z-rc.N` only, PyPI / linux-packages / claude-plugin-pr / publish-registry jobs show as "skipped".
- [ ] Verify `:latest`, `:v1.21`, `:v1` Docker tags still point at the **previous** stable release (no movement).
- [ ] Verify `main` has no new manifest-bump commit after the pre-release run.
- [ ] Download the pre-release `.mcpb` and install in Claude Desktop as a smoke test.
- [ ] Dispatch once more with `prerelease: false` to confirm normal-release behavior is unchanged (or defer this check until the next real release is due).
EOF
)"
```

- [ ] **Step 3: Return the PR URL**

The `gh pr create` output includes a URL like `https://github.com/pvliesdonk/markdown-vault-mcp/pull/NNN`. Report this to the user.

---

## Post-merge verification (out of scope for this PR, but document the smoke test)

After merging, the project owner should:

1. Dispatch the `Release` workflow from `main` with `prerelease: true` (the default) and verify every row of the Job-by-job matrix in the spec.
2. Dispatch once more with `prerelease: false` on the first real release to confirm stable behavior is unaffected.

These dispatches cannot run from this plan (they require `secrets.RELEASE_TOKEN` and move real public artifacts). They belong in the PR's Test plan checklist.
