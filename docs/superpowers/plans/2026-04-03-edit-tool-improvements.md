# Edit Tool Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `edit` tool more reliable for LLM consumers by adding line-range editing, normalized text matching, and diagnostic error messages.

**Architecture:** Three backwards-compatible improvements layered onto the existing `Collection.edit()` method. New private helpers (`_normalize_text`, `_build_position_map`, `_find_closest_match`) handle normalization and diagnostics. The MCP layer catches `EditConflictError` to surface structured diagnostics in error text.

**Tech Stack:** Python 3.10+, stdlib only (`unicodedata`, `re`, `difflib`). No new dependencies.

**Issue:** #325

---

### Task 1: Add `match_type` to `EditResult`

**Files:**
- Modify: `src/markdown_vault_mcp/types.py:104-109`
- Test: `tests/test_collection.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_collection.py`, add to the existing `TestEdit` class:

```python
def test_edit_match_type_exact_default(
    self, writable: Collection, vault_path: Path
) -> None:
    """edit() returns match_type='exact' by default."""
    result = writable.edit("simple.md", "Simple Document", "Updated Document")
    assert result.match_type == "exact"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_collection.py::TestEdit::test_edit_match_type_exact_default -v`
Expected: FAIL with `AttributeError: 'EditResult' object has no attribute 'match_type'`

- [ ] **Step 3: Add `match_type` field to `EditResult`**

In `src/markdown_vault_mcp/types.py`, modify `EditResult`:

```python
@dataclass
class EditResult:
    """Result of an edit operation."""

    path: str
    replacements: int
    match_type: str = "exact"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_collection.py::TestEdit::test_edit_match_type_exact_default -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run python -m pytest tests/test_collection.py tests/test_mcp_server.py -x -q`
Expected: All pass. The new default `"exact"` is backwards-compatible.

- [ ] **Step 6: Commit**

```bash
git add src/markdown_vault_mcp/types.py tests/test_collection.py
git commit -m "feat(edit): add match_type field to EditResult (#325)"
```

---

### Task 2: Add diagnostic fields to `EditConflictError`

**Files:**
- Modify: `src/markdown_vault_mcp/exceptions.py:16-17`
- Test: `tests/test_collection.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_collection.py`, add a new test class after `TestEdit`:

```python
class TestEditConflictDiagnostics:
    def test_error_has_diagnostic_fields(self) -> None:
        """EditConflictError stores diagnostic fields."""
        err = EditConflictError(
            "old_text not found in test.md",
            closest_match_line=10,
            first_diff_char=42,
            expected_snippet="—",
            found_snippet="-",
        )
        assert err.closest_match_line == 10
        assert err.first_diff_char == 42
        assert err.expected_snippet == "—"
        assert err.found_snippet == "-"
        assert str(err) == "old_text not found in test.md"

    def test_error_defaults_none(self) -> None:
        """EditConflictError diagnostic fields default to None."""
        err = EditConflictError("old_text not found in test.md")
        assert err.closest_match_line is None
        assert err.first_diff_char is None
        assert err.expected_snippet is None
        assert err.found_snippet is None
```

Add the import at the top of `tests/test_collection.py` if not already present:

```python
from markdown_vault_mcp.exceptions import EditConflictError
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_collection.py::TestEditConflictDiagnostics -v`
Expected: FAIL with `TypeError: EditConflictError.__init__() got an unexpected keyword argument 'closest_match_line'`

- [ ] **Step 3: Add diagnostic fields to `EditConflictError`**

In `src/markdown_vault_mcp/exceptions.py`, replace the `EditConflictError` class:

```python
class EditConflictError(MarkdownMCPError):
    """old_text not found or appears more than once."""

    def __init__(
        self,
        message: str,
        *,
        closest_match_line: int | None = None,
        first_diff_char: int | None = None,
        expected_snippet: str | None = None,
        found_snippet: str | None = None,
    ) -> None:
        super().__init__(message)
        self.closest_match_line = closest_match_line
        self.first_diff_char = first_diff_char
        self.expected_snippet = expected_snippet
        self.found_snippet = found_snippet
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_collection.py::TestEditConflictDiagnostics -v`
Expected: PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `uv run python -m pytest tests/test_collection.py tests/test_mcp_server.py -x -q`
Expected: All pass. Existing `EditConflictError("message")` calls still work (all new params are keyword-only with defaults).

- [ ] **Step 6: Commit**

```bash
git add src/markdown_vault_mcp/exceptions.py tests/test_collection.py
git commit -m "feat(edit): add diagnostic fields to EditConflictError (#325)"
```

---

### Task 3: Implement `_normalize_text` and `_build_position_map` helpers

**Files:**
- Modify: `src/markdown_vault_mcp/collection.py` (add helpers near top of file, after imports)
- Test: `tests/test_collection.py`

- [ ] **Step 1: Write failing tests for `_normalize_text`**

In `tests/test_collection.py`, add a new test class:

```python
from markdown_vault_mcp.collection import _normalize_text, _build_position_map


class TestNormalizeText:
    def test_nfc_normalization(self) -> None:
        """NFC normalizes composed vs decomposed Unicode."""
        # e + combining acute accent → é (composed)
        decomposed = "caf\u0065\u0301"
        assert _normalize_text(decomposed) == "caf\u00e9"

    def test_dashes_normalized(self) -> None:
        """En-dash and em-dash become hyphens."""
        assert _normalize_text("a\u2013b\u2014c") == "a-b-c"

    def test_smart_quotes_normalized(self) -> None:
        """Smart quotes become straight quotes."""
        assert _normalize_text("\u201chello\u201d \u2018world\u2019") == '"hello" \'world\''

    def test_whitespace_collapsed(self) -> None:
        """Multiple spaces/tabs collapse to single space within lines."""
        assert _normalize_text("a   b\tc") == "a b c"

    def test_trailing_whitespace_stripped(self) -> None:
        """Trailing whitespace stripped per line."""
        assert _normalize_text("hello   \nworld\t\n") == "hello\nworld\n"

    def test_newlines_preserved(self) -> None:
        """Newlines are not collapsed."""
        assert _normalize_text("a\n\nb") == "a\n\nb"

    def test_no_change_passthrough(self) -> None:
        """Clean text passes through unchanged."""
        text = "hello world"
        assert _normalize_text(text) == text
```

- [ ] **Step 2: Write failing tests for `_build_position_map`**

In the same file, add:

```python
class TestBuildPositionMap:
    def test_identity_mapping(self) -> None:
        """When text is already normalized, positions map 1:1."""
        text = "hello"
        pos_map = _build_position_map(text, text)
        assert pos_map == [0, 1, 2, 3, 4]

    def test_dash_mapping(self) -> None:
        """Em-dash (1 char) maps to hyphen (1 char)."""
        original = "a\u2014b"
        normalized = _normalize_text(original)
        pos_map = _build_position_map(original, normalized)
        # normalized is "a-b", length 3
        assert len(pos_map) == 3
        assert pos_map[0] == 0  # 'a' -> 'a'
        assert pos_map[1] == 1  # '—' -> '-'
        assert pos_map[2] == 2  # 'b' -> 'b'

    def test_whitespace_collapse_mapping(self) -> None:
        """Multiple spaces collapse; map points to first original space."""
        original = "a   b"
        normalized = _normalize_text(original)
        pos_map = _build_position_map(original, normalized)
        # normalized is "a b", length 3
        assert len(pos_map) == 3
        assert pos_map[0] == 0  # 'a'
        assert pos_map[1] == 1  # first space of '   '
        assert pos_map[2] == 4  # 'b'

    def test_trailing_ws_mapping(self) -> None:
        """Trailing whitespace stripped; mapping covers remaining chars."""
        original = "ab  "
        normalized = _normalize_text(original)
        pos_map = _build_position_map(original, normalized)
        # normalized is "ab", length 2
        assert len(pos_map) == 2
        assert pos_map[0] == 0
        assert pos_map[1] == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_collection.py::TestNormalizeText tests/test_collection.py::TestBuildPositionMap -v`
Expected: FAIL with `ImportError: cannot import name '_normalize_text' from 'markdown_vault_mcp.collection'`

- [ ] **Step 4: Implement `_normalize_text`**

In `src/markdown_vault_mcp/collection.py`, add `import unicodedata` to the existing imports (near line 17 — `re` is already imported). Then add the function after the imports:

```python
def _normalize_text(text: str) -> str:
    """Normalize text for fuzzy edit matching.

    Applied to both old_text and file content for comparison only — the
    actual file replacement uses original bytes.

    Steps:
        1. Unicode NFC normalization.
        2. En-dash / em-dash → hyphen.
        3. Smart quotes → straight quotes.
        4. Collapse whitespace runs within lines (not across newlines).
        5. Strip trailing whitespace per line.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    lines = text.split("\n")
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in lines]
    return "\n".join(lines)
```

- [ ] **Step 5: Implement `_build_position_map`**

In the same file, right after `_normalize_text`. Note: `unicodedata` was added in the previous step; no new imports needed:

```python
def _build_position_map(original: str, normalized: str) -> list[int]:
    """Map each normalized character index to its original character index.

    Walks both strings in parallel, advancing the original pointer past
    characters that were removed or merged by normalization.

    Args:
        original: The original (un-normalized) text.
        normalized: The result of ``_normalize_text(original)``.

    Returns:
        A list where ``pos_map[i]`` is the index in *original* that
        corresponds to ``normalized[i]``.
    """
    pos_map: list[int] = []
    orig_idx = 0
    norm_idx = 0
    orig_len = len(original)
    norm_len = len(normalized)

    while norm_idx < norm_len:
        if orig_idx >= orig_len:
            # Safety: normalized should never be longer.
            break

        norm_char = normalized[norm_idx]
        orig_char = original[orig_idx]

        # Newlines anchor both streams.
        if norm_char == "\n" and orig_char == "\n":
            pos_map.append(orig_idx)
            orig_idx += 1
            norm_idx += 1
            continue

        # Trailing whitespace was stripped: skip original trailing ws
        # before a newline or end-of-string.
        if norm_char == "\n" or (norm_idx == norm_len - 1 and norm_char != "\n"):
            if norm_char != "\n":
                # last char of normalized, not a newline — emit it first
                pos_map.append(orig_idx)
                orig_idx += 1
                norm_idx += 1
            # skip trailing whitespace in original before newline/end
            while orig_idx < orig_len and original[orig_idx] in " \t":
                orig_idx += 1
            continue

        # Direct character match (possibly after substitution).
        norm_of_orig = _normalize_text(orig_char)
        if norm_of_orig == norm_char:
            pos_map.append(orig_idx)
            orig_idx += 1
            norm_idx += 1
            continue

        # Whitespace collapse: normalized has single space, original has
        # multiple spaces/tabs.
        if norm_char == " " and orig_char in " \t":
            pos_map.append(orig_idx)
            orig_idx += 1
            # skip remaining whitespace in original
            while orig_idx < orig_len and original[orig_idx] in " \t":
                orig_idx += 1
            norm_idx += 1
            continue

        # Unicode NFC: original may have multiple chars for one normalized.
        # Try expanding original chars until they normalize to norm_char.
        consumed = 1
        while orig_idx + consumed <= orig_len:
            chunk = original[orig_idx : orig_idx + consumed]
            if unicodedata.normalize("NFC", chunk) == norm_char:
                pos_map.append(orig_idx)
                orig_idx += consumed
                norm_idx += 1
                break
            consumed += 1
        else:
            # Fallback: advance both by one.
            pos_map.append(orig_idx)
            orig_idx += 1
            norm_idx += 1

    return pos_map
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_collection.py::TestNormalizeText tests/test_collection.py::TestBuildPositionMap -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/markdown_vault_mcp/collection.py tests/test_collection.py
git commit -m "feat(edit): add _normalize_text and _build_position_map helpers (#325)"
```

---

### Task 4: Implement `_find_closest_match` diagnostic helper

**Files:**
- Modify: `src/markdown_vault_mcp/collection.py`
- Test: `tests/test_collection.py`

- [ ] **Step 1: Write failing tests**

In `tests/test_collection.py`, add:

```python
from markdown_vault_mcp.collection import _find_closest_match


class TestFindClosestMatch:
    def test_close_match_found(self) -> None:
        """Returns diagnostic info when a close match exists."""
        old_text = "the quick—brown fox"
        file_content = "line one\nthe quick-brown fox\nline three\n"
        diag = _find_closest_match(old_text, file_content)
        assert diag["closest_match_line"] == 2
        assert diag["first_diff_char"] is not None
        assert diag["expected_snippet"] is not None
        assert diag["found_snippet"] is not None

    def test_no_close_match(self) -> None:
        """Returns empty dict when nothing is close."""
        old_text = "completely different text xyz123"
        file_content = "line one\nline two\nline three\n"
        diag = _find_closest_match(old_text, file_content)
        assert diag == {}

    def test_exact_match_reports_line(self) -> None:
        """Even near-exact matches are reported with correct line number."""
        old_text = "hello world"
        file_content = "first\nhello worlds\nthird\n"
        diag = _find_closest_match(old_text, file_content)
        assert diag["closest_match_line"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_collection.py::TestFindClosestMatch -v`
Expected: FAIL with `ImportError: cannot import name '_find_closest_match'`

- [ ] **Step 3: Implement `_find_closest_match`**

In `src/markdown_vault_mcp/collection.py`, add `from difflib import SequenceMatcher` to the imports section, then add after `_build_position_map`:

```python
def _find_closest_match(old_text: str, file_content: str) -> dict[str, Any]:
    """Find the closest fuzzy match for diagnostic error reporting.

    Compares the first line of *old_text* against every line in the file
    using ``difflib.SequenceMatcher``.  If a match with ratio >= 0.6 is
    found, returns diagnostic info about the first character divergence.

    Args:
        old_text: The text the caller tried to match.
        file_content: The full file content.

    Returns:
        A dict with ``closest_match_line``, ``first_diff_char``,
        ``expected_snippet``, and ``found_snippet``; or an empty dict
        if no match with ratio >= 0.6 is found.
    """
    first_line = old_text.split("\n", 1)[0]
    file_lines = file_content.split("\n")
    best_ratio = 0.0
    best_line_num = 0
    best_line_text = ""

    for i, line in enumerate(file_lines, 1):
        ratio = SequenceMatcher(None, first_line, line).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_line_num = i
            best_line_text = line

    if best_ratio < 0.6:
        return {}

    # Find first character difference.
    diff_pos = 0
    min_len = min(len(first_line), len(best_line_text))
    while diff_pos < min_len and first_line[diff_pos] == best_line_text[diff_pos]:
        diff_pos += 1

    ctx = 30
    return {
        "closest_match_line": best_line_num,
        "first_diff_char": diff_pos,
        "expected_snippet": first_line[max(0, diff_pos - ctx) : diff_pos + ctx],
        "found_snippet": best_line_text[max(0, diff_pos - ctx) : diff_pos + ctx],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_collection.py::TestFindClosestMatch -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/markdown_vault_mcp/collection.py tests/test_collection.py
git commit -m "feat(edit): add _find_closest_match diagnostic helper (#325)"
```

---

### Task 5: Refactor `Collection.edit()` — line-range mode

**Files:**
- Modify: `src/markdown_vault_mcp/collection.py:2247-2318`
- Test: `tests/test_collection.py`

- [ ] **Step 1: Write failing tests for line-range mode**

In `tests/test_collection.py`, add to the `TestEdit` class:

```python
def test_edit_line_range_replaces(
    self, writable: Collection, vault_path: Path
) -> None:
    """edit() with line_start/line_end replaces the specified lines."""
    writable.write("lines.md", "line1\nline2\nline3\nline4\n")
    result = writable.edit(
        "lines.md", new_text="replaced\n", line_start=2, line_end=3
    )
    assert result.replacements == 1
    content = (vault_path / "lines.md").read_text()
    assert content == "line1\nreplaced\nline4\n"

def test_edit_line_range_single_line(
    self, writable: Collection, vault_path: Path
) -> None:
    """line_start == line_end replaces exactly one line."""
    writable.write("lines.md", "line1\nline2\nline3\n")
    writable.edit("lines.md", new_text="new2", line_start=2, line_end=2)
    content = (vault_path / "lines.md").read_text()
    assert content == "line1\nnew2\nline3\n"

def test_edit_line_range_out_of_bounds(self, writable: Collection) -> None:
    """line_end beyond file length raises ValueError."""
    writable.write("lines.md", "line1\nline2\n")
    with pytest.raises(ValueError, match="out of range"):
        writable.edit("lines.md", new_text="x", line_start=1, line_end=5)

def test_edit_line_range_inverted(self, writable: Collection) -> None:
    """line_start > line_end raises ValueError."""
    writable.write("lines.md", "line1\nline2\n")
    with pytest.raises(ValueError, match="line_start.*line_end"):
        writable.edit("lines.md", new_text="x", line_start=3, line_end=1)

def test_edit_line_range_only_one_provided(self, writable: Collection) -> None:
    """Providing only line_start without line_end raises ValueError."""
    with pytest.raises(ValueError, match="both.*line_start.*line_end"):
        writable.edit("simple.md", new_text="x", line_start=1)

def test_edit_no_old_text_no_lines(self, writable: Collection) -> None:
    """Neither old_text nor line range raises ValueError."""
    with pytest.raises(ValueError, match="old_text.*line_start"):
        writable.edit("simple.md", new_text="x")

def test_edit_line_range_zero_raises(self, writable: Collection) -> None:
    """line_start < 1 raises ValueError (1-based)."""
    with pytest.raises(ValueError, match="line_start.*>= 1"):
        writable.edit("simple.md", new_text="x", line_start=0, line_end=1)

def test_edit_line_range_updates_index(self, writable: Collection) -> None:
    """Line-range edit updates the FTS index."""
    writable.write("lines.md", "# Old Title\n\nOld body.\n")
    writable.edit(
        "lines.md", new_text="# Xylophone Title\n", line_start=1, line_end=1
    )
    results = writable.search("xylophone", mode="keyword")
    assert any(r.path == "lines.md" for r in results)

def test_edit_line_range_with_if_match(
    self, writable: Collection, vault_path: Path
) -> None:
    """Line-range edit respects if_match etag."""
    writable.write("lines.md", "line1\nline2\n")
    read_result = writable.read("lines.md")
    writable.edit(
        "lines.md",
        new_text="new1\n",
        line_start=1,
        line_end=1,
        if_match=read_result.etag,
    )
    content = (vault_path / "lines.md").read_text()
    assert content == "new1\nline2\n"

def test_edit_line_range_with_wrong_if_match(self, writable: Collection) -> None:
    """Line-range edit rejects stale etag."""
    writable.write("lines.md", "line1\nline2\n")
    with pytest.raises(ConcurrentModificationError):
        writable.edit(
            "lines.md",
            new_text="new",
            line_start=1,
            line_end=1,
            if_match="stale_hash",
        )

def test_edit_line_range_triggers_callback(self, vault_path: Path) -> None:
    """Line-range edit fires the on_write callback."""
    calls: list = []
    col = _make_collection(
        vault_path, read_only=False, on_write=lambda *args: calls.append(args)
    )
    col.build_index()
    col.write("lines.md", "line1\nline2\n")
    col.edit("lines.md", new_text="replaced\n", line_start=1, line_end=1)
    col.close()
    # write + edit = 2 callbacks
    assert len(calls) == 2
    _, _, operation = calls[1]
    assert operation == "edit"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_collection.py::TestEdit::test_edit_line_range_replaces tests/test_collection.py::TestEdit::test_edit_no_old_text_no_lines -v`
Expected: FAIL — current `edit()` requires `old_text` as a positional arg.

- [ ] **Step 3: Refactor `Collection.edit()` with line-range support**

Replace the `edit` method in `src/markdown_vault_mcp/collection.py` (lines 2247-2318) with:

```python
def edit(
    self,
    path: str,
    old_text: str | None = None,
    new_text: str = "",
    if_match: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
) -> EditResult:
    """Patch a section of a document.

    Supports three modes:

    - **Exact match** (``old_text`` only): verifies *old_text* exists
      exactly once in the full file content (including frontmatter),
      replaces it with *new_text*.
    - **Line-range** (``line_start``/``line_end`` only): replaces the
      specified line range with *new_text*.
    - **Scoped match** (both): searches for *old_text* only within the
      specified line range, allowing disambiguation of repeated text.

    When exact match fails, a normalized comparison is attempted
    (Unicode NFC, dash/quote normalization, whitespace collapsing).
    If a unique normalized match is found, it is used and
    ``match_type="normalized"`` is returned.

    Args:
        path: Relative document path.
        old_text: Text to replace. Required for exact-match and
            scoped-match modes.  Must appear exactly once (in the
            file or in the line range).
        new_text: Replacement text.
        if_match: Optional etag from a previous :meth:`read` call.
            When provided, the edit is only performed if the current
            file hash matches this value, preventing edits based on
            stale content. Pass ``None`` (default) to skip the check.
        line_start: First line to replace (1-based, inclusive).
            Must be provided together with *line_end*.
        line_end: Last line to replace (1-based, inclusive).
            Must be provided together with *line_start*.

    Returns:
        :class:`~markdown_vault_mcp.types.EditResult`.

    Raises:
        ReadOnlyError: If the collection is read-only.
        DocumentNotFoundError: If the file does not exist.
        ConcurrentModificationError: If *if_match* is provided and does
            not match the current file hash.
        EditConflictError: If *old_text* is not found or appears
            more than once.
        ValueError: If parameter combination is invalid, or line
            numbers are out of range.
    """
    self._check_writable()

    # --- Parameter validation ---
    has_lines = line_start is not None or line_end is not None
    if not old_text and not has_lines:
        raise ValueError(
            "Must provide old_text, line_start/line_end, or both"
        )
    if (line_start is None) != (line_end is None):
        raise ValueError(
            "Must provide both line_start and line_end, not just one"
        )
    if line_start is not None and line_end is not None:
        if line_start < 1:
            raise ValueError("line_start must be >= 1 (lines are 1-based)")
        if line_start > line_end:
            raise ValueError(
                f"line_start ({line_start}) must be <= line_end ({line_end})"
            )

    with self._write_lock:
        self._ensure_initialized()

        abs_path = self._validate_path(path)
        if not abs_path.is_file():
            raise DocumentNotFoundError(f"Document not found: {path}")

        if if_match is not None:
            current_hash = compute_file_hash(abs_path)
            if current_hash != if_match:
                raise ConcurrentModificationError(
                    path, expected=if_match, actual=current_hash
                )

        file_content = abs_path.read_text(encoding="utf-8")

        if has_lines:
            assert line_start is not None and line_end is not None
            new_content, match_type = self._edit_with_lines(
                file_content, old_text, new_text, line_start, line_end, path
            )
        else:
            assert old_text is not None
            new_content, match_type = self._edit_with_text(
                file_content, old_text, new_text, path
            )

        abs_path.write_text(new_content, encoding="utf-8")

        # Update FTS index.
        note = parse_note(abs_path, self._source_dir, self._chunk_strategy)
        self._fts.upsert_note(note)

        # Mark for deferred embedding update.
        self._update_vector_index(note)

    # Fire git callback in background thread.
    self._fire_write_callback(abs_path, new_content, "edit")

    return EditResult(path=path, replacements=1, match_type=match_type)

def _edit_with_lines(
    self,
    file_content: str,
    old_text: str | None,
    new_text: str,
    line_start: int,
    line_end: int,
    path: str,
) -> tuple[str, str]:
    """Handle line-range and scoped-match edit modes.

    Returns:
        Tuple of (new_file_content, match_type).
    """
    lines = file_content.split("\n")
    # The split produces an extra empty string after a trailing newline.
    # Total addressable lines = len(lines) if last is non-empty, else
    # len(lines) - 1 (the trailing empty element isn't a real line).
    total_lines = len(lines) - 1 if lines and lines[-1] == "" else len(lines)
    if line_end > total_lines:
        raise ValueError(
            f"line_end ({line_end}) out of range "
            f"(file has {total_lines} lines)"
        )

    # Convert to 0-based indices for slicing.
    start_idx = line_start - 1
    end_idx = line_end  # exclusive for slice

    if old_text is not None:
        # Scoped match: search within the line range only.
        scope = "\n".join(lines[start_idx:end_idx])
        new_scope, match_type = self._match_and_replace(
            scope, old_text, new_text, path
        )
        lines[start_idx:end_idx] = new_scope.split("\n")
    else:
        # Pure line-range replacement.
        match_type = "exact"
        # Reconstruct: new_text replaces lines, preserving structure.
        # Strip trailing newline from new_text if present to avoid
        # double-newline when rejoining.
        replacement_lines = new_text.rstrip("\n").split("\n") if new_text else [""]
        lines[start_idx:end_idx] = replacement_lines

    return "\n".join(lines), match_type

def _edit_with_text(
    self,
    file_content: str,
    old_text: str,
    new_text: str,
    path: str,
) -> tuple[str, str]:
    """Handle exact-match edit mode (with normalized fallback).

    Returns:
        Tuple of (new_file_content, match_type).
    """
    new_content, match_type = self._match_and_replace(
        file_content, old_text, new_text, path
    )
    return new_content, match_type

def _match_and_replace(
    self,
    content: str,
    old_text: str,
    new_text: str,
    path: str,
) -> tuple[str, str]:
    """Try exact match, then normalized match, then raise with diagnostics.

    Returns:
        Tuple of (new_content, match_type).
    """
    count = content.count(old_text)

    if count == 1:
        return content.replace(old_text, new_text, 1), "exact"

    if count > 1:
        raise EditConflictError(
            f"old_text appears {count} times in {path}; "
            f"must appear exactly once"
        )

    # count == 0: try normalized matching.
    normalized_content = _normalize_text(content)
    normalized_old = _normalize_text(old_text)
    norm_count = normalized_content.count(normalized_old)

    if norm_count == 1:
        pos_map = _build_position_map(content, normalized_content)
        norm_start = normalized_content.index(normalized_old)
        norm_end = norm_start + len(normalized_old)
        orig_start = pos_map[norm_start]
        orig_end = (
            pos_map[norm_end - 1] + 1
            if norm_end <= len(pos_map)
            else len(content)
        )
        new_content = content[:orig_start] + new_text + content[orig_end:]
        return new_content, "normalized"

    if norm_count > 1:
        raise EditConflictError(
            f"old_text appears {norm_count} times in {path} after "
            f"normalization; must appear exactly once"
        )

    # norm_count == 0: raise with diagnostics.
    diag = _find_closest_match(old_text, content)
    raise EditConflictError(
        f"old_text not found in {path}", **diag
    )
```

- [ ] **Step 4: Run line-range tests to verify they pass**

Run: `uv run python -m pytest tests/test_collection.py::TestEdit -v -k "line_range or no_old_text_no_lines"`
Expected: All PASS

- [ ] **Step 5: Run full TestEdit suite for regressions**

Run: `uv run python -m pytest tests/test_collection.py::TestEdit -v`
Expected: All PASS. Existing tests use positional `old_text` which still works.

- [ ] **Step 6: Commit**

```bash
git add src/markdown_vault_mcp/collection.py tests/test_collection.py
git commit -m "feat(edit): add line-range edit mode to Collection.edit() (#325)"
```

---

### Task 6: Add scoped match and normalized match tests

**Files:**
- Test: `tests/test_collection.py`

- [ ] **Step 1: Write scoped match tests**

In `tests/test_collection.py`, add to `TestEdit`:

```python
def test_edit_scoped_match(
    self, writable: Collection, vault_path: Path
) -> None:
    """old_text + line range disambiguates repeated text."""
    writable.write("repeated.md", "hello\nworld\nhello\n")
    # "hello" appears twice, but only once in lines 1-1.
    result = writable.edit(
        "repeated.md", old_text="hello", new_text="goodbye",
        line_start=1, line_end=1,
    )
    assert result.replacements == 1
    content = (vault_path / "repeated.md").read_text()
    assert content == "goodbye\nworld\nhello\n"

def test_edit_scoped_match_not_found(self, writable: Collection) -> None:
    """old_text not in the specified line range raises EditConflictError."""
    writable.write("scoped.md", "aaa\nbbb\nccc\n")
    with pytest.raises(EditConflictError, match="not found"):
        writable.edit(
            "scoped.md", old_text="ccc", new_text="ddd",
            line_start=1, line_end=2,
        )
```

- [ ] **Step 2: Write normalized match tests**

In `tests/test_collection.py`, add to `TestEdit`:

```python
def test_edit_normalized_dashes(
    self, writable: Collection, vault_path: Path
) -> None:
    """Normalized match handles em-dash vs hyphen."""
    writable.write("dashes.md", "hello \u2014 world\n")
    result = writable.edit("dashes.md", old_text="hello - world", new_text="goodbye")
    assert result.match_type == "normalized"
    content = (vault_path / "dashes.md").read_text()
    assert content == "goodbye\n"

def test_edit_normalized_quotes(
    self, writable: Collection, vault_path: Path
) -> None:
    """Normalized match handles smart quotes vs straight."""
    writable.write("quotes.md", "\u201chello\u201d\n")
    result = writable.edit("quotes.md", old_text='"hello"', new_text="goodbye")
    assert result.match_type == "normalized"
    content = (vault_path / "quotes.md").read_text()
    assert content == "goodbye\n"

def test_edit_normalized_whitespace(
    self, writable: Collection, vault_path: Path
) -> None:
    """Normalized match handles collapsed whitespace."""
    writable.write("ws.md", "hello   world\n")
    result = writable.edit("ws.md", old_text="hello world", new_text="goodbye")
    assert result.match_type == "normalized"
    content = (vault_path / "ws.md").read_text()
    assert content == "goodbye\n"

def test_edit_normalized_trailing_ws(
    self, writable: Collection, vault_path: Path
) -> None:
    """Normalized match handles trailing whitespace difference."""
    writable.write("trail.md", "hello   \nworld\n")
    result = writable.edit("trail.md", old_text="hello\nworld", new_text="goodbye")
    assert result.match_type == "normalized"
    content = (vault_path / "trail.md").read_text()
    assert content == "goodbye\n"

def test_edit_normalized_unicode(
    self, writable: Collection, vault_path: Path
) -> None:
    """Normalized match handles NFC decomposed vs composed."""
    # File has decomposed é (e + combining acute)
    writable.write("unicode.md", "caf\u0065\u0301\n")
    # old_text has composed é
    result = writable.edit("unicode.md", old_text="caf\u00e9", new_text="tea")
    assert result.match_type == "normalized"
    content = (vault_path / "unicode.md").read_text()
    assert content == "tea\n"

def test_edit_normalized_returns_match_type(
    self, writable: Collection
) -> None:
    """Normalized match returns match_type='normalized' in EditResult."""
    writable.write("norm.md", "a\u2014b\n")
    result = writable.edit("norm.md", old_text="a-b", new_text="c")
    assert result.match_type == "normalized"

def test_edit_normalized_multiple_raises(self, writable: Collection) -> None:
    """Normalized match with >1 occurrences raises EditConflictError."""
    writable.write("multi.md", "a\u2014b and a\u2014b\n")
    with pytest.raises(EditConflictError, match="after normalization"):
        writable.edit("multi.md", old_text="a-b", new_text="c")

def test_edit_exact_preferred_over_normalized(
    self, writable: Collection
) -> None:
    """Exact match is used even when normalized would also work."""
    writable.write("exact.md", "a-b\n")
    result = writable.edit("exact.md", old_text="a-b", new_text="c")
    assert result.match_type == "exact"

def test_edit_normalized_preserves_original_bytes(
    self, writable: Collection, vault_path: Path
) -> None:
    """Normalized replacement preserves original bytes outside the match."""
    # File has smart quotes + em-dash in OTHER parts.
    writable.write(
        "preserve.md",
        "\u201cintro\u201d\nhello   world\n\u201coutro\u201d\n"
    )
    writable.edit(
        "preserve.md", old_text="hello world", new_text="goodbye"
    )
    content = (vault_path / "preserve.md").read_text()
    # Smart quotes in intro/outro must be preserved.
    assert content == "\u201cintro\u201d\ngoodbye\n\u201coutro\u201d\n"

def test_edit_normalized_within_line_range(
    self, writable: Collection, vault_path: Path
) -> None:
    """Normalized match works within a scoped line range."""
    writable.write("scoped_norm.md", "aaa\nhello\u2014world\nccc\n")
    result = writable.edit(
        "scoped_norm.md", old_text="hello-world", new_text="goodbye",
        line_start=2, line_end=2,
    )
    assert result.match_type == "normalized"
    content = (vault_path / "scoped_norm.md").read_text()
    assert content == "aaa\ngoodbye\nccc\n"
```

- [ ] **Step 3: Write diagnostic error tests**

In `tests/test_collection.py`, add to `TestEdit`:

```python
def test_edit_diagnostic_closest_line(self, writable: Collection) -> None:
    """Failed match includes closest_match_line in error."""
    writable.write("diag.md", "line one\nthe quick brown fox\nline three\n")
    with pytest.raises(EditConflictError) as exc_info:
        writable.edit("diag.md", old_text="the quick brown fax", new_text="x")
    assert exc_info.value.closest_match_line == 2

def test_edit_diagnostic_diff_snippet(self, writable: Collection) -> None:
    """Failed match includes expected/found snippets."""
    writable.write("diag2.md", "the quick-brown fox\n")
    with pytest.raises(EditConflictError) as exc_info:
        writable.edit(
            "diag2.md", old_text="the quick\u2014brown fox", new_text="x"
        )
    err = exc_info.value
    assert err.expected_snippet is not None
    assert err.found_snippet is not None

def test_edit_diagnostic_no_close_match(self, writable: Collection) -> None:
    """No diagnostics when nothing is remotely close."""
    writable.write("diag3.md", "aaaa\nbbbb\ncccc\n")
    with pytest.raises(EditConflictError) as exc_info:
        writable.edit("diag3.md", old_text="xyz123 completely different", new_text="x")
    err = exc_info.value
    assert err.closest_match_line is None
```

- [ ] **Step 4: Run all new tests**

Run: `uv run python -m pytest tests/test_collection.py::TestEdit -v`
Expected: All PASS

- [ ] **Step 5: Run full collection test suite**

Run: `uv run python -m pytest tests/test_collection.py -x -q`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_collection.py
git commit -m "test(edit): add scoped, normalized, and diagnostic edit tests (#325)"
```

---

### Task 7: Update MCP tool layer

**Files:**
- Modify: `src/markdown_vault_mcp/_server_tools.py:859-892`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing MCP tests**

In `tests/test_mcp_server.py`, add to `TestEditTool`:

```python
@pytest.mark.usefixtures("_mcp_env_writable")
async def test_edit_line_range(self) -> None:
    """MCP edit tool accepts line_start/line_end."""
    server = create_server()
    async with Client(server) as client:
        await client.call_tool(
            "write",
            {"path": "lines.md", "content": "line1\nline2\nline3\n"},
        )
        result = await client.call_tool(
            "edit",
            {
                "path": "lines.md",
                "new_text": "replaced\n",
                "line_start": 2,
                "line_end": 2,
            },
        )
    data = result.data
    assert data["path"] == "lines.md"
    assert data["replacements"] == 1

@pytest.mark.usefixtures("_mcp_env_writable")
async def test_edit_normalized_match(self) -> None:
    """MCP edit response includes match_type."""
    server = create_server()
    async with Client(server) as client:
        await client.call_tool(
            "write",
            {"path": "norm.md", "content": "hello \u2014 world\n"},
        )
        result = await client.call_tool(
            "edit",
            {
                "path": "norm.md",
                "old_text": "hello - world",
                "new_text": "goodbye",
            },
        )
    data = result.data
    assert data["match_type"] == "normalized"

@pytest.mark.usefixtures("_mcp_env_writable")
async def test_edit_diagnostic_error(self) -> None:
    """MCP edit error includes diagnostic info."""
    server = create_server()
    async with Client(server) as client:
        await client.call_tool(
            "write",
            {"path": "diag.md", "content": "the quick brown fox\n"},
        )
        result = await client.call_tool_mcp(
            "edit",
            {
                "path": "diag.md",
                "old_text": "the quick brown fax",
                "new_text": "x",
            },
        )
    assert result.isError is True
    # The error text should contain diagnostic info.
    from mcp import types as mcp_types

    error_text = cast(mcp_types.TextContent, result.content[0]).text
    assert "closest_match_line" in error_text or "line 1" in error_text.lower()
```

Add `cast` import if not present at the top of the test file:

```python
from typing import cast
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_mcp_server.py::TestEditTool::test_edit_line_range tests/test_mcp_server.py::TestEditTool::test_edit_normalized_match tests/test_mcp_server.py::TestEditTool::test_edit_diagnostic_error -v`
Expected: FAIL — current MCP tool doesn't accept `line_start`/`line_end`.

- [ ] **Step 3: Update the MCP edit tool**

In `src/markdown_vault_mcp/_server_tools.py`, replace the `edit` function (lines 859-892):

```python
async def edit(
    path: str,
    old_text: str | None = None,
    new_text: str = "",
    if_match: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
    collection: Collection = Depends(get_collection),
) -> dict[str, Any]:
    """Make a targeted text replacement in an existing .md note (not supported for attachments).

    Three edit modes:
    - **Exact match** (old_text only): pass a portion of the file as
      old_text — must appear exactly once. Frontmatter can be edited.
    - **Line-range** (line_start + line_end, no old_text): replace the
      specified lines with new_text. Lines are 1-based (matching
      'read' output). Recommended: pass if_match for safety.
    - **Scoped match** (old_text + line_start/line_end): search for
      old_text within the line range only — useful when old_text
      appears multiple times in the file.

    When exact match fails, a normalized comparison is attempted
    (Unicode NFC, dash/quote normalization, whitespace collapsing).
    If a unique normalized match is found, it is used and
    match_type='normalized' is returned.

    Always call 'read' first to get the current text and line numbers.
    The search index is updated immediately; do not call 'reindex'.

    Args:
        path: Relative path to the document.
        old_text: Text to replace. Must appear exactly once in the
            document or line range. Get this via 'read'. Optional
            when using line-range mode.
        new_text: Replacement text. May be longer or shorter.
        if_match: Optional etag obtained from a previous 'read' call.
            When provided, the edit only proceeds if the file has not
            been modified since that read (optimistic concurrency).
        line_start: First line to replace (1-based, inclusive).
            Must be provided together with line_end.
        line_end: Last line to replace (1-based, inclusive).
            Must be provided together with line_start.

    Returns:
        - **path** (str): path of the edited document.
        - **replacements** (int): always 1.
        - **match_type** (str): ``'exact'`` or ``'normalized'``.

    Raises:
        ValueError: If parameter combination is invalid, or line
            numbers are out of range.
        EditConflictError: If old_text is not found or appears more
            than once.
    """
    try:
        result = await asyncio.to_thread(
            collection.edit,
            path,
            old_text=old_text,
            new_text=new_text,
            if_match=if_match,
            line_start=line_start,
            line_end=line_end,
        )
        return asdict(result)
    except EditConflictError as exc:
        parts = [str(exc)]
        if exc.closest_match_line is not None:
            parts.append(f"closest_match_line: {exc.closest_match_line}")
        if exc.first_diff_char is not None:
            parts.append(f"first_diff_at_char: {exc.first_diff_char}")
        if exc.expected_snippet is not None:
            parts.append(f"expected: {exc.expected_snippet!r}")
        if exc.found_snippet is not None:
            parts.append(f"found: {exc.found_snippet!r}")
        raise ToolError("\n".join(parts)) from exc
```

Add the imports at the top of the file:

```python
from fastmcp.exceptions import ToolError
from markdown_vault_mcp.exceptions import EditConflictError
```

- [ ] **Step 4: Run MCP tests to verify they pass**

Run: `uv run python -m pytest tests/test_mcp_server.py::TestEditTool -v`
Expected: All PASS

- [ ] **Step 5: Run full MCP test suite**

Run: `uv run python -m pytest tests/test_mcp_server.py -x -q`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/markdown_vault_mcp/_server_tools.py tests/test_mcp_server.py
git commit -m "feat(edit): update MCP edit tool with line-range, normalized match, diagnostics (#325)"
```

---

### Task 8: Update existing tests for backwards compatibility

**Files:**
- Modify: `tests/test_collection.py`

- [ ] **Step 1: Check that existing `test_edit_empty_old_text_raises` still works**

The existing test calls `writable.edit("simple.md", "", "new")`. With the new signature, `old_text=""` is falsy, so the validation logic must treat empty string the same as `None` for the "must not be empty" check. Verify the existing validation:

In `collection.py`, the `_match_and_replace` method will be called with `old_text=""`. We need to make sure empty-string `old_text` is still rejected. Check that the `edit()` method validates this before reaching `_match_and_replace`:

The current flow: `edit()` checks `if not old_text and not has_lines: raise ValueError`. But `old_text=""` is falsy AND we have no lines, so it raises the *wrong* error message ("Must provide old_text, line_start/line_end, or both" instead of "old_text must not be empty").

We need to handle this: if `old_text` is explicitly passed as `""`, raise the specific "old_text must not be empty" error.

- [ ] **Step 2: Fix the validation logic**

In `collection.py`, in the `edit()` method, add before the existing parameter validation block:

```python
if old_text is not None and not old_text:
    raise ValueError("old_text must not be empty")
```

And adjust the subsequent check:

```python
if old_text is None and not has_lines:
    raise ValueError(
        "Must provide old_text, line_start/line_end, or both"
    )
```

- [ ] **Step 3: Run existing edit tests**

Run: `uv run python -m pytest tests/test_collection.py::TestEdit -v`
Expected: All PASS including `test_edit_empty_old_text_raises`

- [ ] **Step 4: Run the full test suite**

Run: `uv run python -m pytest tests/test_collection.py tests/test_mcp_server.py -x -q`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/markdown_vault_mcp/collection.py
git commit -m "fix(edit): preserve empty old_text validation in refactored edit (#325)"
```

---

### Task 9: Update design doc

**Files:**
- Modify: `docs/design.md`

- [ ] **Step 1: Update the `edit()` spec in design.md**

Find the edit-related sections and update them. The key sections to update:

**Collection API signature** (around line 789):

```python
def edit(self, path: str, old_text: str | None = None,
         new_text: str = "", if_match: str | None = None,
         line_start: int | None = None,
         line_end: int | None = None) -> EditResult: ...
```

**EditResult dataclass** (around line 504):

```python
@dataclass
class EditResult:
    """Result of an edit operation."""
    path: str
    replacements: int                 # always 1 (enforced by edit semantics)
    match_type: str = "exact"         # "exact" or "normalized"
```

**`edit()` behavior** (around line 837): Replace the existing paragraph with:

```
**`edit()` behavior**: supports three modes: (1) exact match — reads file,
verifies `old_text` exists exactly once, replaces with `new_text`; (2) line-range
— replaces lines `line_start..line_end` (1-based, inclusive) with `new_text`;
(3) scoped match — searches for `old_text` within the specified line range only.

When exact match fails (count == 0), a normalized comparison is attempted:
Unicode NFC, en-dash/em-dash → hyphen, smart quotes → straight quotes,
whitespace collapse within lines, trailing whitespace stripping. If exactly
one normalized match is found, the original byte range is replaced and
`match_type="normalized"` is returned. Raises `DocumentNotFoundError`
if the file does not exist. Raises `EditConflictError` if `old_text` is
not found (after both exact and normalized matching) or appears more than
once. When both exact and normalized match fail, `EditConflictError`
includes diagnostic fields: `closest_match_line`, `first_diff_char`,
`expected_snippet`, `found_snippet`.
```

**Exceptions table** (around line 270): Add a note about `EditConflictError` diagnostic fields:

```
| `EditConflictError` | `edit()` | `old_text` not found or appears more than once. Includes optional diagnostic fields: `closest_match_line`, `first_diff_char`, `expected_snippet`, `found_snippet` |
```

**Tool surface table** (around line 998): Update the edit row description if needed.

- [ ] **Step 2: Commit**

```bash
git add docs/design.md
git commit -m "docs: update design.md with edit tool improvements (#325)"
```

---

### Task 10: Update user-facing documentation

**Files:**
- Modify: `docs/tools/index.md`
- Modify: `README.md`

- [ ] **Step 1: Update `docs/tools/index.md` edit section**

Replace the `### edit` section (around line 226-241) with:

```markdown
### `edit`

Make a targeted text replacement in an existing document. Supports three modes:

- **Exact match** (`old_text` only) — must appear exactly once in the document.
- **Line-range** (`line_start` + `line_end`, no `old_text`) — replaces the specified lines. Pass `if_match` for safety.
- **Scoped match** (`old_text` + `line_start`/`line_end`) — searches for `old_text` within the specified line range only.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Relative path to the document |
| `old_text` | string | Conditional | Text to replace. Required unless using line-range mode |
| `new_text` | string | Yes | Replacement text |
| `if_match` | string | No | Etag from `read` for optimistic concurrency |
| `line_start` | integer | Conditional | First line to replace (1-based, inclusive). Required with `line_end` |
| `line_end` | integer | Conditional | Last line to replace (1-based, inclusive). Required with `line_start` |

**Returns:** `{"path": "Journal/note.md", "replacements": 1, "match_type": "exact"}`

`match_type` is `"exact"` when the text matched byte-for-byte, or `"normalized"` when it matched after Unicode/whitespace normalization.

!!! tip "Usage pattern"
    Always call `read` first to get the exact current text and line numbers. For small edits, use `old_text` (exact match). For large block replacements, use `line_start`/`line_end` with the line numbers shown by `read`. Frontmatter can be edited — `old_text` may span the YAML block.

!!! info "Normalized matching"
    When exact match fails, the tool automatically tries a normalized comparison: Unicode NFC, dash normalization (en-dash/em-dash → hyphen), smart quote normalization, whitespace collapsing. If a unique match is found, it proceeds and returns `match_type: "normalized"`.

!!! warning "Diagnostic errors"
    When no match is found, the error message includes diagnostic info: the closest matching line number, the character position of the first difference, and short snippets showing what was expected vs. what was found. This helps identify the exact mismatch.
```

- [ ] **Step 2: Update `README.md` edit tool row**

Find the edit row in the tools table (around line 298) and update:

```markdown
| `edit` | Replace text in a document — exact match, line-range, or scoped match with normalized fallback |
```

- [ ] **Step 3: Verify no guide pages need updating**

Check `docs/guides/zettelkasten.md` — the `collection.edit()` calls there use the existing exact-match API which still works. No changes needed.

- [ ] **Step 4: Commit**

```bash
git add docs/tools/index.md README.md
git commit -m "docs: update README and tools docs with edit improvements (#325)"
```

---

### Task 11: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run python -m pytest tests/test_collection.py tests/test_mcp_server.py -x -q`
Expected: All PASS

- [ ] **Step 2: Check coverage**

Run: `uv run python -m pytest tests/ -q --cov=markdown_vault_mcp --cov-report=term-missing --ignore=tests/test_mcp_apps_browser.py --ignore=tests/test_mcp_apps_context.py --ignore=tests/test_mcp_apps_foundation.py --ignore=tests/test_mcp_apps_graph.py 2>/dev/null | tail -5`
Expected: Total coverage ≥ 89%

- [ ] **Step 3: Run linting**

Run: `uv run ruff check src/markdown_vault_mcp/ tests/`
Expected: No errors

Run: `uv run ruff format --check src/markdown_vault_mcp/ tests/`
Expected: No formatting issues

- [ ] **Step 4: Run mypy**

Run: `uv run mypy src/markdown_vault_mcp/`
Expected: No errors
