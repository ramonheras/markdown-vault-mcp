# PR #443 — adopt `register_file_exchange_upload` (file-exchange upload scaffold)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `fastmcp-pvl-core` v2.1.0's `register_file_exchange_upload` into MV via the v1.6.0 template scaffold — gives a local coding agent a one-time HTTPS POST URL (`create_upload_link`) to push files into the vault without round-tripping through MCP context.

**Architecture:** Adopt the upstream helper directly (no local POC). MV supplies a `_vault_upload_receiver` that dispatches by extension to `Collection.write` / `write_attachment`, plus a `_validate_upload_target` that runs at link-creation via `pre_link_validator=` so bad paths fail in-band. The template-shipped `DOMAIN-FILE-EXCHANGE` sentinel block in `server.py` already contains the commented scaffold; this PR uncomments it and supplies the real callables.

**Tech Stack:** `fastmcp-pvl-core>=2.1.0,<3` (transitively bumped by template v1.6.0), existing `Collection` write APIs, `httpx.AsyncClient` for end-to-end testing.

**Spec:** `docs/superpowers/specs/2026-05-10-out-of-band-file-and-git-ops-design.md` § 3.

**Prerequisite:** the copier update v1.5.1 → v1.6.0 must land first (Task 0). It is behaviourally inert (scaffold ships commented).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| (`copier update` — Task 0) | Prereq: brings in `DOMAIN-FILE-EXCHANGE` sentinel + commented scaffold + pvl-core>=2.1.0 pin + new env-var docs | Separate PR |
| `src/markdown_vault_mcp/uploads.py` | NEW: `_vault_upload_receiver` (commit bytes via Collection) + `_validate_upload_target` (path/extension validator) | Create |
| `src/markdown_vault_mcp/_server_deps.py` | Add `get_collection_singleton()` for use outside FastMCP DI (HTTP route handler runs there) | Modify |
| `src/markdown_vault_mcp/server.py` | Uncomment `register_file_exchange_upload(...)` in the `DOMAIN-FILE-EXCHANGE` sentinel; supply callables | Modify |
| `tests/test_uploads.py` | Receiver dispatch (.md vs binary), validator rejects path traversal + bad extension, end-to-end via httpx POST | Create |
| `README.md` | Add `create_upload_link` row to MCP Tools table | Modify |
| `docs/tools/index.md` | Add full `create_upload_link` tool entry | Modify |
| `docs/guides/claude-desktop.md` | Add local-agent upload flow as worked example with `curl` | Modify |

---

## Task 0 (PREREQ): Copier update v1.5.1 → v1.6.0

**Note:** this is a separate PR landed before the rest of this plan starts. Same playbook as #439 (the v1.5.1 update). Listed here for traceability — execute via the babysit + local-circus workflow per CLAUDE.md, not via the TDD steps below.

- [ ] Branch from main, run `uv run --quiet copier update --conflict=inline --defaults --vcs-ref=v1.6.0 --trust`
- [ ] Reconcile any `<<<<<<<` markers (expect mainly in `pyproject.toml` for the pvl-core pin bump and `server.py` for the new sentinel block; the scaffold itself is commented so no behavioural conflicts)
- [ ] `uv sync --all-extras --all-groups` (picks up `fastmcp-pvl-core==2.1.0`)
- [ ] Run all gates (`pytest -x -q`, `ruff`, `mypy`, `diff-cover`)
- [ ] Local circus (both reviewers per CLAUDE.md)
- [ ] Open as draft, babysit, merge

**Verification before starting Task 1:**

```bash
grep -n "DOMAIN-FILE-EXCHANGE-START" src/markdown_vault_mcp/server.py
# Expected: one line with the start sentinel
grep -n "DOMAIN-FILE-EXCHANGE-END" src/markdown_vault_mcp/server.py
# Expected: one line with the end sentinel
grep -n "register_file_exchange_upload" src/markdown_vault_mcp/server.py
# Expected: one or more lines, each prefixed with `#` (commented-out scaffold)
grep "fastmcp-pvl-core" pyproject.toml
# Expected: "fastmcp-pvl-core>=2.1.0,<3"
```

If any of those verifications fail, do not proceed with this plan — the copier update wasn't applied as expected.

---

## Task 1: Add `get_collection_singleton()` to `_server_deps.py`

The HTTP POST route handler (registered by pvl-core) runs outside FastMCP's `Depends(get_collection)` injection. We need a module-level singleton accessor — same pattern `artifacts.py`'s `set_artifact_store` / `get_artifact_store` already use.

**Files:**
- Modify: `src/markdown_vault_mcp/_server_deps.py`
- Test: `tests/test_server_deps.py` (or wherever `_server_deps` is tested — check via `git grep -l "_server_deps" tests/`)

- [ ] **Step 1: Write the failing test**

```python
class TestCollectionSingleton:
    """Module-level Collection accessor for handlers outside FastMCP DI."""

    def test_get_raises_when_unset(self) -> None:
        from markdown_vault_mcp._server_deps import (
            get_collection_singleton,
            set_collection_singleton,
        )
        set_collection_singleton(None)
        with pytest.raises(RuntimeError, match="Collection not initialised"):
            get_collection_singleton()

    def test_set_then_get_roundtrips(self, tmp_path: Path) -> None:
        from markdown_vault_mcp._server_deps import (
            get_collection_singleton,
            set_collection_singleton,
        )
        from markdown_vault_mcp.collection import Collection

        col = Collection(source_dir=tmp_path)
        set_collection_singleton(col)
        try:
            assert get_collection_singleton() is col
        finally:
            set_collection_singleton(None)  # cleanup
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server_deps.py::TestCollectionSingleton -v`
Expected: FAIL — `ImportError` on `get_collection_singleton`.

- [ ] **Step 3: Add the singleton accessors**

In `src/markdown_vault_mcp/_server_deps.py`, add at module level (after existing imports, before the `lifespan` factory):

```python
# Module-level Collection singleton — set in lifespan, read by HTTP
# handlers (file-exchange upload route) and other code paths that run
# outside FastMCP's per-request `Depends(get_collection)` injection.
# Same pattern as `artifacts.py`'s `set_artifact_store` / `get_artifact_store`.
_collection_singleton: Collection | None = None


def set_collection_singleton(collection: Collection | None) -> None:
    """Set or clear the process-wide Collection singleton.

    Called from the lifespan factory after Collection construction; called
    again with ``None`` on shutdown.  Idempotent.
    """
    global _collection_singleton
    _collection_singleton = collection


def get_collection_singleton() -> Collection:
    """Return the process-wide Collection.

    Raises:
        RuntimeError: If the singleton hasn't been set (server not in
            lifespan, or test forgot to set it).
    """
    if _collection_singleton is None:
        raise RuntimeError(
            "Collection not initialised — set_collection_singleton was "
            "never called.  In normal operation the lifespan factory sets "
            "it; in tests, set explicitly via set_collection_singleton(col)."
        )
    return _collection_singleton
```

- [ ] **Step 4: Wire the lifespan factory to set/clear the singleton**

In `src/markdown_vault_mcp/_server_deps.py`, find `make_collection_lifespan` (or whichever function builds the FastMCP lifespan). Inside its async-context-manager body, add `set_collection_singleton(collection)` after the `Collection(...)` construction and `set_collection_singleton(None)` in the cleanup path (typically a `finally:` after the `yield`).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_server_deps.py::TestCollectionSingleton -v`
Expected: 2 passed.

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `uv run pytest -x -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/markdown_vault_mcp/_server_deps.py tests/test_server_deps.py
git commit -m "feat(server): add Collection singleton accessor for non-DI callers

The pvl-core file-exchange upload route handler runs outside FastMCP's
Depends(get_collection) injection.  Add set_collection_singleton /
get_collection_singleton (same pattern as artifacts.py) so the upload
receiver and any future HTTP-route handler can reach the live Collection
without re-implementing the singleton plumbing.

Refs #443"
```

---

## Task 2: Write `_vault_upload_receiver` in `uploads.py`

**Files:**
- Create: `src/markdown_vault_mcp/uploads.py`
- Test: `tests/test_uploads.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_uploads.py`:

```python
"""Tests for the MV-side file-exchange upload receiver and validator."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class TestVaultUploadReceiver:
    """_vault_upload_receiver dispatches by extension to write or write_attachment."""

    def _make_record(self, target_id: str) -> object:
        from fastmcp_pvl_core import UploadRecord

        # Construct a minimal UploadRecord — exact fields per pvl-core 2.1.0's spec.
        # (If UploadRecord's constructor differs from the assumed shape,
        # adjust here; the spec ships it as a frozen dataclass.)
        return UploadRecord(
            token="test-token",
            target_id=target_id,
            content_type="application/octet-stream",
            size_bytes=0,
            extra={},
        )

    def test_md_path_dispatches_to_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from markdown_vault_mcp import _server_deps, uploads
        from markdown_vault_mcp.collection import Collection

        col = Collection(source_dir=tmp_path)
        col.build_index()
        _server_deps.set_collection_singleton(col)

        try:
            record = self._make_record("note.md")
            result = uploads._vault_upload_receiver(record, b"# Note\n\nbody\n")
            assert result == {"path": "note.md", "size_bytes": 13}
            assert (tmp_path / "note.md").read_text() == "# Note\n\nbody\n"
        finally:
            _server_deps.set_collection_singleton(None)

    def test_binary_path_dispatches_to_write_attachment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from markdown_vault_mcp import _server_deps, uploads
        from markdown_vault_mcp.collection import Collection

        col = Collection(
            source_dir=tmp_path,
            attachment_extensions=["pdf"],
        )
        col.build_index()
        _server_deps.set_collection_singleton(col)

        try:
            record = self._make_record("doc.pdf")
            payload = b"%PDF-1.4\n%fake-pdf-content"
            result = uploads._vault_upload_receiver(record, payload)
            assert result == {"path": "doc.pdf", "size_bytes": len(payload)}
            assert (tmp_path / "doc.pdf").read_bytes() == payload
        finally:
            _server_deps.set_collection_singleton(None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_uploads.py::TestVaultUploadReceiver -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'markdown_vault_mcp.uploads'`.

- [ ] **Step 3: Create `src/markdown_vault_mcp/uploads.py`**

```python
"""MV-side wiring for fastmcp-pvl-core's file-exchange upload helper.

Provides the `receiver` and `pre_link_validator` callables passed to
`register_file_exchange_upload(...)` in `server.py`.  The receiver
commits uploaded bytes to the vault via the existing Collection write
APIs; the validator runs at link-creation time so bad paths fail in-band
rather than after a wasted HTTP POST.

See pvliesdonk/fastmcp-pvl-core#64 for the upstream helper API and
spec amendments 10 + 11 for the wire contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from markdown_vault_mcp._server_deps import get_collection_singleton

if TYPE_CHECKING:
    from fastmcp_pvl_core import UploadRecord


def _vault_upload_receiver(record: UploadRecord, body: bytes) -> dict[str, Any]:
    """Commit uploaded bytes to the vault.

    Dispatches to ``Collection.write`` for ``.md`` paths or
    ``Collection.write_attachment`` for binaries based on the
    ``target_id``'s extension.  Path validation already ran at link
    creation via :func:`_validate_upload_target`, so this function trusts
    the path.

    Args:
        record: pvl-core's UploadRecord — ``target_id`` is the vault-relative
            path the agent passed to ``create_upload_link``.
        body: raw bytes streamed from the POST request, already validated
            against the size cap.

    Returns:
        Dict serialised as the HTTP 200 response body.  Conventional keys:
        ``path``, ``size_bytes``.
    """
    collection = get_collection_singleton()
    if record.target_id.endswith(".md"):
        collection.write(record.target_id, content=body.decode("utf-8"))
    else:
        collection.write_attachment(record.target_id, body)
    return {"path": record.target_id, "size_bytes": len(body)}
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_uploads.py::TestVaultUploadReceiver -v`
Expected: 2 passed.

(If `UploadRecord`'s actual constructor signature differs, the test's `_make_record` helper needs adjustment — fix the test, not the receiver.)

- [ ] **Step 5: Commit**

```bash
git add src/markdown_vault_mcp/uploads.py tests/test_uploads.py
git commit -m "feat(uploads): _vault_upload_receiver dispatches by extension

Receiver for register_file_exchange_upload — .md paths go through
Collection.write (with utf-8 decode), other extensions through
write_attachment.  Reaches the live Collection via get_collection_singleton
since the HTTP route handler runs outside FastMCP DI.

Refs #443"
```

---

## Task 3: Write `_validate_upload_target` in `uploads.py`

**Files:**
- Modify: `src/markdown_vault_mcp/uploads.py`
- Modify: `tests/test_uploads.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_uploads.py`:

```python
class TestValidateUploadTarget:
    """_validate_upload_target rejects bad paths at link-creation time."""

    def test_path_traversal_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from markdown_vault_mcp import _server_deps, uploads
        from markdown_vault_mcp.collection import Collection

        col = Collection(source_dir=tmp_path)
        col.build_index()
        _server_deps.set_collection_singleton(col)

        try:
            with pytest.raises(ValueError):
                uploads._validate_upload_target("../etc/passwd")
        finally:
            _server_deps.set_collection_singleton(None)

    def test_disallowed_extension_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from markdown_vault_mcp import _server_deps, uploads
        from markdown_vault_mcp.collection import Collection

        col = Collection(
            source_dir=tmp_path,
            attachment_extensions=["pdf"],
        )
        col.build_index()
        _server_deps.set_collection_singleton(col)

        try:
            with pytest.raises(ValueError):
                uploads._validate_upload_target("malware.exe")
        finally:
            _server_deps.set_collection_singleton(None)

    def test_md_path_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from markdown_vault_mcp import _server_deps, uploads
        from markdown_vault_mcp.collection import Collection

        col = Collection(source_dir=tmp_path)
        col.build_index()
        _server_deps.set_collection_singleton(col)

        try:
            uploads._validate_upload_target("notes/note.md")  # no exception
        finally:
            _server_deps.set_collection_singleton(None)

    def test_allowed_attachment_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from markdown_vault_mcp import _server_deps, uploads
        from markdown_vault_mcp.collection import Collection

        col = Collection(
            source_dir=tmp_path,
            attachment_extensions=["pdf"],
        )
        col.build_index()
        _server_deps.set_collection_singleton(col)

        try:
            uploads._validate_upload_target("docs/file.pdf")  # no exception
        finally:
            _server_deps.set_collection_singleton(None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_uploads.py::TestValidateUploadTarget -v`
Expected: FAIL — `_validate_upload_target` doesn't exist yet.

- [ ] **Step 3: Add `_validate_upload_target`**

Append to `src/markdown_vault_mcp/uploads.py`:

```python
def _validate_upload_target(target_id: str) -> None:
    """Validate the vault path before pvl-core mints a token.

    Runs at link-creation time via the helper's ``pre_link_validator=``
    parameter.  Raises ``ValueError`` for invalid input so pvl-core
    surfaces the failure as an in-band ``create_upload_link`` tool error,
    before the link is minted — the agent gets the rejection in the same
    call that asked for the link, not after a wasted HTTP POST.

    Validation:
    - Path traversal / escape from ``source_dir`` (delegated to
      ``Collection._validate_path``).
    - Attachment extension must be in the configured allowlist (delegated
      to ``Collection._check_attachment_extension``).  ``.md`` paths skip
      this check.

    Args:
        target_id: vault-relative path the agent passed to
            ``create_upload_link``.

    Raises:
        ValueError: invalid path or disallowed extension.
    """
    collection = get_collection_singleton()
    # pylint: disable=protected-access  # No public API; MCP layer is a
    # trusted consumer of Collection internals (same pattern as #443
    # receiver above and #439's existing artifact route).
    collection._validate_path(target_id)
    if not target_id.endswith(".md"):
        collection._check_attachment_extension(target_id)
```

**Note:** if `_check_attachment_extension` doesn't exist on `Collection` (check via `git grep -n "_check_attachment_extension\|attachment_extensions" src/markdown_vault_mcp/collection.py src/markdown_vault_mcp/managers/document.py`), use whichever method or attribute is the actual extension-allowlist entry point. The pattern is "look up how `write_attachment` validates its path's extension at write-time and reuse that".

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_uploads.py::TestValidateUploadTarget -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/markdown_vault_mcp/uploads.py tests/test_uploads.py
git commit -m "feat(uploads): _validate_upload_target rejects bad paths in-band

Runs as pvl-core's pre_link_validator= so path-traversal attempts and
disallowed extensions raise ValueError at create_upload_link call time,
not after a wasted HTTP POST.  Delegates to Collection._validate_path
and the existing attachment-extension allowlist.

Refs #443"
```

---

## Task 4: Uncomment the scaffold + wire callables in `server.py`

**Files:**
- Modify: `src/markdown_vault_mcp/server.py` (inside the `DOMAIN-FILE-EXCHANGE-START` / `END` sentinel block)

- [ ] **Step 1: Locate the sentinel block**

Run: `grep -n "DOMAIN-FILE-EXCHANGE" src/markdown_vault_mcp/server.py`. Expected output: two lines (start + end). Read those lines plus everything between (typically 30-60 lines of commented scaffold).

- [ ] **Step 2: Plan the edit**

The template ships:
- `register_file_exchange(...)` (already uncommented from #439's adoption)
- `register_file_exchange_upload(...)` (commented stub with placeholder `_upload_receiver` and `_validate_upload_target` — these are stubs we replace with imports of MV's real ones)

The edit:
1. Add `from markdown_vault_mcp.uploads import _vault_upload_receiver, _validate_upload_target` at the top of the file (or reuse an existing import block).
2. Inside the sentinel, uncomment the `register_file_exchange_upload(...)` call.
3. In the uncommented call's `receiver=` argument, replace the template's stub with `receiver=_vault_upload_receiver`.
4. In the `pre_link_validator=` argument, replace the stub with `pre_link_validator=_validate_upload_target`.
5. Delete the template's stub `_upload_receiver` and `_validate_upload_target` definitions if they were inlined (template ships them as commented stubs in the same block).

- [ ] **Step 3: Apply the edit**

Use `Edit` to:
- Add the import.
- Within the sentinel block, transform the commented `register_file_exchange_upload(...)` call into an uncommented call with `receiver=_vault_upload_receiver, pre_link_validator=_validate_upload_target` arguments. Preserve any other kwargs the template ships (e.g. `namespace=`, `env_prefix=`).

(Exact diff depends on what the template ships — read the block first, then edit.)

- [ ] **Step 4: Verify no comment-only lines remain in the call**

Run: `grep -A 20 "register_file_exchange_upload(" src/markdown_vault_mcp/server.py | head -25`
Visually confirm: no `#` prefixes inside the call's argument list.

- [ ] **Step 5: Smoke-test the server constructs without error**

Run:
```bash
uv run python -c "
import os
os.environ['MARKDOWN_VAULT_MCP_SOURCE_DIR'] = '/tmp/empty-vault'
os.makedirs('/tmp/empty-vault', exist_ok=True)
from markdown_vault_mcp.server import make_server
server = make_server(transport='http')
print('server constructed OK')
"
```
Expected: prints `server constructed OK` and exits 0. If `make_server` raises, the wiring is wrong — re-check the edit.

- [ ] **Step 6: Commit**

```bash
git add src/markdown_vault_mcp/server.py
git commit -m "feat(server): wire register_file_exchange_upload with MV receiver

Uncomments the v1.6.0 template scaffold's register_file_exchange_upload
call; supplies _vault_upload_receiver (commits via Collection) and
_validate_upload_target (path/extension check at link creation).

Refs #443"
```

---

## Task 5: End-to-end test — `create_upload_link` → POST → file in vault

**Files:**
- Modify: `tests/test_uploads.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_uploads.py`:

```python
class TestUploadEndToEnd:
    """Mint link via create_upload_link, POST bytes via httpx, verify file lands."""

    @pytest.mark.asyncio
    async def test_md_upload_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx
        from fastmcp import Client

        from markdown_vault_mcp.server import make_server

        monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(tmp_path))
        monkeypatch.setenv(
            "MARKDOWN_VAULT_MCP_BASE_URL", "http://test.invalid"
        )
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_READ_ONLY", "false")
        # Clear conflicting env vars (per existing test fixture pattern)
        for var in (
            "MARKDOWN_VAULT_MCP_INDEX_PATH",
            "MARKDOWN_VAULT_MCP_EMBEDDINGS_PATH",
            "MARKDOWN_VAULT_MCP_BEARER_TOKEN",
            "MARKDOWN_VAULT_MCP_OIDC_CONFIG_URL",
        ):
            monkeypatch.delenv(var, raising=False)

        server = make_server(transport="http")
        app = server.http_app(transport="http")

        # Use httpx ASGI transport to talk to the server in-process.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test.invalid"
        ) as http_client:
            # Need to step the lifespan ourselves since ASGITransport doesn't
            # invoke it.  Use the existing client-via-fastmcp pattern instead:
            pass

        # Actual end-to-end via FastMCP Client (handles lifespan automatically):
        async with Client(server) as fm_client:
            # 1. Mint the link
            result = await fm_client.call_tool(
                "create_upload_link",
                {"target_id": "uploaded.md", "ttl_seconds": 60},
            )
            payload = result.data if hasattr(result, "data") else result
            upload_url = payload["upload_url"]
            assert "uploaded.md" in payload.get("target_id", "")

            # 2. POST the bytes
            async with httpx.AsyncClient() as http:
                # The upload_url is built against BASE_URL; rewrite to talk
                # to the in-process server.  Strip the BASE_URL prefix.
                path = upload_url.removeprefix("http://test.invalid")
                resp = await http.post(
                    f"http://test.invalid{path}",
                    content=b"# Uploaded\n\nbody\n",
                    headers={"Content-Type": "application/octet-stream"},
                    transport=httpx.ASGITransport(app=app),
                )
            assert resp.status_code == 200, resp.text

            # 3. Verify the file landed
            assert (tmp_path / "uploaded.md").read_text() == "# Uploaded\n\nbody\n"

            # 4. Verify it's readable via the standard read tool
            read_result = await fm_client.call_tool(
                "read", {"path": "uploaded.md"}
            )
            read_data = read_result.data if hasattr(read_result, "data") else read_result
            assert "Uploaded" in read_data["content"]
```

**Note:** the exact mechanics of stepping the ASGI lifespan + reading the in-memory mounted route may need adjustment based on how `mcp.http_app()` is structured. The pattern to copy from is `tests/test_artifacts.py` — that test does the same thing for the inverse direction (download). Read that file first and mirror its setup verbatim.

If `tests/test_artifacts.py` doesn't exist with this pattern, an alternative is to test the route directly by calling pvl-core's internal helpers — but the round-trip via `httpx` is the most useful test (it catches wiring bugs that direct internal calls would miss).

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_uploads.py::TestUploadEndToEnd -v`
Expected: PASS. If something in the wiring is wrong (route not mounted, validator not called, receiver not supplied), this is where it surfaces.

- [ ] **Step 3: Commit**

```bash
git add tests/test_uploads.py
git commit -m "test(uploads): end-to-end create_upload_link → POST → vault file

Mints a one-time URL via create_upload_link, POSTs bytes via httpx,
verifies the file lands in the vault and is readable via read().
Mirrors the test_artifacts.py setup for the inverse direction.

Refs #443"
```

---

## Task 6: MV-specific docs

**Files:**
- Modify: `README.md`
- Modify: `docs/tools/index.md`
- Modify: `docs/guides/claude-desktop.md`

(The template-shipped docs — env vars in `docs/configuration.md`, the file-exchange guide section, the `## File Exchange` block in `CLAUDE.md` — are already in place from the copier update.)

- [ ] **Step 1: Add `create_upload_link` row to README MCP Tools table**

Find the MCP Tools table in `README.md`. Add a row (sort alphabetically with surrounding rows or append at end):

```markdown
| `create_upload_link` | Mint a one-time HTTPS POST URL for pushing bytes into the vault. The URL accepts raw bytes (`Content-Type: application/octet-stream`) and dispatches to `write` or `write_attachment` based on the path's extension. Bytes flow over HTTP, not through MCP context — use this for any file >100 KB. HTTP/SSE transport only; requires `MARKDOWN_VAULT_MCP_BASE_URL`. |
```

- [ ] **Step 2: Add full tool entry to `docs/tools/index.md`**

Find where `create_download_link` is documented. Add `create_upload_link` immediately after, with a parallel structure:

```markdown
### `create_upload_link`

Mints a one-time HTTPS POST URL for pushing a file into the vault.

**Parameters:**

- `target_id` (str, required): vault-relative path the bytes will be written to (e.g. `"assets/diagram.pdf"` or `"notes/captured.md"`). Validated at link creation — bad paths fail in-band before the link is minted.
- `ttl_seconds` (int, optional, default 300): link lifetime.
- `max_bytes` (int, optional): per-link size cap; defaults to `MARKDOWN_VAULT_MCP_FILE_EXCHANGE_UPLOAD_MAX_BYTES`.

**Returns:**

```json
{
  "upload_url": "https://vault.example.com/vault/uploads/abc123",
  "expires_in_seconds": 300,
  "target_id": "assets/diagram.pdf"
}
```

**Usage from a local agent:**

```bash
# 1. Mint the link via MCP
URL=$(call_create_upload_link target_id="assets/diagram.pdf" | jq -r .upload_url)

# 2. POST the bytes
curl -X POST --data-binary @diagram.pdf \
     -H "Content-Type: application/octet-stream" \
     "$URL"
```

**Context cost:** zero — bytes flow over HTTP, not through MCP context. Use this for any file larger than ~100 KB; for tiny binaries (icons, signatures), `write(content_base64=...)` is acceptable.

**Validation:**
- Path traversal (`../`) rejected at link creation.
- Disallowed extensions (per `MARKDOWN_VAULT_MCP_ATTACHMENT_EXTENSIONS`) rejected at link creation.
- Last-write-wins on path collision (matches `write` semantics).

**Errors:** `ValueError` at link creation for invalid `target_id`. HTTP-side errors (token expired, oversize, etc.) follow the spec contract: 200 / 400 / 404 / 410 / 413 / 415 / 500.

**Tag:** `write` — hidden when `MARKDOWN_VAULT_MCP_READ_ONLY=true`.

**Transport:** HTTP/SSE only. Requires `MARKDOWN_VAULT_MCP_BASE_URL`.
```

- [ ] **Step 3: Add worked example to `docs/guides/claude-desktop.md`**

Find a "Workflows" or "Examples" section in the Claude Desktop guide; if none exists, add one. Insert:

```markdown
## Uploading a local file to the vault

Claude Desktop running with claude-code or a similar local agent can drop files into the vault without round-tripping bytes through context.

1. Ask Claude to mint an upload link for the file's target path:

   > "Use `create_upload_link` to give me a URL for `screenshots/today.png`."

2. Claude returns `upload_url` and `expires_in_seconds`.

3. POST the bytes from your local shell:

   ```bash
   curl -X POST --data-binary @screenshot.png \
        -H "Content-Type: application/octet-stream" \
        "<upload_url>"
   ```

4. The file appears in the vault. Claude can now `read` or `search` for it by path.

For files >1 MB this is the only viable path — `write(content_base64=...)` is bounded by the LLM's context budget and will reject anything over `MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB` (default 1 MB).
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/tools/index.md docs/guides/claude-desktop.md
git commit -m "docs(uploads): create_upload_link tool entry + claude-desktop example

README tool table row, full entry in docs/tools/index.md with curl
example, and a Workflow section in the claude-desktop guide showing
the local-agent upload flow.

Refs #443"
```

---

## Task 7: Run all gates and prepare PR

- [ ] **Step 1: Pre-commit hooks**

Run: `uv run pre-commit run --all-files`
Expected: all green.

- [ ] **Step 2: Tests with patch coverage check**

Run:
```bash
uv run pytest --cov=src/markdown_vault_mcp --cov-report=xml --cov-fail-under=0 -q
uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=80
```
Expected: ≥80% on the patch.

- [ ] **Step 3: Lint + format + mypy**

Run:
```bash
uv run ruff check --fix .
uv run ruff format .
uv run ruff format --check .
uv run mypy src/ tests/
```
Expected: all green.

- [ ] **Step 4: Local review circus per CLAUDE.md**

Dispatch in parallel:

```
Agent: pr-review-toolkit:code-reviewer
  Prompt: Review cumulative diff vs main on branch <branch>.  PR #443 —
  adopts pvl-core 2.1.0's register_file_exchange_upload via the v1.6.0
  template scaffold.  Focus on: receiver dispatch correctness (.md vs
  binary), validator's pre_link semantics (raises ValueError → in-band
  failure), get_collection_singleton thread-safety, ASGI lifespan
  handling in the end-to-end test.

Agent: pr-review-toolkit:silent-failure-hunter
  Prompt: Same diff.  Focus on: does the receiver swallow Collection
  exceptions (it shouldn't — ValueError from write/write_attachment must
  propagate so pvl-core maps it to HTTP 4xx)?  Does the validator's
  use of private Collection methods (_validate_path,
  _check_attachment_extension) silently behave differently from what the
  attachment write path does?  What happens if the singleton isn't set
  (e.g., upload arrives before lifespan startup completes)?
```

Address findings; re-run reviewers until clean.

- [ ] **Step 5: Open the PR (draft)**

```bash
git push -u origin <branch-name>
gh pr create --draft \
  --title "feat(uploads): adopt register_file_exchange_upload (#443)" \
  --body "Closes #443.  Built on top of the copier-update v1.5.1 → v1.6.0 PR (separate, behaviourally inert).

## Summary
- Wires fastmcp-pvl-core v2.1.0's register_file_exchange_upload via the v1.6.0 template's DOMAIN-FILE-EXCHANGE scaffold
- New _vault_upload_receiver dispatches by extension (Collection.write for .md, write_attachment for binaries)
- New _validate_upload_target runs as pre_link_validator, fails in-band on path traversal / disallowed extension
- New get_collection_singleton accessor in _server_deps for handlers outside FastMCP DI
- End-to-end test: create_upload_link → httpx POST → file in vault → readable via read()
- Docs: README tool row, docs/tools/index.md full entry with curl example, claude-desktop workflow guide

## Test plan
- [x] uv run pytest -x -q (all green)
- [x] uv run mypy src/ tests/ (clean)
- [x] uv run pre-commit run --all-files (clean)
- [x] diff-cover ≥80% on patch
- [x] local review circus clean (both subagents)
- [ ] CI green
- [ ] bot reviewers LGTM"
```

- [ ] **Step 6: Babysit + flip ready**

After CI runs and bot reviewers settle, address any findings (re-running local circus before each push). Flip ready when clean:

```bash
gh pr ready <PR-number>
```
