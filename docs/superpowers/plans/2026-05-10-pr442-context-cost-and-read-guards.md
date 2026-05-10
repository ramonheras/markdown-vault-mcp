# PR #442 — Context-cost docstrings + read-side size guards

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the LLM from silently blowing context budget on binary or oversized markdown reads — by tightening the attachment size cap, adding a new note-read cap, and standardising a "Context cost" paragraph across every tool that returns large data.

**Architecture:** Two enforcement points in `DocumentManager` (one already exists for attachments at `read_attachment`; one new for `read`). One new env var (`MAX_NOTE_READ_BYTES`) + tightened default on the existing `MAX_ATTACHMENT_SIZE_MB`. Docstring disclaimers on `read`, `write`, and `fetch` tools.

**Tech Stack:** Python 3.11+ stdlib (`os`, `pathlib`); existing `DocumentManager` / `CollectionConfig` patterns; no new runtime deps.

**Spec:** `docs/superpowers/specs/2026-05-10-out-of-band-file-and-git-ops-design.md` § 2.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/markdown_vault_mcp/config.py` | Add `max_note_read_bytes` field + env loader; lower `max_attachment_size_mb` default 10→1 | Modify |
| `src/markdown_vault_mcp/managers/document.py` | Enforce both caps in `read()` (note) and existing site in `read_attachment()`; rewrite the existing attachment error to point at `create_download_link` | Modify |
| `src/markdown_vault_mcp/_server_tools.py` | Add **Context cost** paragraph to `read`, `write`, `fetch` docstrings | Modify |
| `tests/test_config.py` | Test the new env var loader (default + override + invalid) | Modify |
| `tests/test_document.py` (or wherever `DocumentManager` is tested) | Test cap enforcement on `read` (over/under/disabled) and updated error text on `read_attachment` | Modify |
| `README.md` | Update env var table; add upgrade note for the 10→1 MB change | Modify |
| `docs/configuration.md` | Mirror README env var changes | Modify |
| `docs/tools/index.md` | Per-tool **Context cost** paragraph | Modify |
| `examples/*.env` | Add `MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES` example commented entries | Modify |

---

## Task 1: Add `max_note_read_bytes` to `CollectionConfig` + env loader

**Files:**
- Modify: `src/markdown_vault_mcp/config.py:178` (field), `src/markdown_vault_mcp/config.py:561` (env loader area)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py` (find an existing `TestEnv*` class to add to, or create `TestMaxNoteReadBytes`):

```python
class TestMaxNoteReadBytesEnv:
    """MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES env loader."""

    def test_default_is_262144(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(tmp_path))
        monkeypatch.delenv("MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES", raising=False)
        config = load_config()
        assert config.max_note_read_bytes == 262144

    def test_override_via_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(tmp_path))
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES", "1048576")
        config = load_config()
        assert config.max_note_read_bytes == 1048576

    def test_zero_disables_limit(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(tmp_path))
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES", "0")
        config = load_config()
        assert config.max_note_read_bytes == 0

    def test_invalid_value_falls_back_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(tmp_path))
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES", "not-a-number")
        with caplog.at_level(logging.WARNING):
            config = load_config()
        assert config.max_note_read_bytes == 262144
        assert "MAX_NOTE_READ_BYTES" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::TestMaxNoteReadBytesEnv -v`
Expected: FAIL with `AttributeError: 'CollectionConfig' object has no attribute 'max_note_read_bytes'` on the first test, others not yet collected.

- [ ] **Step 3: Add the field on `CollectionConfig`**

In `src/markdown_vault_mcp/config.py`, find `max_attachment_size_mb: float = 10.0` (around line 178) and add immediately after:

```python
    max_note_read_bytes: int = 262144  # 256 KB; 0 = unlimited
```

- [ ] **Step 4: Add the env loader**

In `src/markdown_vault_mcp/config.py`, find the existing `raw_max_attachment_size = (_env("MAX_ATTACHMENT_SIZE_MB") or "").strip()` block (around line 561). Add an analogous block immediately after it:

```python
    raw_max_note_read_bytes = (_env("MAX_NOTE_READ_BYTES") or "").strip()
    if raw_max_note_read_bytes:
        try:
            max_note_read_bytes = int(raw_max_note_read_bytes)
        except ValueError:
            logger.warning(
                "load_config: invalid MAX_NOTE_READ_BYTES=%r, using default 262144",
                raw_max_note_read_bytes,
            )
            max_note_read_bytes = 262144
        else:
            if max_note_read_bytes < 0:
                logger.warning(
                    "load_config: MAX_NOTE_READ_BYTES=%r is negative, using default 262144",
                    raw_max_note_read_bytes,
                )
                max_note_read_bytes = 262144
    else:
        max_note_read_bytes = 262144
```

Then find the `CollectionConfig(...)` constructor call at the bottom of `load_config` and add `max_note_read_bytes=max_note_read_bytes,` to the kwargs (alphabetised with the others if that's the convention; otherwise next to `max_attachment_size_mb=...`).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py::TestMaxNoteReadBytesEnv -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/markdown_vault_mcp/config.py tests/test_config.py
git commit -m "feat(config): add MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES env var

New config field max_note_read_bytes (default 262144 / 256 KB) for the
upcoming DocumentManager.read size guard.  0 disables the limit.  Env
loader follows the existing MAX_ATTACHMENT_SIZE_MB pattern.

Refs #442"
```

---

## Task 2: Lower `max_attachment_size_mb` default 10 → 1

**Files:**
- Modify: `src/markdown_vault_mcp/config.py:178`, `src/markdown_vault_mcp/config.py:570` and `:574` (existing 10.0 fallbacks)
- Modify: `src/markdown_vault_mcp/managers/document.py:105` (constructor default)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_config.py`, find or create a `TestMaxAttachmentSizeMbDefault` class:

```python
class TestMaxAttachmentSizeMbDefault:
    """Default for MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB tightened in #442."""

    def test_default_is_one_mb(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(tmp_path))
        monkeypatch.delenv("MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB", raising=False)
        config = load_config()
        assert config.max_attachment_size_mb == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::TestMaxAttachmentSizeMbDefault -v`
Expected: FAIL — current default is 10.0.

- [ ] **Step 3: Update the field default**

In `src/markdown_vault_mcp/config.py`, change line 178:

```python
    max_attachment_size_mb: float = 1.0  # MB; 0 = unlimited
```

- [ ] **Step 4: Update the env-loader fallbacks**

In `src/markdown_vault_mcp/config.py`, find lines around 567 and 574 with the literal `10.0` fallback in the `MAX_ATTACHMENT_SIZE_MB` parser. Replace both with `1.0`. Also update the warning log strings if they mention "default 10.0" → "default 1.0".

- [ ] **Step 5: Update `DocumentManager` constructor default**

In `src/markdown_vault_mcp/managers/document.py:105`, change:

```python
        max_attachment_size_mb: float = 1.0,
```

(The constructor signature default is rarely used — tests construct via fixtures and config — but the project convention keeps signature defaults aligned with config defaults.)

- [ ] **Step 6: Update other test files that asserted the 10.0 default**

Run `git grep -n "max_attachment_size_mb.*10\b" tests/` and `git grep -n "MAX_ATTACHMENT_SIZE_MB.*10\b" tests/` to find any test that relies on the old default. Update each to either set the env var explicitly to 10 (preserving original intent) or use the new 1.0 default. If unsure which test wants which, the safer answer is "set to 10 explicitly" — preserving the test's data-shape intent.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -x -q`
Expected: all green. If anything fails because of the default change, fix per Step 6.

- [ ] **Step 8: Commit**

```bash
git add src/markdown_vault_mcp/config.py src/markdown_vault_mcp/managers/document.py tests/
git commit -m "feat(config)!: lower MAX_ATTACHMENT_SIZE_MB default 10 → 1

Most LLM contexts can't survive a 10 MB base64-encoded attachment; the
old default was a silent context-blow-up.  1 MB is small enough that
even tight contexts (~200K tokens) survive a single read.  Operators
with explicit non-LLM consumers raise via the existing env var.

BREAKING: any deployment relying on the 10 MB default needs to set
MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB=10 explicitly.

Refs #442"
```

---

## Task 3: Update `read_attachment` error message to point at `create_download_link`

**Files:**
- Modify: `src/markdown_vault_mcp/managers/document.py:351-356` (existing error message)
- Test: `tests/test_document.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_document.py` (or whichever test file covers `read_attachment` — find via `git grep -l "read_attachment" tests/`):

```python
class TestReadAttachmentErrorMessage:
    """The size-cap ValueError must point at create_download_link, not just 'raise the limit'."""

    def test_error_mentions_create_download_link(
        self, vault_path: Path
    ) -> None:
        from markdown_vault_mcp.managers.document import DocumentManager

        big_file = vault_path / "big.bin"
        big_file.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB

        manager = DocumentManager(
            source_dir=vault_path,
            attachment_extensions=["bin"],
            max_attachment_size_mb=1.0,
        )

        with pytest.raises(ValueError, match="create_download_link"):
            manager.read_attachment("big.bin")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_document.py::TestReadAttachmentErrorMessage -v`
Expected: FAIL — current message says "Raise MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB or set it to 0".

- [ ] **Step 3: Rewrite the error message**

In `src/markdown_vault_mcp/managers/document.py:351-356`, replace the existing `raise ValueError(...)` block with:

```python
                raise ValueError(
                    f"Attachment {path!r} is {size_bytes} bytes "
                    f"({size_bytes / 1024 / 1024:.1f} MB), exceeds "
                    f"MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB "
                    f"({self._max_attachment_size_mb} MB). "
                    f"Use create_download_link({path!r}) for HTTP transfer, "
                    f"or raise MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB if "
                    f"you need the bytes in context."
                )
```

The same error appears at line 531 (in `write_attachment`'s pre-write check). Update it the same way for consistency, but the message there should say "Use a smaller file" rather than "Use create_download_link" — that's the inbound path.

For the write-side at line 531, use:

```python
                    raise ValueError(
                        f"Attachment {path!r} is {size_bytes} bytes "
                        f"({size_bytes / 1024 / 1024:.1f} MB), exceeds "
                        f"MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB "
                        f"({self._max_attachment_size_mb} MB). "
                        f"Use create_upload_link({path!r}) (#443, when available) "
                        f"for out-of-band upload, or raise the limit env var."
                    )
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_document.py::TestReadAttachmentErrorMessage -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markdown_vault_mcp/managers/document.py tests/test_document.py
git commit -m "feat(read): error messages point LLMs at the right alternative

When read_attachment / write_attachment hit MAX_ATTACHMENT_SIZE_MB,
the error now names create_download_link (or create_upload_link from
#443) so the LLM doesn't loop on cap-bump-and-retry.

Refs #442"
```

---

## Task 4: Add note-read size guard in `DocumentManager.read`

**Files:**
- Modify: `src/markdown_vault_mcp/managers/document.py:225` (the `read` method)
- Modify: `src/markdown_vault_mcp/managers/document.py:105` (constructor — add `max_note_read_bytes` parameter)
- Modify: `src/markdown_vault_mcp/collection.py` (where `DocumentManager` is constructed — pass through the new field)
- Test: `tests/test_document.py`

- [ ] **Step 1: Write the failing test**

```python
class TestReadNoteSizeGuard:
    """DocumentManager.read enforces MAX_NOTE_READ_BYTES."""

    def test_read_under_limit_returns_content(self, vault_path: Path) -> None:
        from markdown_vault_mcp.managers.document import DocumentManager

        small = vault_path / "small.md"
        small.write_text("# Small\n\nbody")

        manager = DocumentManager(
            source_dir=vault_path,
            max_note_read_bytes=1024,
        )
        result = manager.read("small.md")
        assert result is not None
        assert "body" in result.content

    def test_read_over_limit_raises(self, vault_path: Path) -> None:
        from markdown_vault_mcp.managers.document import DocumentManager

        big = vault_path / "big.md"
        big.write_text("# Big\n\n" + "x" * 2048)

        manager = DocumentManager(
            source_dir=vault_path,
            max_note_read_bytes=512,
        )
        with pytest.raises(ValueError, match="MAX_NOTE_READ_BYTES"):
            manager.read("big.md")

    def test_read_zero_disables_limit(self, vault_path: Path) -> None:
        from markdown_vault_mcp.managers.document import DocumentManager

        big = vault_path / "big.md"
        big.write_text("# Big\n\n" + "x" * (10 * 1024 * 1024))  # 10 MB note

        manager = DocumentManager(
            source_dir=vault_path,
            max_note_read_bytes=0,
        )
        result = manager.read("big.md")
        assert result is not None

    def test_read_section_bypasses_full_doc_limit(self, vault_path: Path) -> None:
        """`section=` reads don't load the full document into context, so they
        bypass the full-document cap and use the section's own size only."""
        from markdown_vault_mcp.managers.document import DocumentManager

        big = vault_path / "big.md"
        big.write_text("# Big\n\n" + "x" * 2048 + "\n\n## Section\n\nshort")

        manager = DocumentManager(
            source_dir=vault_path,
            max_note_read_bytes=512,
        )
        # Whole doc would fail, but section read is allowed
        result = manager.read("big.md", section="Section")
        assert result is not None
        assert "short" in result.content

    def test_error_mentions_section_and_env_var(self, vault_path: Path) -> None:
        from markdown_vault_mcp.managers.document import DocumentManager

        big = vault_path / "big.md"
        big.write_text("# Big\n\n" + "x" * 2048)

        manager = DocumentManager(
            source_dir=vault_path,
            max_note_read_bytes=512,
        )
        with pytest.raises(ValueError) as exc_info:
            manager.read("big.md")
        msg = str(exc_info.value)
        assert "MAX_NOTE_READ_BYTES" in msg
        assert "section=" in msg  # error must point at the partial-read alternative
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_document.py::TestReadNoteSizeGuard -v`
Expected: FAIL — the constructor doesn't accept `max_note_read_bytes` yet.

- [ ] **Step 3: Add the constructor parameter**

In `src/markdown_vault_mcp/managers/document.py`, find the `__init__` signature (around line 100). Add the parameter:

```python
    def __init__(
        self,
        source_dir: Path,
        *,
        # ... existing params ...
        max_attachment_size_mb: float = 1.0,
        max_note_read_bytes: int = 262144,
        # ... rest ...
    ):
```

Update the docstring to mention the new parameter, then store it:

```python
        self._max_note_read_bytes = max_note_read_bytes
```

- [ ] **Step 4: Add the size check in `read()`**

In `src/markdown_vault_mcp/managers/document.py`, in the `read` method (line 225). After the `if not abs_path.is_file(): return None` check (around line 258) and before the `parse_note(...)` call (line 261), insert:

```python
        # Enforce MAX_NOTE_READ_BYTES (only on full-document reads — section
        # reads bypass this cap because they only load one chunk).
        if section is None and self._max_note_read_bytes > 0:
            size_bytes = abs_path.stat().st_size
            if size_bytes > self._max_note_read_bytes:
                raise ValueError(
                    f"Document {path!r} is {size_bytes} bytes "
                    f"({size_bytes / 1024:.1f} KB), exceeds "
                    f"MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES "
                    f"({self._max_note_read_bytes} bytes). "
                    f"Use read({path!r}, section=...) for partial reads "
                    f"(see search() output's heading field), or raise "
                    f"MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES if you need the "
                    f"full document in context."
                )
```

Note the position: BEFORE `if section is not None` would short-circuit, the new check must run only when `section is None` (we already enter the `else` branch by Python's flow, but be explicit with the `section is None` guard since this code path runs for the whole-document case).

Actually re-reading the existing flow: `read` calls `_read_section` immediately if `section is not None` and returns. So the code below `if section is not None` only runs for whole-document reads — the explicit `section is None` guard in the new check is defensive; remove it for clarity:

```python
        # Enforce MAX_NOTE_READ_BYTES (whole-document reads only — `section=`
        # bypassed via early return above).
        if self._max_note_read_bytes > 0:
            size_bytes = abs_path.stat().st_size
            if size_bytes > self._max_note_read_bytes:
                raise ValueError(
                    f"Document {path!r} is {size_bytes} bytes "
                    f"({size_bytes / 1024:.1f} KB), exceeds "
                    f"MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES "
                    f"({self._max_note_read_bytes} bytes). "
                    f"Use read({path!r}, section=...) for partial reads "
                    f"(see search() output's heading field), or raise "
                    f"MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES if you need the "
                    f"full document in context."
                )
```

- [ ] **Step 5: Wire `max_note_read_bytes` through `Collection`**

In `src/markdown_vault_mcp/collection.py`, find where `DocumentManager(...)` is constructed inside `Collection.__init__`. Add the new parameter in the same way `max_attachment_size_mb` is passed today.

Also update `Collection.__init__`'s signature to accept `max_note_read_bytes: int = 262144` and store/forward it.

Find the `to_collection_kwargs()` method on `CollectionConfig` (in `config.py`) and add `"max_note_read_bytes": self.max_note_read_bytes,` to the dict it returns.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_document.py::TestReadNoteSizeGuard -v`
Expected: 5 passed.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -x -q`
Expected: all green. Anything that calls `DocumentManager(source_dir=...)` without the new kwarg will pick up the default 262144 — should be fine but verify.

- [ ] **Step 8: Commit**

```bash
git add src/markdown_vault_mcp/managers/document.py src/markdown_vault_mcp/collection.py src/markdown_vault_mcp/config.py tests/test_document.py
git commit -m "feat(read): size guard on full-document reads (MAX_NOTE_READ_BYTES)

DocumentManager.read now raises ValueError if a whole-document read
would exceed MAX_NOTE_READ_BYTES (default 256 KB).  section= reads are
unaffected — they only load one chunk.  Error message points the LLM
at section= and the env-var override.

Refs #442"
```

---

## Task 5: Add **Context cost** paragraph to `read` tool docstring

**Files:**
- Modify: `src/markdown_vault_mcp/_server_tools.py:169` (the `read` tool registration)

- [ ] **Step 1: Locate the `read` tool docstring**

Read `src/markdown_vault_mcp/_server_tools.py` lines 169-220 (the `async def read(...)` docstring). Note the current structure — Args, Returns, etc.

- [ ] **Step 2: Insert the disclaimer**

Find the existing docstring's first paragraph (the brief tool summary). Add a new paragraph immediately after it, before any Args/Returns blocks:

```python
        """Read a document or attachment from the vault.

        ... (existing summary text) ...

        **Context cost:** every byte returned counts against the LLM's
        context budget.  Reads above `MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES`
        (default 256 KB for `.md`) or `MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB`
        (default 1 MB for binaries) raise `ValueError` with the right
        alternative.  For partial markdown reads, pass `section=heading` (use
        the `heading` field from a `search()` result).  For binary transfer,
        use `create_download_link(path)` to mint an HTTPS URL — bytes flow
        over HTTP, not through context.

        Args:
            ... (existing) ...
        """
```

(Read the actual existing text first to preserve structure exactly; only add the new paragraph.)

- [ ] **Step 3: No new test required** — docstring change.

- [ ] **Step 4: Verify the docstring renders correctly**

Run: `uv run python -c "from markdown_vault_mcp._server_tools import register_tools; help(register_tools)"` — confirms the module imports. The actual tool docstring is best-effort verified by reading the file:

```bash
sed -n '169,230p' src/markdown_vault_mcp/_server_tools.py
```

Visually confirm the **Context cost** paragraph is in place.

- [ ] **Step 5: Commit**

```bash
git add src/markdown_vault_mcp/_server_tools.py
git commit -m "docs(read): add Context cost disclaimer to docstring

Tells the LLM in-band that bytes returned count against context, names
section= for partial markdown reads and create_download_link for binary
transfer.  Establishes the **Context cost:** convention for #443's new
upload tool and any future tools that return large data.

Refs #442"
```

---

## Task 6: Add **Context cost** paragraph to `write` tool docstring (`content_base64`)

**Files:**
- Modify: `src/markdown_vault_mcp/_server_tools.py:1021` (the `write` tool)

- [ ] **Step 1: Locate the `write` tool docstring's `content_base64` parameter description**

Read `src/markdown_vault_mcp/_server_tools.py` around line 1021 (`async def write(...)`). The `content_base64` parameter is documented in the Args block.

- [ ] **Step 2: Insert the disclaimer**

In the `Args:` block, find the `content_base64:` entry. Append the disclaimer to its description:

```
        content_base64: Base64-encoded binary content for attachment files.
            Required when path is not `.md`.

            **Context cost:** base64 encoding inflates by ~33%; even a 1 MB
            attachment becomes ~1.3 MB of tokens.  For files larger than
            ~100 KB, prefer `create_upload_link(path)` (#443, when
            available) — bytes flow over HTTPS POST, not through context.
```

- [ ] **Step 3: No new test required.**

- [ ] **Step 4: Commit**

```bash
git add src/markdown_vault_mcp/_server_tools.py
git commit -m "docs(write): add Context cost disclaimer to content_base64 param

Refs #442"
```

---

## Task 7: Reinforce **Context cost** message on `fetch` tool docstring

**Files:**
- Modify: `src/markdown_vault_mcp/_server_tools.py:1288` (the `fetch` tool)

- [ ] **Step 1: Locate the `fetch` tool docstring**

Read `src/markdown_vault_mcp/_server_tools.py` around line 1288. `fetch` already mentions URL transfer; reinforce that the saved file should be referenced by path afterwards.

- [ ] **Step 2: Update the docstring**

After the existing summary, ensure there's a paragraph like:

```
        **Context cost:** zero for the bytes themselves — the file is
        downloaded server-side and saved to the vault.  After a successful
        fetch, reference the file by its `path` (call `read(path)` only
        for small results, otherwise pass the path to other tools).
```

If a similar paragraph already exists, just verify it's there; don't duplicate.

- [ ] **Step 3: Commit**

```bash
git add src/markdown_vault_mcp/_server_tools.py
git commit -m "docs(fetch): reinforce Context cost disclaimer

The bytes never enter context, but the LLM might still try to read()
the just-saved file — note that the saved file should be referenced
by path for downstream tools.

Refs #442"
```

---

## Task 8: Update README + docs/configuration.md for new env vars

**Files:**
- Modify: `README.md` (env var table; new upgrade note section)
- Modify: `docs/configuration.md` (mirror)

- [ ] **Step 1: Update the env var table in `README.md`**

Find the env var table (search for `MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB`). Update the existing row's default from `10` to `1`, and add a new row for `MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES` immediately after it.

Example of the new row format (match existing column order):

```markdown
| `MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES` | int | `262144` (256 KB) | Maximum bytes returned by full-document `read()` for `.md` files; raises `ValueError` if exceeded. Use `read(path, section=...)` for partial reads. `0` disables the limit. |
```

- [ ] **Step 2: Add an upgrade note section in `README.md`**

Find the "Upgrading" or "Migration" section if one exists; if not, add one near the bottom of the README with:

```markdown
### Upgrading from <previous-version>

- `MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB` default lowered from **10 MB**
  to **1 MB**.  Most LLM contexts can't survive a 10 MB base64-encoded
  attachment; the old default was a silent context-blow-up.  If you have
  non-LLM consumers (scripts, CI) that need the old behaviour, set
  `MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB=10` explicitly.
- `MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES` is a **new** env var (default
  256 KB).  Whole-document `.md` reads above this raise `ValueError`.
  Partial reads via `read(path, section=heading)` bypass the cap.
```

- [ ] **Step 3: Mirror in `docs/configuration.md`**

Apply the same env var table updates and upgrade note. (May need to find the right section — `docs/configuration.md` typically has a more detailed table than the README.)

- [ ] **Step 4: Commit**

```bash
git add README.md docs/configuration.md
git commit -m "docs(config): document MAX_NOTE_READ_BYTES and the cap-default change

Refs #442"
```

---

## Task 9: Update `docs/tools/index.md` with per-tool **Context cost** paragraphs

**Files:**
- Modify: `docs/tools/index.md`

- [ ] **Step 1: Locate the `read`, `write`, `fetch` tool entries**

Open `docs/tools/index.md`. Find each tool's section (typically headed `### read`, `### write`, `### fetch`).

- [ ] **Step 2: Add a **Context cost** subsection to each**

For `read`, after the existing description and before/after the Args table:

```markdown
**Context cost:** every byte returned counts against the LLM's context
budget.  Reads above `MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES` (default
256 KB for `.md`) or `MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB` (default
1 MB for binaries) raise an error with the right alternative — `section=`
for partial markdown reads, `create_download_link()` for binary transfer.
```

For `write`:

```markdown
**Context cost:** the `content` parameter (text) is bounded only by the
LLM's own output budget.  The `content_base64` parameter (binary) inflates
by ~33%; for files >100 KB use `create_upload_link()` (#443, when
available) instead.
```

For `fetch`:

```markdown
**Context cost:** zero — the file is downloaded server-side.  Reference
the saved file by `path` for downstream tools rather than `read()`-ing it
back into context.
```

- [ ] **Step 3: Commit**

```bash
git add docs/tools/index.md
git commit -m "docs(tools): per-tool Context cost paragraphs for read/write/fetch

Refs #442"
```

---

## Task 10: Update `examples/*.env` files

**Files:**
- Modify: every `examples/*.env` file (there are typically 3-4)

- [ ] **Step 1: List the example env files**

Run: `ls examples/*.env`

- [ ] **Step 2: Add commented entries for the new and changed env vars**

Append (or update if already present) the following block to each example `.env` file, near the existing `MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB` line:

```bash
# Maximum attachment size in MB returned by read() / accepted by write().
# Default 1 MB (lowered from 10 MB in #442 to keep LLM context bounded).
# Set to 0 to disable the limit.
# MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB=1

# Maximum bytes returned by full-document read() for .md files.
# Default 262144 (256 KB).  Use read(path, section=...) for partial reads.
# Set to 0 to disable the limit.
# MARKDOWN_VAULT_MCP_MAX_NOTE_READ_BYTES=262144
```

- [ ] **Step 3: Commit**

```bash
git add examples/
git commit -m "docs(examples): document MAX_NOTE_READ_BYTES + new attachment default

Refs #442"
```

---

## Task 11: Run all gates and prepare PR

- [ ] **Step 1: Pre-commit hooks**

Run: `uv run pre-commit run --all-files`
Expected: all green. Fix anything that fails.

- [ ] **Step 2: Tests with patch coverage check**

Run:
```bash
uv run pytest --cov=src/markdown_vault_mcp --cov-report=xml --cov-fail-under=0 -q
uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=80
```
Expected: ≥80% on the patch.

- [ ] **Step 3: Run full lint + format + mypy**

Run:
```bash
uv run ruff check --fix .
uv run ruff format .
uv run ruff format --check .
uv run mypy src/ tests/
```
Expected: all green.

- [ ] **Step 4: Run the local review circus per CLAUDE.md PR workflow**

Dispatch both subagent reviewers on the cumulative branch diff (per the Pre-flight checklist in `~/.claude/CLAUDE.md`):

```
Agent: pr-review-toolkit:code-reviewer
  Prompt: Review the cumulative diff on branch <branch-name> against main.
  This is PR #442 — context-bloat docstrings + read-side caps.  Focus
  on the new MAX_NOTE_READ_BYTES enforcement, the lowered cap default
  (10→1 MB) being a soft-breaking change, and the docstring disclaimer
  pattern that #443 will adopt.

Agent: pr-review-toolkit:silent-failure-hunter
  Prompt: Same diff.  Focus on the new error-message paths — do they
  actually point at create_download_link / section= / the env var, or
  do they say something generic that the LLM will ignore?  Also: does
  any caller catch the new ValueError in a way that swallows the
  actionable message?
```

Address findings in commits, re-run reviewers until clean.

- [ ] **Step 5: Open the PR (draft)**

```bash
git push -u origin <branch-name>
gh pr create --draft \
  --title "feat(read): context-cost docstrings + read-side size guards (#442)" \
  --body "Closes #442

## Summary
- Lowered MAX_ATTACHMENT_SIZE_MB default 10→1 (soft-breaking — see upgrade note in README)
- New MAX_NOTE_READ_BYTES env var (default 256 KB) enforced in DocumentManager.read for whole-document reads; section= bypasses it
- Updated error messages on attachment cap to point at create_download_link
- New Context cost paragraph convention on read / write / fetch docstrings; future tools (#443's create_upload_link) adopt the same pattern
- Docs: README env var table + upgrade note, docs/configuration.md mirror, docs/tools/index.md per-tool paragraphs, examples/*.env defaults

## Test plan
- [x] uv run pytest -x -q (all green)
- [x] uv run mypy src/ tests/ (clean)
- [x] uv run pre-commit run --all-files (clean)
- [x] diff-cover ≥80% on patch
- [x] local review circus clean (both subagents)
- [ ] CI green
- [ ] bot reviewers LGTM"
```

- [ ] **Step 6: Babysit the PR**

After CI runs, address any bot findings per CLAUDE.md (defend in writing if wrong; re-run local circus before any push).

- [ ] **Step 7: Flip ready when CI + bot reviewers green**

```bash
gh pr ready <PR-number>
```
