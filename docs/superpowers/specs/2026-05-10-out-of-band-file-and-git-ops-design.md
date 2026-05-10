# Out-of-band file ops + git sync — design

**Date:** 2026-05-10
**Issues:** #442 (read-side guards + Context-cost docstrings), #443 (`create_upload_link` adoption), #444 (`git_sync` force-trigger tool)
**Sequencing:** three independent PRs, design captured here once.

---

## 1. Theme & shared rationale

LLMs (and the agents wrapping them) keep trying to move bytes through the MCP context. That works for small text but fails silently for binaries: base64 inflates 1.33×, and even today's biggest contexts choke on a 10 MB attachment that turns into 13 MB of garbled tokens nobody can use. The vault has the right primitives in adjacent slots — `create_download_link` for outbound, `fetch` for "pull by URL" — but the surface around them isn't legible to the LLM, and the inbound mirror (a way to push bytes into the vault from a local file the LLM doesn't itself have) is missing.

Three independent PRs, one combined spec:

1. **#442** — close the silent-failure path: tighten read-side caps so context-bound binaries fail fast with an actionable error, and standardise a "Context cost" disclaimer pattern across every tool that returns large payloads.
2. **#443** — open the missing inbound channel: adopt `register_file_exchange_upload` from `fastmcp-pvl-core` v2.1.0 via the `fastmcp-server-template` v1.6.0 scaffold. `create_upload_link` mints a one-time HTTPS POST URL the local agent uses to push bytes directly into the vault, bypassing context entirely.
3. **#444** — add the missing manual-sync trigger: `git_sync` lets the LLM force pull/push/both immediately instead of waiting up to 600s for the periodic loops.

The three are independently reviewable and revertable. Bundling them was considered and rejected (one ~600+ line PR is hard to bisect; #442's cap defaults touch behavior every consumer relies on, so isolation matters).

---

## 2. PR #442 — read-side guards + Context-cost disclaimers

### Behaviour changes

| Knob | Today | New default | Override |
|---|---|---|---|
| `MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB` | 10 MB | **1 MB** | env var, 0 = unlimited |
| `MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES` | (none) | **262144** (256 KB) | new env var, 0 = unlimited |

`DocumentManager.read` and `read_attachment` enforce the new caps and raise `ValueError` with messages that name the alternative the LLM should use:

> `"Document at 'Foo/giant.md' is 412 KB, exceeds MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES (256 KB). Use read(path, section=heading) for partial reads, or raise MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES if you genuinely need the full document in context."`

> `"Attachment 'assets/x.pdf' is 5.2 MB, exceeds MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB (1 MB). Use create_download_link(path) for HTTP transfer, or raise MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB if you need the bytes in context."`

The error messages name the right alternative — not just "raise the limit" — so the LLM doesn't loop on cap-bump-and-retry.

### Disclaimer pattern

Every tool whose return value can be large gets a uniform `**Context cost:**` paragraph in its docstring. Initial targets:

- `read` — "Use `create_download_link` for transfer; bytes through context are bounded by `MAX_ATTACHMENT_SIZE_MB` and `MAX_NOTE_READ_BYTES`."
- `write` (`content_base64` parameter) — "Use `create_upload_link` for inbound binaries once #443 lands; `content_base64` is intended only for tiny payloads (<100 KB)."
- `fetch` — reinforce the existing "URL transfer keeps bytes out of context" message.

#443's new `create_upload_link` will adopt the same pattern when it lands. Section 5 covers codifying the convention in CLAUDE.md as a follow-up.

### Files touched

`src/markdown_vault_mcp/config.py` (new env var), `src/markdown_vault_mcp/managers/document.py` (cap enforcement in `read` / `read_attachment`), `src/markdown_vault_mcp/_server_tools.py` (docstring disclaimers), `README.md` (env vars + new defaults + upgrade note), `docs/configuration.md` (env vars), `docs/tools/index.md` (per-tool disclaimers), `examples/*.env` (default values).

### Migration note

The cap reduction (10 MB → 1 MB) is a soft-breaking change for any deployment relying on the previous default. README upgrade section explains the new defaults and points at the env-var override. Operators with explicit non-LLM consumers (scripts, CI) raise via `MAX_ATTACHMENT_SIZE_MB` — the existing knob still works, just with a tighter default.

---

## 3. PR #443 — adopt template v1.6.0 file-exchange-upload scaffold

### Prereq — copier update v1.5.1 → v1.6.0

Brings in:

- `DOMAIN-FILE-EXCHANGE-START` / `END` sentinel block in `server.py` wrapping the existing `register_file_exchange(...)` call.
- Fully-commented `register_file_exchange_upload(...)` scaffold inside the same sentinel, with stub `_upload_receiver` and `_validate_upload_target`.
- `fastmcp-pvl-core>=2.1.0,<3` pin in `pyproject.toml`.
- 4 new env vars documented in `docs/configuration.md`.
- "Uploading files (`receiver=`)" section in `docs/guides/file-exchange.md`.
- `## File Exchange` section in `CLAUDE.md`.

The copier-update is **behaviourally inert** by itself — the upload scaffold ships commented; no tools are registered. It is therefore safely landable as a separate PR before #443's content commits, which keeps the diffs reviewable on their own. Two-PR split chosen over one-PR-with-two-commits for review clarity.

### MV-specific work (after the copier update)

#### Wiring (uncomment the scaffold)

Mechanical: remove the `#` prefix on the `register_file_exchange_upload(...)` call inside the sentinel.

#### Receiver + validator

New module `src/markdown_vault_mcp/uploads.py`:

```python
def _vault_upload_receiver(record: UploadRecord, body: bytes) -> dict[str, Any]:
    """Commit uploaded bytes to the vault.

    Dispatches to Collection.write for .md paths or
    Collection.write_attachment for binaries based on the target_id's
    extension.  Path validation already ran at link creation via
    _validate_upload_target.
    """
    collection = get_collection_singleton()
    if record.target_id.endswith(".md"):
        collection.write(record.target_id, content=body.decode("utf-8"))
    else:
        collection.write_attachment(record.target_id, body)
    return {"path": record.target_id, "size_bytes": len(body)}


def _validate_upload_target(target_id: str) -> None:
    """Runs at link-creation via pvl-core's pre_link_validator=.
    Raises ValueError → in-band tool error per pvl-core v0.4 spec contract."""
    collection = get_collection_singleton()
    collection._validate_path(target_id)         # path traversal + relative-path guard
    if not target_id.endswith(".md"):
        collection._check_attachment_extension(target_id)  # extension allowlist
```

The `pre_link_validator=` raises `ValueError` for invalid input; pvl-core surfaces the failure as an in-band tool error before the link is minted. Bad paths fail in the same call that asked for the link, not after a wasted HTTP POST.

#### Receiver flavour

Buffered (`receiver=`), not streaming (`stream_receiver=`). `Collection.write` and `write_attachment` take `bytes`; the size cap (default 10 MB, configurable via `MARKDOWN_VAULT_MCP_FILE_EXCHANGE_UPLOAD_MAX_BYTES`) bounds the buffer. Streaming variant is available later if a multi-GB use case appears.

### Behaviour (inherited from upstream pvl-core v2.1.0 / spec v0.4)

- One-time UUID4 tokens. Default 5-minute TTL.
- Token consumed at the lookup step (anti-replay) — any 4xx response burns the link, client re-mints to retry.
- POST route at `/<namespace>/uploads/{token}`.
- HTTP status contract per spec Amendment 11: 200 / 400 (validator) / 404 (missing or already-consumed) / 409 (no-overwrite, if configured) / 410 (expired) / 413 (oversize) / 415 (MIME mismatch) / 500 (receiver bug).
- `accepts=` MIME filter at link-creation time.

### Files touched (post-copier-update)

`src/markdown_vault_mcp/server.py` (uncomment scaffold, wire real callables), new `src/markdown_vault_mcp/uploads.py` (receiver + validator), `src/markdown_vault_mcp/_server_deps.py` (extend with `get_collection_singleton()`; see Section 5), `README.md` (tool table row), `docs/tools/index.md` (full tool entry), `docs/guides/claude-desktop.md` (worked example with `curl`), `tests/test_uploads.py`.

### Tests

MV-side concerns only:

- Receiver dispatches by extension (parametrise `.md` vs `.pdf`).
- Validator rejects path traversal at link-creation (`../etc/passwd`).
- Validator rejects disallowed extensions (`.exe` against the default allowlist).
- End-to-end: `create_upload_link` → `httpx.AsyncClient.post(url, content=bytes)` → vault file appears → `read(path)` returns it.

The pvl-core helper's own behaviour (token lifecycle, status codes, size enforcement, MIME filter) is tested upstream — MV does not re-test it.

### Migration story

None. MV depends on the upstream helper from day one. No local POC, no migration tracker. The pattern matches #431 in spirit (downstream consumer of an upstream helper) but skips the temporary divergence #431 is paying off today.

---

## 4. PR #444 — `git_sync` force-trigger tool

### Tool signature

```python
@mcp.tool(tags={"write", "git-managed"})
async def git_sync(
    direction: Literal["pull", "push", "both"] = "both",
    dry_run: bool = False,
    collection: Collection = Depends(get_collection),
) -> dict[str, Any]:
    """Force an immediate git pull / push / both, bypassing the periodic loops.

    Today the only sync triggers are time-based (GIT_PULL_INTERVAL_S=600,
    GIT_PUSH_DELAY_S=30).  This tool runs the same operations synchronously
    and returns structured state, so an LLM can confirm a multi-write
    workflow has been pushed before telling the user to check another device.

    Context cost: small — returns a structured dict with SHAs, conflict paths
    if any, and a per-direction status.  No file bytes ever returned.

    Args:
        direction: Which leg(s) to run.  "both" runs pull then push.
        dry_run: When true, runs `git fetch` + diff vs origin to report what
            would happen without applying.  Skips push side entirely (no
            `--dry-run` for push because remote rejection only surfaces
            after the actual attempt).

    Returns:
        Structured dict; see schema below.
    """
```

### Visibility — hidden in non-managed modes

A second visibility axis on top of the existing `READ_ONLY` toggle: managed-git mode. Reuses the same `mcp.disable(tags=...)` mechanism — tool tagged with both `write` and `git-managed`; in `server.py` after all registrations, run a second disable pass when the resolved git mode isn't managed:

```python
git_strategy = config.to_collection_kwargs().get("git_strategy")
if git_strategy is None or not git_strategy.managed:
    mcp.disable(tags={"git-managed"})
```

The existing read-only disable composes naturally — a tool tagged with both `write` and `git-managed` is hidden if either condition fires (set-union of disabled tags). No new visibility framework, just one extra tag and a four-line check.

### Result schema

```python
# direction="both", success
{
    "direction": "both",
    "head_sha": "abc1234",
    "branch": "main",
    "pull": {
        "applied": True,
        "fast_forward": True,
        "commits_pulled": 3,
        "from_sha": "9999999",
        "to_sha": "abc1234",
    },
    "push": {
        "applied": True,
        "commits_pushed": 5,
        "remote_sha_before": "8888888",
        "remote_sha_after": "abc1234",
    },
}

# direction="pull", conflict
{
    "direction": "pull",
    "head_sha": "abc1234",  # unchanged from before
    "branch": "main",
    "pull": {
        "applied": False,
        "reason": "non_fast_forward_with_conflicts",
        "conflict_files": ["Notes/2026-05-09.md", "Inbox/draft.md"],
        "remote_sha": "9999999",
        "local_sha": "abc1234",
    },
    "push": null,  # not attempted when pull failed
}

# direction="push", remote rejected
{
    "direction": "push",
    "head_sha": "abc1234",
    "branch": "main",
    "pull": null,
    "push": {
        "applied": False,
        "reason": "non_fast_forward",
        "remote_sha": "9999999",
        "local_sha": "abc1234",
        "hint": "Run git_sync(direction='pull') first to integrate remote commits.",
    },
}

# dry_run
{
    "direction": "both",
    "dry_run": True,
    "head_sha": "abc1234",
    "branch": "main",
    "pull": {
        "would_apply": True,
        "commits_pulled": 3,
        "from_sha": "9999999",
        "to_sha": "abc1234-after-fetch",
    },
    "push": null,  # skipped in dry-run
}
```

The `hint` field is the same pattern as #442's error messages — give the LLM the next step in-band so it doesn't guess.

### Behaviour

- "both" runs pull first, then push if pull succeeded. Pull failure short-circuits push.
- Pull conflict handling reuses the Syncthing-style conflict-file machinery from PR #232 — conflicting files get `.conflict-<sha>.md` siblings; the tool returns their paths in `conflict_files` so the LLM can read them and propose resolutions.
- Push rejection (non-fast-forward) does not attempt force-push — fail-loud with the `hint` field.
- The tool acquires `_write_lock` for the duration so concurrent `write` / `edit` / `delete` calls don't race the sync.
- When the periodic pull/push loop is mid-flight, `git_sync` blocks briefly for it to finish (existing lock), then runs.
- Detached HEAD or no remote: `ValueError` with a clear message — the tool wouldn't have been registered if the strategy were non-managed, but a remote disappearing at runtime is still possible.

### Internals on `GitWriteStrategy`

```python
class GitWriteStrategy:
    # existing methods ...

    def force_pull(self, *, dry_run: bool = False) -> PullResult: ...
    def force_push(self, *, dry_run: bool = False) -> PushResult: ...
    # composed sync(direction) lives in the server tool, not here
```

The strategy already does pull+push internally on its periodic schedule; this exposes them as direct calls returning `PullResult` / `PushResult` dataclasses that the server-tool layer serialises to the dict shapes above.

### Files touched

`src/markdown_vault_mcp/git.py` (new `force_pull` / `force_push` methods + result dataclasses), `src/markdown_vault_mcp/_server_tools.py` (new tool registration), `src/markdown_vault_mcp/server.py` (managed-mode disable pass), `README.md`, `docs/configuration.md`, `docs/tools/index.md`, `docs/guides/git-integration.md`, `tests/test_git_sync.py`, `tests/conftest.py` or `tests/fixtures/git.py` (new bare-repo fixture — see Section 5).

### Tests

Two ephemeral repos in fixture (a bare "remote" + a "local" clone) so tests verify real git state instead of mocking. Cases:

- Clean both-direction (idempotent: second call returns 0 commits in either direction).
- Pull conflict (writes `.conflict-<sha>.md`; tool returns the list).
- Push rejection (returns `hint`).
- Dry-run pull (returns prediction without changing HEAD).
- `direction="pull"` skips push entirely.
- Tool absent when `git_repo_url` unset (visibility test via `client.list_tools()`).

### Out of scope for this PR

- A `git_status` companion tool for inspection-only ("what's local vs remote without pulling?"). Defer until a use case appears; for now the dry-run mode covers most of it.
- Force-push with explicit user opt-in (CLAUDE.md: "Never run destructive git commands ... unless explicitly requested").
- Integration with #232's conflict-file viewer — separate UX layer; this tool just surfaces file paths.

---

## 5. Cross-cutting concerns

### Sequencing across the PRs

```
1. PR #442  — context-bloat docstrings + read-side caps
   ↓ (independent of the others)

2. PR (copier-update)  — v1.5.1 → v1.6.0 (separate, behaviourally inert)
   ↓ (required by #443; can land in parallel with #442)

3. PR #443  — uncomment file-exchange-upload scaffold + supply receiver/validator
   ↓ (independent of #444)

4. PR #444  — git_sync force-trigger tool
   (independent of #443; could land any time after #442's disclaimer pattern is established)
```

Wall-clock optimum: #442 + copier-update in parallel, then #443 and #444 in parallel after both prereqs land. All four PRs reviewable independently; bisect-friendly.

### Disclaimer pattern as a project convention

The `**Context cost:**` paragraph #442 introduces is the seed of a project-wide convention for every future tool that returns large data. Codify in `CLAUDE.md` once #442 lands so future PRs don't reinvent the wording. One-line addition under "Logging Standard" or a new "Tool Docstrings" subsection. Out of scope for #442 itself — it's a discipline note that follows from the pattern hardening.

### `get_collection_singleton()` access pattern

Both #443's receiver and #444's tool need a way to reach the live `Collection` from outside the FastMCP `Depends(get_collection)` injection — the upload receiver runs from the HTTP route handler (no FastMCP context), and `git_sync` runs in the tool body but needs a stable reference outside the per-request injection.

MV today already has this for `artifacts.py`'s `set_artifact_store` / `get_artifact_store` — same pattern (module-level singleton set in lifespan, read in handler). Extend `_server_deps.py` with `get_collection_singleton()` rather than create a new module — the file already owns the lifespan factory and the existing `get_collection` Depends function. No new file needed.

### Test infrastructure

- #442 tests are pure unit (size assertions on canned files) — no new infra.
- #443 tests need an HTTP client to actually POST against the running server — `httpx.AsyncClient` against `mcp.http_app()` lifespan, same pattern as existing `test_artifacts.py`.
- #444 tests need a real git remote (bare repo) + local clone — new fixture in `tests/conftest.py` or `tests/fixtures/git.py`. Reusable for any future git-tool tests.

### Documentation impact

| Doc | #442 | #443 | #444 |
|---|---|---|---|
| `README.md` | env vars + new defaults | new tool row | new tool row |
| `docs/configuration.md` | new + tightened env vars | (template-shipped section) | — |
| `docs/tools/index.md` | per-tool "Context cost" caveats | new `create_upload_link` entry | new `git_sync` entry |
| `docs/guides/file-exchange.md` | — | (template-shipped) — only MV-specific bits | — |
| `docs/guides/claude-desktop.md` | — | local-agent upload flow example | — |
| `docs/guides/git-integration.md` | — | — | manual-sync flow example |
| `examples/*.env` | new env var defaults | — | — |
| `CLAUDE.md` | "Tool Docstrings" subsection codifying the disclaimer pattern | (template-shipped File Exchange block) | — |

### Out of scope across all three PRs

- Migrating `create_download_link` to upstream (#431 — separate, paid off in its own PR cycle).
- `register_app_tool` adoption (pvl-core#63 + template#116 still pending upstream).
- Resumable / multi-part uploads (pvl-core deferred to v0.5+).
- `exchange://` reverse for co-deployed-server pushes (pvl-core deferred).
- Force-push, force-reset, or any destructive git op in #444.
- A `git_status` inspection tool (defer until needed).

### Risk register

| Risk | Mitigation |
|---|---|
| #442's cap reduction (10→1 MB) breaks downstream consumers relying on default | Loud env-var override (`MAX_ATTACHMENT_SIZE_MB`); README upgrade note; error message names the override |
| #443's receiver dispatching `.md` vs binary by extension misclassifies edge cases (e.g. `.markdown` extension) | Validator at link-creation rejects unknown extensions; existing attachment-allowlist already handles this — no new failure mode |
| Copier-update v1.5.1→v1.6.0 introduces conflicts in MV's existing customizations | Same playbook as #439 — local circus runs both reviewers on the cumulative diff before push; conflicts handled per copier's `--conflict=inline` |
| #444 races with periodic pull/push loop | Existing `_write_lock` already serialises; `git_sync` acquires same lock |
| pvl-core 2.1.0 introduces a new behaviour MV's existing wiring conflicts with | Tested at copier-update PR before #443 lands; if anything breaks, the copier-update PR is the right place to surface it |

---

## 6. References

- **MV issues:** #442, #443, #444
- **Upstream (closed/shipped):** [pvl-core#64](https://github.com/pvliesdonk/fastmcp-pvl-core/issues/64), [template#117](https://github.com/pvliesdonk/fastmcp-server-template/issues/117)
- **Upstream (still open, independent):** [pvl-core#63](https://github.com/pvliesdonk/fastmcp-pvl-core/issues/63), [template#116](https://github.com/pvliesdonk/fastmcp-server-template/issues/116)
- **Related MV trackers:** #431 (download-link upstream migration), #440 (graph-neighborhood perf), #441 (Dep Audit CVE)
- **Pvl-core release:** v2.1.0 (2026-05-10) — `register_file_exchange_upload`
- **Template release:** v1.6.0 (2026-05-10) — `DOMAIN-FILE-EXCHANGE` sentinel + upload scaffold
- **Spec amendments:** File Exchange spec v0.4 — Amendment 10 (`transfer_methods.http` direction tagging), Amendment 11 (inbound HTTP transfer)
