# Edit Tool Improvements: Line-Range, Normalized Match, and Diagnostics

## Problem

The `edit()` tool requires an exact byte-for-byte match of `old_text` against file content. When an LLM uses the tool, the text makes a round-trip through: file → MCP JSON response → LLM context window → LLM output → MCP JSON request → string comparison. Any transformation anywhere in that chain breaks the match.

Three failure modes compound:

1. **Large block replacements** — the LLM tries to replace a 20+ line section and one character is off somewhere in the middle.
2. **Unicode/whitespace normalization** — invisible differences (en-dash vs hyphen, smart quotes, trailing whitespace) cause silent mismatches.
3. **Poor error diagnostics** — when the match fails, the error gives no clue *why* or *where* the mismatch is, so the LLM retries blindly.

## Solution

Three complementary improvements, all backwards-compatible with the existing API.

## 1. API Surface

### Collection.edit() signature

```python
def edit(
    self,
    path: str,
    old_text: str | None = None,    # was required, now optional
    new_text: str = "",
    if_match: str | None = None,
    line_start: int | None = None,   # 1-based, inclusive
    line_end: int | None = None,     # 1-based, inclusive
) -> EditResult:
```

### Three edit modes

| Mode | Parameters | Safety | Use case |
|------|-----------|--------|----------|
| **Exact match** (existing) | `old_text` only | Highest — must match once | Small, precise edits |
| **Line-range** | `line_start` + `line_end` (no `old_text`) | Medium — etag recommended | Large block replacements |
| **Both** | `old_text` + `line_start`/`line_end` | Highest — scoped exact match | Disambiguating repeated text |

### Validation rules

- Must provide `old_text` or `line_start`/`line_end` (or both) — `ValueError` if neither.
- `line_start`/`line_end` must both be present if either is — `ValueError` if only one.
- `line_start` must be ≤ `line_end` — `ValueError` otherwise.
- Lines are 1-based to match `read` output.
- Out-of-range lines raise `ValueError` (not silently clamped).
- `line_start` < 1 raises `ValueError`.

### Scoped match (both parameters)

When both `old_text` and `line_start`/`line_end` are provided, extract lines `line_start..line_end`, search for `old_text` within that slice only. This handles the case where `old_text` appears multiple times in the file but only once in the target range.

### MCP tool signature

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
```

## 2. Normalized Matching

When exact `old_text` match fails (count == 0), a normalization fallback kicks in before raising `EditConflictError`.

### Normalization steps

Applied to both `old_text` and file content for comparison only — the actual replacement uses original file bytes:

1. **Unicode NFC** — `unicodedata.normalize("NFC", text)`
2. **Normalize dashes** — en-dash `–` (U+2013), em-dash `—` (U+2014) → hyphen `-`
3. **Normalize quotes** — `""` (U+201C, U+201D) → `"` and `''` (U+2018, U+2019) → `'`
4. **Collapse whitespace runs** — multiple spaces/tabs → single space (within lines only, not across newlines)
5. **Strip trailing whitespace** per line

### Matching logic

```
exact_count = file_content.count(old_text)
if exact_count == 1:  → proceed (existing behavior)
if exact_count > 1:   → error (existing behavior)
if exact_count == 0:
    normalized_file = normalize(file_content)
    normalized_old  = normalize(old_text)
    norm_count = count occurrences in normalized form
    if norm_count == 1:
        → find the original byte range via position mapping
        → replace that original range with new_text
        → return EditResult with match_type="normalized"
    if norm_count == 0:  → error (with diagnostics)
    if norm_count > 1:   → error "old_text appears N times after normalization"
```

### Reverse-mapping

Build a position map: for each character in the normalized string, track its corresponding index in the original. When a normalized match is found at `[i:j]`, look up `orig_start = pos_map[i]` and `orig_end = pos_map[j-1] + 1`. Replace `file_content[orig_start:orig_end]` with `new_text`.

This preserves the original file's whitespace and Unicode everywhere except the replaced span.

### Interaction with line-range

When both `old_text` and `line_start`/`line_end` are provided: if exact match within the line range fails, try normalized match within the line range.

### EditResult change

```python
@dataclass
class EditResult:
    path: str
    replacements: int
    match_type: str = "exact"  # "exact" or "normalized"
```

## 3. Error Diagnostics

When both exact and normalized matching fail (count == 0), the error includes diagnostic information.

### EditConflictError changes

```python
class EditConflictError(MarkdownMCPError):
    def __init__(
        self,
        message: str,
        *,
        closest_match_line: int | None = None,
        first_diff_char: int | None = None,
        expected_snippet: str | None = None,
        found_snippet: str | None = None,
    ):
        super().__init__(message)
        self.closest_match_line = closest_match_line
        self.first_diff_char = first_diff_char
        self.expected_snippet = expected_snippet
        self.found_snippet = found_snippet
```

### Finding the closest match

1. Take the first line of `old_text` and search for the best fuzzy match in the file using `difflib.SequenceMatcher`.
2. If a match with ratio ≥ 0.6 is found, report its line number.
3. Extract a short snippet (±30 chars) around the first character-level difference.

### MCP error response

```json
{
  "error": "old_text not found in notes/foo.md",
  "closest_match_line": 87,
  "first_diff_at_char": 42,
  "expected": "...the quick—brown fox...",
  "found": "...the quick-brown fox..."
}
```

The `_server_tools.py` edit wrapper catches `EditConflictError` and surfaces diagnostic fields in the error dict.

For the "appears more than once" case, no diagnostics are added — the error message already says how many times it appeared.

## Files Modified

| File | Changes |
|------|---------|
| `src/markdown_vault_mcp/types.py` | Add `match_type: str = "exact"` to `EditResult` |
| `src/markdown_vault_mcp/exceptions.py` | Add diagnostic fields to `EditConflictError` |
| `src/markdown_vault_mcp/collection.py` | Refactor `edit()` with three modes + normalization + diagnostics |
| `src/markdown_vault_mcp/_server_tools.py` | Add `line_start`/`line_end` params, surface diagnostics in error |
| `docs/design.md` | Update edit spec with new modes |
| `tests/test_collection.py` | ~24 new collection-level tests |
| `tests/test_mcp_server.py` | ~6 new MCP-level tests |
| `README.md` | Update edit tool description with new parameters |
| `docs/tools/index.md` | Document line-range mode, normalized matching, diagnostic errors |
| `docs/guides/*.md` | Update any guides referencing the edit tool |

## New Private Helpers (collection.py)

- `_normalize_text(text: str) -> str` — applies the 5 normalization steps.
- `_build_position_map(original: str, normalized: str) -> list[int]` — maps normalized char indices to original char indices.
- `_find_closest_match(old_text: str, file_content: str) -> dict` — fuzzy match diagnostics using `difflib.SequenceMatcher`.

## Dependencies

No new dependencies. Uses only `unicodedata`, `re`, `difflib.SequenceMatcher` (all stdlib).

## Testing

~30 new tests targeting ≥89% overall coverage.

### Collection-level tests

| Test | Mode |
|------|------|
| `test_edit_line_range_replaces` | line-range |
| `test_edit_line_range_single_line` | line-range |
| `test_edit_line_range_out_of_bounds` | line-range |
| `test_edit_line_range_inverted` | line-range |
| `test_edit_line_range_only_one_provided` | line-range |
| `test_edit_line_range_no_old_text_no_lines` | validation |
| `test_edit_line_range_updates_index` | line-range |
| `test_edit_line_range_with_if_match` | line-range |
| `test_edit_line_range_triggers_callback` | line-range |
| `test_edit_line_range_with_wrong_if_match` | line-range |
| `test_edit_line_range_zero_raises` | line-range |
| `test_edit_scoped_match` | both |
| `test_edit_scoped_match_not_found` | both |
| `test_edit_normalized_unicode` | normalized |
| `test_edit_normalized_dashes` | normalized |
| `test_edit_normalized_quotes` | normalized |
| `test_edit_normalized_whitespace` | normalized |
| `test_edit_normalized_trailing_ws` | normalized |
| `test_edit_normalized_returns_match_type` | normalized |
| `test_edit_normalized_multiple_raises` | normalized |
| `test_edit_exact_preferred_over_normalized` | normalized |
| `test_edit_normalized_preserves_original_bytes` | normalized |
| `test_edit_normalized_within_line_range` | normalized + line-range |
| `test_edit_diagnostic_closest_line` | diagnostics |
| `test_edit_diagnostic_diff_snippet` | diagnostics |
| `test_edit_diagnostic_no_close_match` | diagnostics |
| `test_edit_match_type_exact_default` | existing behavior |

### MCP-level tests

| Test | What it verifies |
|------|------------------|
| `test_edit_line_range` | MCP tool accepts line_start/line_end |
| `test_edit_normalized_match` | MCP response includes match_type |
| `test_edit_diagnostic_error` | MCP error includes diagnostic fields |
