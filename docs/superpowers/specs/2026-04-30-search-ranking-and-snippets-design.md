# Search ranking and snippet truncation — design

**Date:** 2026-04-30
**Status:** Approved (brainstorming complete; awaiting implementation plan)

## Problem statement

Two distinct retrieval pathologies were observed when a long synthesising essay (a 14-section, ~12000-word multilingual etymology lexicon) was added to a vault alongside many shorter atomic concept notes:

1. **Document concentration.** A hybrid search for `"se-cura etymology security without care"` returned the essay in five of the top ten slots (sections XIV, intro, I, VIII, Caveats), crowding out other relevant material. Section XIV (summary) outranked section I (the original exposition) because XIV repeats key terms more densely.
2. **Payload variance.** The `search` tool returns the full matching chunk as `content`. Chunk size varies wildly (200–1500 words) because chunking happens at H1/H2 boundaries; consumer context cost per result is unpredictable.

A diagnostic pure-semantic search for `"se-cura"` did not surface the essay at all in the top 10 — embedding signal for the hyphenated Latin compound was weak in isolation. Score distribution was narrow (0.62–0.64). Top hits included false positives (`Restic backup` at 0.638; `NIS2 Directive` at 0.620). This is a separate signal-quality issue that this design does not directly attack.

## Goals

1. **Cap document concentration in result lists.** No single document occupies more than `chunks_per_doc` slots in any search result, regardless of mode (keyword / semantic / hybrid). Default cap: 2.
2. **Downweight chunks of long documents during ranking.** Apply a single tunable factor (`length_downweight_alpha`, default 0.25) to each chunk's score, per channel, before fusion. Long docs slide down; short focused notes rise.
3. **Bound result payload size.** Truncate `SearchResult.content` to a query-relevant window of approximately `snippet_words` words (default 200). Full chunk recovery available via `read(path, section=...)`.
4. **Reduce within-doc chunk-size variance via adaptive heading-level chunking.** Chunker recursively descends from H1 → H2 → … → H6 when a chunk exceeds `max_chunk_words` (default 400). Pairs naturally with goals 1–3: chunk count rises for big docs, length downweight strengthens automatically, snippets operate on already-uniform chunks.
5. **Behave identically across keyword, semantic, and hybrid modes** for user-visible knobs (cap, snippet truncation). Length downweight is rank-mode-specific in mechanism but uniform in effect.
6. **No SearchResult shape break.** Same field names and types — the `content` field simply contains less text by default. Existing consumers continue to work; opt back into full chunks with `snippet_words=0`.

## Non-goals

1. **No frontmatter-based ranking.** The MCP must not require, recommend, or special-case any frontmatter convention on vault content (no `kind`, no `noindex`, no `boost`). Vault organisation is the user's choice; the server treats all `.md` files structurally identically. Rationale: a generic-purpose markdown MCP cannot impose a content-modelling discipline on the user. This forecloses the option permanently, not just for this PR.
2. **No re-embedding at search time.** Snippet selection for semantic-only hits uses cheap word-window heuristics, not per-result chunk re-embedding.
3. **No paragraph-level or fixed-window chunking.** Splitting follows existing heading structure adaptively. No sliding-window overlap, no sentence splitting, no content-blind size caps. A single 5000-word prose block with no sub-headings stays one chunk; snippet truncation handles the read-time payload.
4. **No new search modes.** No "diversity-aware" mode, no "essay-mode-on/off". The same tools, with three new knobs (plus the chunker threshold).

## Pipeline overview

```
                 ┌─ keyword channel ────────────────────────┐
                 │  FTS5 BM25 search (widened candidates)   │
                 │  → length downweight per chunk (D1)      │
                 │  → re-rank within channel                │
                 └──────────────────────────────────────────┘
query, mode  →                                                  → fuse →  cap per path  →  snippet  →  SearchResult
                 ┌─ semantic channel ───────────────────────┐    (RRF in   (C2: drop      (A1: FTS5     (limit
                 │  cosine top-K (widened)                  │    hybrid)   excess         snippet for   results)
                 │  → length downweight per chunk (D1)      │              chunks per     keyword/
                 │  → re-rank within channel                │              path)          hybrid-keyword,
                 └──────────────────────────────────────────┘                             word-window
                                                                                          for semantic-only)
```

**Per mode.**
- `mode="keyword"` — only the keyword channel runs. Cap → snippet → return.
- `mode="semantic"` — only the semantic channel runs. Cap → snippet (word-window fallback path) → return.
- `mode="hybrid"` — both channels, RRF fuse, then cap → snippet → return.

**Candidate widening.** Each channel fetches `max(limit * (chunks_per_doc + 4), 50)` candidates so that capping doesn't starve us of `limit` results. The `+4` is slack for ranking inversions where same-doc chunks cluster at the top.

## Detailed mechanism

### Length downweight (1b, D1)

Each chunk has a known `chunk_count_in_doc` value (its parent doc's total chunks, computed once at index time and stored in a new `documents.chunk_count` column).

Within each channel:
- Adjusted score: `raw_score / (1 + alpha * log(chunk_count_in_doc))`.
- Re-sort the channel by adjusted score (rank order is what RRF consumes downstream).
- For RRF the divisor's magnitude doesn't get combined across BM25 and cosine — only ranks merge.

Effect at the default `alpha = 0.25`: a 10-chunk doc loses ~37% effective rank weight; a 2-chunk doc loses ~17%; a 1-chunk doc is unchanged. `alpha = 0` disables.

### Per-doc cap (1a, C2)

Cap is applied **after RRF fusion**, uniformly across all three modes:
- Walk the merged-and-sorted list in ranked order.
- For each result, increment a per-`path` counter.
- Skip results whose counter has already reached `chunks_per_doc`.
- Stop when `limit` results are collected.

C2 was preferred over C1 (cap-per-channel) because RRF should see full per-channel information; capping is a presentation/diversity step, not a ranking concern.

### Snippet selection (2a, A1)

Computed **after cap**, so only the `limit` surviving results pay the cost.

- **Keyword hit (or keyword-side hit in hybrid):** select FTS5's `snippet(notes_fts, 4, '', '', '…', snippet_words)` as a column expression in the FTS query. SQLite computes a tokenizer-aware window centered on match terms, with `…` ellipsis on truncated edges. Column index 4 is the `content` column (declared 0-indexed in `notes_fts USING fts5(path, title, folder, heading, content, ...)`).
- **Semantic-only (came from cosine, never matched keyword):** Python word-window scan of the chunk's full content.
  - Tokenize query case-insensitively.
  - Slide a `snippet_words`-wide window across the chunk; pick the window with the highest count of query tokens.
  - Falls back to the first `snippet_words` words of the chunk body when the query has zero literal overlap. The chunk body already starts at the line *after* the heading (the chunker strips the heading line), and the heading text itself is returned separately on `SearchResult.heading` — so the fallback is heading-anchored in effect without redundant text in `content`.
- **`snippet_words = 0`:** skip truncation entirely; `content` is the full chunk.

Snippet computation is bounded: O(snippet_words) for FTS5, O(chunk_size) for the Python fallback. Per-result, not per-candidate.

### Adaptive chunking (goal 5)

Algorithm in `HeadingChunker`:
1. Split at H1.
2. For each chunk, if word count > `max_chunk_words`, re-split at H2.
3. Recurse: H2 → H3 → H4 → H5 → H6.
4. Stop when chunk fits, or when no headings of the next level exist inside.
5. Preamble (no heading) and "single huge prose block with no sub-headings" cases: leave as-is.
6. Short-doc bypass (≤ 30 lines) still applies — redundant with adaptive but harmless.

Word count: `len(content.split())`. Recursion depth is bounded by 6 (H1–H6). Migration: existing vault must be reindexed for the new chunker to take effect; reindex is an existing operation.

## Component & file changes

| File | Change |
|---|---|
| `src/markdown_vault_mcp/scanner.py` | Extend `HeadingChunker.__init__` with `max_chunk_words: int \| None = None`. Add private `_refine_oversize(chunks, current_level, max_words)` helper. Word count via `len(content.split())`. `max_chunk_words=None` preserves today's H1/H2-only behavior. |
| `src/markdown_vault_mcp/fts_index.py` | Add `chunk_count INTEGER NOT NULL DEFAULT 1` column to `documents` table. Populate during `upsert_note` and `build_from_notes` from `len(note.chunks)`. Provide a migration step (`ALTER TABLE ADD COLUMN`) for FTS DBs created before this PR. New `FTSIndex.search(...)` parameter `snippet_words: int \| None`: when set, the SQL projects `snippet(notes_fts, 4, '', '', '…', snippet_words)` for the content column instead of raw `content`. New `chunk_count` field on `FTSResult`. |
| `src/markdown_vault_mcp/types.py` | Add `chunk_count` to `FTSResult` (internal). `SearchResult` shape unchanged. Update the `content` field docstring to reflect snippet semantics and recovery via `read(path, section=...)`. |
| `src/markdown_vault_mcp/managers/search.py` | New private helpers: `_apply_length_downweight(results, alpha)`, `_apply_chunks_per_doc_cap(results, n)`, `_compute_snippet_for_semantic(content, query, snippet_words)`. Rework `_keyword_search`, `_semantic_search`, `_hybrid_search` to apply the pipeline shown above. Candidate-widening formula moves into a single helper. The public `search()` method gains `chunks_per_doc: int \| None = None` and `snippet_words: int \| None = None` parameters; `None` falls back to config defaults. |
| `src/markdown_vault_mcp/managers/document.py` | Extend `DocumentManager.read(path)` → `read(path, *, section: str \| None = None)`. When `section` is provided, query the `sections` table for the matching `(document_id, heading)` and return only that chunk's content; raise `ValueError` if not found. `section=None` keeps today's whole-file behavior. Empty / whitespace section raises `ValueError`. Preamble retrieval not exposed. |
| `src/markdown_vault_mcp/collection.py` | Plumb the new config knobs into `SearchManager` and `HeadingChunker` construction. |
| `src/markdown_vault_mcp/config.py` | Add four config fields between `CONFIG-FIELDS-START`/`END` sentinels. Read from env in the matching `CONFIG-FROM-ENV` block. |
| `src/markdown_vault_mcp/_server_tools.py` | On `search` (≈ line 83): surface `chunks_per_doc` and `snippet_words` as per-call parameters; update tool docstring/Returns to describe snippet semantics + recovery via `read(path, section=...)`. On `read` (≈ line 154): surface the new `section` parameter. |
| `docs/design.md` | New "Search ranking and snippet truncation" section under Search architecture. Update the chunker description for adaptive H-level splitting. |
| `docs/tools/index.md`, `docs/configuration.md`, `examples/.env.example` | New env vars documented; `search` and `read` tool signatures updated. |

## API surface

### Config / env vars (new)

| Env var | Default | Type | Notes |
|---|---|---|---|
| `MARKDOWN_VAULT_MCP_CHUNKS_PER_DOC` | `2` | int ≥ 1 | Per-doc cap on results. `0` rejected. |
| `MARKDOWN_VAULT_MCP_SNIPPET_WORDS` | `200` | int ≥ 0 | Snippet word budget. `0` = no truncation. |
| `MARKDOWN_VAULT_MCP_LENGTH_DOWNWEIGHT_ALPHA` | `0.25` | float ≥ 0 | `score / (1 + alpha · log(chunk_count))`. `0` disables. |
| `MARKDOWN_VAULT_MCP_MAX_CHUNK_WORDS` | `400` | int ≥ 1 | Adaptive chunker threshold. Set very high (e.g. `100000`) to disable adaptive splitting. |

`length_downweight_alpha` is operator-only (env-var only, no per-call override). The other three knobs accept per-call overrides on the `search` MCP tool.

### `search` MCP tool — new optional parameters

```python
search(
    query: str,
    *,
    limit: int = 10,
    mode: Literal["keyword", "semantic", "hybrid"] = "keyword",
    filters: dict[str, str] | None = None,
    folder: str | None = None,
    chunks_per_doc: int | None = None,   # NEW — None → server default
    snippet_words: int | None = None,    # NEW — None → server default; 0 → full chunk
) -> list[SearchResult]
```

`SearchResult` shape unchanged; `content` semantics changed (snippet by default — documented in the tool docstring).

### `read` MCP tool — new optional parameter

```python
read(
    path: str,
    *,
    section: str | None = None,   # NEW — None → whole document; else exact heading match
) -> NoteContent | AttachmentContent
```

When `section` is provided:
- Heading lookup uses exact-match against `sections.heading` for that document.
- Multiple sections share the same heading? First by `start_line` is returned (deterministic). Documented behavior; rare in practice.
- Section not found → `ValueError("Section 'X' not found in document Y")`.
- `section=""` or whitespace-only → `ValueError`.
- Returned `NoteContent.content` is the chunk content; frontmatter is not synthesized for section-only reads.

### Backwards compatibility

- Existing `search` callers passing no new params get a 200-word snippet in `content`. **This is a default behavior change.** Documented in `CHANGELOG.md` as a `feat:` (default-tightening). Consumers can opt back into full-chunk behavior with `snippet_words=0`.
- Existing `read` callers passing no new params see identical behavior to today.
- Existing `SearchResult` consumers reading `content` continue to work (same field, same type, just shorter).
- **Reindex required** for the chunker change to take effect — the new `documents.chunk_count` column is populated and the adaptive chunker boundaries differ from today's. Call out in release notes; the existing `reindex` MCP tool / startup path handles it.

### Validation

- Numeric params: reject negatives at parameter-binding time.
- `chunks_per_doc=0` rejected.
- Other knobs accept `0` (feature-disabled semantics).
- `section`: empty / whitespace raises `ValueError` at the manager layer.

## Testing strategy

| Test surface | What to cover |
|---|---|
| `tests/test_scanner_adaptive_chunking.py` (new) | `max_chunk_words=None` produces today's H1/H2-only behavior. `max_chunk_words=400` recursively splits oversize H1 → H2 sub-chunks. Recursion descends H1→…→H6 and stops when chunk fits. Oversize H6 (or oversize prose with no deeper headings) stays as one chunk. Preamble stays as one chunk regardless of size. Short-doc bypass (≤ 30 lines) still applies. `heading_level` and `start_line` correctly propagated. |
| `tests/test_search_length_downweight.py` (new) | Fixture vault with one 14-chunk doc + ten 1-chunk docs, all containing a query term. `alpha=0`: long-doc chunks dominate. `alpha=0.25`: they slide down. `alpha=2.0`: they're nearly absent. Run for keyword, semantic, hybrid. |
| `tests/test_search_chunks_per_doc_cap.py` (new) | Same fixture: with `chunks_per_doc=1`, top-10 results contain ≤ 1 chunk per path. With `chunks_per_doc=2`, ≤ 2 per path. Candidate-widening formula yields `limit` results when enough distinct docs exist; fewer when the vault has fewer matching docs. Per-call override beats env-var default. |
| `tests/test_search_snippets.py` (new) | `snippet_words=0` → full chunk. `snippet_words=200` on a long chunk → ≤ ~200 words and centered on a query token. FTS5 path: keyword hit produces tokenizer-aware snippet with `…` ellipses. Semantic-only path: word-window scan picks the densest window of query tokens; falls back to first N words on no overlap. Hybrid: keyword-side hit gets FTS5 snippet; semantic-only hit gets Python word-window. Snippet generation runs *after* cap (only `limit` snippets computed). |
| `tests/test_documents_read_section.py` (new) | `read(path)` → whole file (regression). `read(path, section="Heading")` → just that section's chunk. Unknown / empty / whitespace section → `ValueError`. Multiple sections with the same heading → first by `start_line`. Frontmatter not included in section-only reads. |
| `tests/test_fts_chunk_count.py` (new) | New `chunk_count` column populated at `upsert_note` and `build_from_notes`. Reindex updates the column when chunk count changes. Migration: an FTS DB created before this PR is upgraded on next index load. |
| `tests/test_search_pipeline_integration.py` (new) | End-to-end on the diagnostic-style fixture (one 12-section essay + many short notes, query similar to "se-cura etymology"): essay occupies ≤ 2 of top 10 slots; snippet payloads are bounded; other docs get representation. Run for all three modes. |
| Existing tests | `tests/test_search*.py`, `tests/test_collection_search.py`, etc. — many will break because `content` is now snippet-by-default. Add `snippet_words=0` to existing search calls that assert on full-content equality. The breakage is itself a useful signal that the feature works as advertised. |

### Manual verification checklist (in PR description)

- [ ] `uv run pytest -x -q` — all tests pass.
- [ ] `uv run mypy src/ tests/` — no errors.
- [ ] `uv run ruff check --fix .` then `uv run ruff format .` — clean.
- [ ] Reindex local vault. Run diagnostic queries `"se-cura"` (semantic) and `"se-cura etymology security without care"` (hybrid). Eyeball: ≤ 2 essay slots in top 10, snippets are sentence-scale, other relevant notes appear.
- [ ] Run with `chunks_per_doc=1, snippet_words=0` — escape-hatch behavior matches expectations.
- [ ] Run with `length_downweight_alpha=0` — long docs return to dominant ranking (regression-style sanity check).

### Patch coverage

All new code in `scanner.py`, `search.py`, `document.py`, `fts_index.py`, and `config.py` exercised by the suites above. Target ≥ 80% on the diff (project hard gate).

### Performance

- Snippet computation is per-result (10ish per query), not per-candidate (50–100). FTS5 `snippet()` is constant-time SQL. Word-window scan is O(chunk_size) per semantic-only result — negligible.
- Length downweight adds one log + one division per candidate — negligible.
- Adaptive chunking adds O(chunks) recursive work at index time, paid once per document.

## Open questions resolved during brainstorming

| Question | Resolution |
|---|---|
| Scope of `kind` taxonomy (1c)? | **Out, by principle.** MCP must not require frontmatter conventions on vault content. Captured as non-goal 1. |
| Per-call override for cap and snippet knobs? | **Yes** for `chunks_per_doc` and `snippet_words`. **No** for `length_downweight_alpha` (operator tuning knob). |
| Defaults for new knobs? | `chunks_per_doc=2`, `snippet_words=200`, `length_downweight_alpha=0.25`, `max_chunk_words=400`. |
| Snippet selection strategy? | A1: FTS5 native `snippet()` for keyword/hybrid-keyword + Python word-window for semantic-only + first-N-words-of-chunk-body fallback when query has zero literal overlap. |
| Backwards compatibility — replace `content` or add `snippet`? | F1: keep `content`, truncate by default, `snippet_words=0` opts out. No SearchResult shape break. |
| Cap × RRF interaction? | C2: cap *after* RRF on the merged sorted list. Uniform across all three modes. |
| Length downweight placement? | D1: per-channel, before fusion. Re-rank each channel by adjusted score. |
| Recovery path for snippet truncation? | B2: extend `read(path)` with optional `section` parameter. Reuses existing `(path, heading)` chunk identity. |
| Adaptive chunking? | **In scope.** Goal 5. Threshold-driven recursive H-level descent. |

## Risks & mitigations

- **Risk:** default snippet truncation surprises an existing automation that depends on full `content`. **Mitigation:** explicit `feat:` `CHANGELOG.md` entry; `snippet_words=0` escape hatch documented prominently in tool docstring and migration notes.
- **Risk:** adaptive chunker changes embedding behavior in ways that hurt some queries even as it helps others. **Mitigation:** `max_chunk_words` is tunable; setting it very high reverts to today's behavior. Observe diagnostic queries after deploy.
- **Risk:** `documents.chunk_count` migration on existing FTS databases. **Mitigation:** `ALTER TABLE ADD COLUMN ... DEFAULT 1` is non-destructive; population happens lazily via the next reindex of each doc, with a guard that recomputes on missing or stale values.
- **Risk:** word-count chunking threshold doesn't match user expectations on multilingual content (CJK has no whitespace). **Mitigation:** `len(content.split())` is good enough for prose markdown; non-Latin scripts may want a custom threshold via the env var. Document as a known limitation.
