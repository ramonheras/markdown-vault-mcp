# Search ranking and snippet truncation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a single long document from dominating search results, and bound result-payload size, by adding a per-document result cap, a length-based ranking downweight, snippet truncation, and adaptive heading-level chunking.

**Architecture:** New ranking-pipeline stages live in `SearchManager` and run in this order: per-channel length downweight → RRF fusion (hybrid only) → per-path cap → snippet projection. The chunker (`HeadingChunker`) gains a recursive H1→H6 refinement step driven by a word-count threshold. A new `chunk_count` column on the FTS `documents` table feeds the length downweight. The MCP `search` and `read` tools surface the new knobs as optional parameters; defaults come from config / env vars.

**Tech Stack:** Python 3.11+, SQLite FTS5, FastMCP, `uv` for package management, `ruff` for lint/format, `mypy` for type checking, `pytest` for tests.

**Spec:** [`docs/superpowers/specs/2026-04-30-search-ranking-and-snippets-design.md`](../specs/2026-04-30-search-ranking-and-snippets-design.md)

**Conventions used in every task:**
- Test-driven: write the failing test, run it to confirm it fails, write the minimal code to pass, run it again, commit.
- Each task ends in a single conventional-commit (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`).
- Before every commit, run all three gates: `uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q`. Pre-commit hooks duplicate these checks; do not bypass with `--no-verify`.
- Line numbers in this plan reflect the codebase as of commit `26416f2`. They may drift slightly across earlier tasks — re-check with `grep -n` if a snippet does not match.

---

## Task 1: Add four config fields & env-var reads

**Goal:** Foundation for everything else — the new knobs available on `CollectionConfig` and read from env vars.

**Files:**
- Modify: `src/markdown_vault_mcp/config.py:160-207` (CONFIG-FIELDS sentinel block)
- Modify: `src/markdown_vault_mcp/config.py:692-734` (CONFIG-FROM-ENV sentinel block)
- Test: `tests/test_config.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_search_ranking_config_defaults(monkeypatch, tmp_path):
    """New ranking/snippet knobs default to documented values when env unset."""
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(tmp_path))
    # Clear any test-runner-leaked overrides.
    for var in (
        "MARKDOWN_VAULT_MCP_CHUNKS_PER_DOC",
        "MARKDOWN_VAULT_MCP_SNIPPET_WORDS",
        "MARKDOWN_VAULT_MCP_LENGTH_DOWNWEIGHT_ALPHA",
        "MARKDOWN_VAULT_MCP_MAX_CHUNK_WORDS",
    ):
        monkeypatch.delenv(var, raising=False)
    from markdown_vault_mcp.config import load_config

    cfg = load_config()
    assert cfg.chunks_per_doc == 2
    assert cfg.snippet_words == 200
    assert cfg.length_downweight_alpha == 0.25
    assert cfg.max_chunk_words == 400


def test_search_ranking_config_env_overrides(monkeypatch, tmp_path):
    """Env vars override the defaults."""
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(tmp_path))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_CHUNKS_PER_DOC", "1")
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SNIPPET_WORDS", "0")
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_LENGTH_DOWNWEIGHT_ALPHA", "0.0")
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_MAX_CHUNK_WORDS", "100000")
    from markdown_vault_mcp.config import load_config

    cfg = load_config()
    assert cfg.chunks_per_doc == 1
    assert cfg.snippet_words == 0
    assert cfg.length_downweight_alpha == 0.0
    assert cfg.max_chunk_words == 100000


def test_search_ranking_config_rejects_zero_chunks_per_doc(monkeypatch, tmp_path):
    """chunks_per_doc=0 is rejected at load_config time (no useful semantics)."""
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(tmp_path))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_CHUNKS_PER_DOC", "0")
    from markdown_vault_mcp.config import load_config

    with pytest.raises(ValueError, match="chunks_per_doc"):
        load_config()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k 'search_ranking' -v`
Expected: FAIL — `AttributeError: 'CollectionConfig' object has no attribute 'chunks_per_doc'`.

- [ ] **Step 3: Add fields to `CollectionConfig`**

Inside the `CONFIG-FIELDS-START` ... `CONFIG-FIELDS-END` block in `src/markdown_vault_mcp/config.py`, append after line 206 (after `fastembed_cache_dir`):

```python
    # Search ranking and snippet truncation
    chunks_per_doc: int = 2
    snippet_words: int = 200
    length_downweight_alpha: float = 0.25
    max_chunk_words: int = 400
```

- [ ] **Step 4: Read from env in `load_config()`**

Just above `return CollectionConfig(` (around line 692), add:

```python
    raw_chunks_per_doc = (_env("CHUNKS_PER_DOC") or "").strip()
    chunks_per_doc = int(raw_chunks_per_doc) if raw_chunks_per_doc else 2
    if chunks_per_doc < 1:
        raise ValueError(
            f"chunks_per_doc must be >= 1, got {chunks_per_doc}; set "
            "MARKDOWN_VAULT_MCP_CHUNKS_PER_DOC to a positive integer."
        )

    raw_snippet_words = (_env("SNIPPET_WORDS") or "").strip()
    snippet_words = int(raw_snippet_words) if raw_snippet_words else 200
    if snippet_words < 0:
        raise ValueError(f"snippet_words must be >= 0, got {snippet_words}")

    raw_alpha = (_env("LENGTH_DOWNWEIGHT_ALPHA") or "").strip()
    length_downweight_alpha = float(raw_alpha) if raw_alpha else 0.25
    if length_downweight_alpha < 0:
        raise ValueError(
            f"length_downweight_alpha must be >= 0, got {length_downweight_alpha}"
        )

    raw_max_chunk_words = (_env("MAX_CHUNK_WORDS") or "").strip()
    max_chunk_words = int(raw_max_chunk_words) if raw_max_chunk_words else 400
    if max_chunk_words < 1:
        raise ValueError(f"max_chunk_words must be >= 1, got {max_chunk_words}")
```

Then inside the `CONFIG-FROM-ENV` block (just before `# CONFIG-FROM-ENV-END`), add:

```python
        chunks_per_doc=chunks_per_doc,
        snippet_words=snippet_words,
        length_downweight_alpha=length_downweight_alpha,
        max_chunk_words=max_chunk_words,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -k 'search_ranking' -v`
Expected: PASS (all three tests).

- [ ] **Step 6: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/config.py tests/test_config.py
git commit -m "feat(config): add search ranking and snippet config knobs

Adds four new fields to CollectionConfig with env-var defaults:
chunks_per_doc=2, snippet_words=200, length_downweight_alpha=0.25,
max_chunk_words=400. Validation rejects chunks_per_doc=0 and any
negative value at load time."
```

---

## Task 2: Adaptive heading-level chunking

**Goal:** When a chunk exceeds `max_chunk_words`, recursively re-split at the next heading level (H1 → H2 → ... → H6).

**Files:**
- Modify: `src/markdown_vault_mcp/scanner.py:70-172` (`HeadingChunker`)
- Test: `tests/test_scanner_adaptive_chunking.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_scanner_adaptive_chunking.py`:

```python
"""Tests for HeadingChunker's adaptive H-level refinement."""

from __future__ import annotations

from markdown_vault_mcp.scanner import HeadingChunker


def _doc(*sections: tuple[int, str, int]) -> str:
    """Build a markdown doc from (level, heading, body_word_count) tuples."""
    parts: list[str] = []
    for level, heading, words in sections:
        parts.append("#" * level + " " + heading)
        parts.append(" ".join(["lorem"] * words))
        parts.append("")
    return "\n".join(parts) + "\n"


def test_max_chunk_words_none_preserves_h1_h2_only_behavior():
    """max_chunk_words=None keeps today's H1/H2-only splitting."""
    body = _doc(
        (1, "Top", 50),
        (2, "Sub A", 50),
        (3, "Deep", 800),  # H3, would not split today and must not split.
    )
    chunker = HeadingChunker(max_chunk_words=None)
    chunks = chunker.chunk(body, {})
    # H1 + H2 produce 2 chunks; H3 stays inside the H2 chunk.
    assert len(chunks) == 2
    headings = [c.heading for c in chunks]
    assert headings == ["Top", "Sub A"]


def test_oversize_h1_splits_at_h2():
    """An H1 chunk exceeding max_chunk_words is re-split at H2."""
    body = _doc(
        (1, "Top", 0),
        (2, "Sub A", 300),
        (2, "Sub B", 300),
    )
    chunker = HeadingChunker(max_chunk_words=200)
    chunks = chunker.chunk(body, {})
    assert [c.heading for c in chunks] == ["Sub A", "Sub B"]
    assert all(c.heading_level == 2 for c in chunks)


def test_recursion_descends_to_h6():
    """An H1 chunk with deeply nested oversized sub-headings descends to H6."""
    body = _doc(
        (1, "L1", 0),
        (2, "L2", 0),
        (3, "L3", 0),
        (4, "L4", 0),
        (5, "L5", 0),
        (6, "L6a", 50),
        (6, "L6b", 50),
    )
    chunker = HeadingChunker(max_chunk_words=80)
    chunks = chunker.chunk(body, {})
    headings = [c.heading for c in chunks]
    assert "L6a" in headings and "L6b" in headings


def test_oversize_chunk_with_no_deeper_headings_stays_one_chunk():
    """A 1000-word H6 with no deeper headings stays as one chunk."""
    body = "###### Solo\n" + " ".join(["lorem"] * 1000) + "\n"
    chunker = HeadingChunker(max_chunk_words=200)
    chunks = chunker.chunk(body, {})
    assert len(chunks) == 1
    assert chunks[0].heading == "Solo"


def test_preamble_stays_one_chunk_regardless_of_size():
    """Preamble (no heading) is not refined further."""
    preamble_words = 1000
    body = (
        " ".join(["lorem"] * preamble_words)
        + "\n\n# Heading\n\n"
        + " ".join(["ipsum"] * 50)
        + "\n"
    )
    chunker = HeadingChunker(max_chunk_words=200)
    chunks = chunker.chunk(body, {})
    # First chunk is the oversize preamble (heading=None), preserved.
    assert chunks[0].heading is None
    assert len(chunks[0].content.split()) >= preamble_words


def test_short_doc_bypass_still_applies():
    """Documents <= 30 lines return as one chunk."""
    body = "# A\nbody\n## B\nmore body\n"
    chunker = HeadingChunker(max_chunk_words=10)
    chunks = chunker.chunk(body, {})
    assert len(chunks) == 1


def test_heading_level_and_start_line_propagated_through_recursion():
    """Refined sub-chunks carry correct heading_level and start_line."""
    body = _doc(
        (1, "Top", 0),
        (2, "Inner", 300),
    )
    chunker = HeadingChunker(max_chunk_words=200)
    chunks = chunker.chunk(body, {})
    inner = next(c for c in chunks if c.heading == "Inner")
    assert inner.heading_level == 2
    # start_line points at the H2 line in the document.
    body_lines = body.splitlines()
    assert body_lines[inner.start_line].lstrip().startswith("## Inner")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scanner_adaptive_chunking.py -v`
Expected: FAIL — `TypeError: HeadingChunker.__init__() got an unexpected keyword argument 'max_chunk_words'`.

- [ ] **Step 3: Implement adaptive chunking**

In `src/markdown_vault_mcp/scanner.py`, replace the existing `HeadingChunker` class (lines 70-172) with:

```python
class HeadingChunker:
    """Split document on heading boundaries, descending adaptively when chunks
    exceed ``max_chunk_words``.

    Default behaviour (``max_chunk_words=None``): split on H1/H2 only — the
    pre-2026-04 behaviour. With ``max_chunk_words`` set, after the initial
    H1/H2 split each chunk that exceeds the threshold is recursively re-split
    at the next heading level (H3, then H4, …, up to H6) until each chunk
    fits or no headings of the next level exist inside.

    Short documents (fewer than ``short_doc_lines`` lines) are returned as a
    single chunk without splitting. Preamble (content before the first
    heading) is never refined further regardless of size — there are no
    deeper headings to split on.

    This is the default chunking strategy.
    """

    def __init__(
        self,
        short_doc_lines: int = _SHORT_DOC_LINES,
        *,
        max_chunk_words: int | None = None,
    ) -> None:
        """Initialise the chunker.

        Args:
            short_doc_lines: Line count at or below which the document is
                returned as a single chunk rather than split on headings.
            max_chunk_words: Word-count threshold above which a chunk is
                recursively re-split at the next heading level. ``None``
                preserves today's H1/H2-only behaviour.
        """
        self.short_doc_lines = short_doc_lines
        self.max_chunk_words = max_chunk_words

    def chunk(self, content: str, _metadata: dict[str, Any]) -> list[Chunk]:
        """Split content adaptively on heading boundaries.

        Args:
            content: Markdown body after frontmatter has been stripped.
            _metadata: Parsed frontmatter dict (unused).

        Returns:
            List of :class:`~markdown_vault_mcp.types.Chunk` objects.
        """
        lines = content.splitlines(keepends=True)

        if len(lines) <= self.short_doc_lines:
            return [Chunk(heading=None, heading_level=0, content=content, start_line=0)]

        chunks = self._split_at_levels(lines, levels=(1, 2), base_line=0)
        if chunks and self.max_chunk_words is not None:
            chunks = self._refine_oversize(chunks, current_level=2)
        return chunks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_at_levels(
        self,
        lines: list[str],
        *,
        levels: tuple[int, ...],
        base_line: int,
    ) -> list[Chunk]:
        """Split *lines* on any heading whose level is in *levels*.

        ``base_line`` is added to every emitted ``start_line`` so that
        ``start_line`` always refers to the *original* document, not the
        sub-slice passed in during recursion.

        Returns an empty list if the slice contains no matching headings.
        """
        # Walk and record split points (line index in this slice, level, text).
        split_points: list[tuple[int, int, str]] = []
        max_level = max(levels)
        pat = re.compile(rf"^(#{{1,{max_level}}})\s+(.+)$")
        for idx, line in enumerate(lines):
            m = pat.match(line.rstrip())
            if m:
                level = len(m.group(1))
                if level in levels:
                    split_points.append((idx, level, m.group(2).strip()))

        if not split_points:
            return []

        chunks: list[Chunk] = []

        # Preamble: anything before the first split point.
        first_line = split_points[0][0]
        if first_line > 0:
            preamble = "".join(lines[:first_line])
            if preamble.strip():
                chunks.append(
                    Chunk(
                        heading=None,
                        heading_level=0,
                        content=preamble,
                        start_line=base_line,
                    )
                )

        for i, (line_idx, level, heading_text) in enumerate(split_points):
            content_start = line_idx + 1
            content_end = (
                split_points[i + 1][0] if i + 1 < len(split_points) else len(lines)
            )
            section_content = "".join(lines[content_start:content_end])
            if not section_content.strip():
                continue
            chunks.append(
                Chunk(
                    heading=heading_text,
                    heading_level=level,
                    content=section_content,
                    start_line=base_line + line_idx,
                )
            )
        return chunks

    def _refine_oversize(
        self, chunks: list[Chunk], *, current_level: int
    ) -> list[Chunk]:
        """Recursively re-split chunks that exceed ``max_chunk_words``.

        ``current_level`` is the deepest heading level already used as a
        split point. Refinement attempts ``current_level + 1`` next.
        """
        assert self.max_chunk_words is not None  # guarded by caller
        if current_level >= 6:
            return chunks

        next_level = current_level + 1
        out: list[Chunk] = []
        for chunk in chunks:
            if chunk.heading is None:
                # Preamble: no deeper headings exist inside it; keep as-is.
                out.append(chunk)
                continue
            if len(chunk.content.split()) <= self.max_chunk_words:
                out.append(chunk)
                continue

            sub_lines = chunk.content.splitlines(keepends=True)
            sub_chunks = self._split_at_levels(
                sub_lines, levels=(next_level,), base_line=chunk.start_line + 1
            )
            if not sub_chunks:
                # No headings of next_level inside; cannot split further.
                out.append(chunk)
                continue
            out.extend(self._refine_oversize(sub_chunks, current_level=next_level))
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scanner_adaptive_chunking.py -v`
Expected: PASS (all seven tests).

Then run the full scanner suite to confirm no regressions:

Run: `uv run pytest tests/test_scanner.py -v`
Expected: PASS (existing tests continue to work — `max_chunk_words=None` is the new default and preserves prior behaviour).

- [ ] **Step 5: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/scanner.py tests/test_scanner_adaptive_chunking.py
git commit -m "feat(scanner): adaptive heading-level chunker

HeadingChunker now accepts max_chunk_words; when set, oversize H1/H2
chunks are recursively re-split at deeper heading levels (H3 -> H4
-> H5 -> H6) until each chunk fits or no deeper headings exist.
max_chunk_words=None (the default) preserves today's H1/H2-only
behaviour."
```

---

## Task 3: `documents.chunk_count` column + migration

**Goal:** Persist the parent-document chunk count so the length downweight has a fast lookup at query time.

**Files:**
- Modify: `src/markdown_vault_mcp/fts_index.py:39-47` (schema), `200+` (`FTSIndex` ctor migration), `260-270` (`_insert_document`), `517+` (`upsert_note`).
- Test: `tests/test_fts_chunk_count.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_fts_chunk_count.py`:

```python
"""Tests for the chunk_count column on documents and its migration path."""

from __future__ import annotations

import sqlite3

from markdown_vault_mcp.fts_index import FTSIndex
from markdown_vault_mcp.scanner import HeadingChunker, parse_note


def _make_note(tmp_path, name: str, body: str):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return parse_note(p, tmp_path, HeadingChunker(max_chunk_words=200))


def test_chunk_count_populated_on_upsert(tmp_path):
    """upsert_note populates documents.chunk_count from len(note.chunks)."""
    fts = FTSIndex(db_path=":memory:")
    body = "\n".join(
        ["# A", "alpha body " * 10, "## B", "beta body " * 10, "## C", "gamma " * 10]
    )
    note = _make_note(tmp_path, "doc.md", body)
    fts.upsert_note(note)

    row = fts._conn.execute(
        "SELECT chunk_count FROM documents WHERE path = ?", (note.path,)
    ).fetchone()
    assert row is not None
    assert row["chunk_count"] == len(note.chunks)


def test_chunk_count_populated_on_build_from_notes(tmp_path):
    """build_from_notes populates chunk_count for every note."""
    fts = FTSIndex(db_path=":memory:")
    notes = [
        _make_note(tmp_path, "a.md", "# A\nalpha\n## B\nbeta\n"),
        _make_note(tmp_path, "b.md", "# A\nonly one chunk\n"),
    ]
    fts.build_from_notes(notes)

    counts = dict(
        fts._conn.execute("SELECT path, chunk_count FROM documents").fetchall()
    )
    assert counts["a.md"] == len(notes[0].chunks)
    assert counts["b.md"] == len(notes[1].chunks)


def test_chunk_count_updates_on_reupsert(tmp_path):
    """When a doc is re-upserted with a different chunk count, the column updates."""
    fts = FTSIndex(db_path=":memory:")
    note_v1 = _make_note(tmp_path, "doc.md", "# A\nbody\n")
    fts.upsert_note(note_v1)
    v1_count = fts._conn.execute(
        "SELECT chunk_count FROM documents WHERE path = ?", (note_v1.path,)
    ).fetchone()["chunk_count"]

    note_v2 = _make_note(
        tmp_path,
        "doc.md",
        "# A\nbody\n## B\nmore\n## C\neven more\n",
    )
    fts.upsert_note(note_v2)
    v2_count = fts._conn.execute(
        "SELECT chunk_count FROM documents WHERE path = ?", (note_v2.path,)
    ).fetchone()["chunk_count"]

    assert v2_count != v1_count
    assert v2_count == len(note_v2.chunks)


def test_migration_adds_column_to_pre_existing_db(tmp_path):
    """Opening an FTS DB created without chunk_count adds the column."""
    db_path = tmp_path / "old.sqlite3"
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            folder TEXT NOT NULL DEFAULT '',
            frontmatter_json TEXT,
            content_hash TEXT NOT NULL,
            modified_at REAL NOT NULL
        );
        INSERT INTO documents (path, title, content_hash, modified_at)
        VALUES ('legacy.md', 'Legacy', 'x', 0.0);
        """
    )
    legacy.commit()
    legacy.close()

    fts = FTSIndex(db_path=db_path)
    cols = [
        r["name"]
        for r in fts._conn.execute("PRAGMA table_info(documents)").fetchall()
    ]
    assert "chunk_count" in cols
    # Existing legacy row gets the default value.
    row = fts._conn.execute(
        "SELECT chunk_count FROM documents WHERE path = 'legacy.md'"
    ).fetchone()
    assert row["chunk_count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fts_chunk_count.py -v`
Expected: FAIL — `sqlite3.OperationalError: no such column: chunk_count`.

- [ ] **Step 3: Add the column to the schema literal**

In `src/markdown_vault_mcp/fts_index.py`, edit the `documents` table literal (around lines 39-47). The new shape:

```python
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    folder TEXT NOT NULL DEFAULT '',
    frontmatter_json TEXT,
    content_hash TEXT NOT NULL,
    modified_at REAL NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 1
);
```

- [ ] **Step 4: Add migration step to `FTSIndex.__init__`**

Find the `FTSIndex` constructor (around line 201). Locate where `_open_connection` is called and the schema is applied. Immediately after schema application, add a small migration that ensures the column exists on pre-existing DBs:

```python
        # Migration: chunk_count was added 2026-04-30. ALTER TABLE is a no-op
        # if the column already exists, but SQLite has no IF NOT EXISTS for
        # columns, so we probe PRAGMA first.
        cols = {
            r["name"]
            for r in self._conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "chunk_count" not in cols:
            self._conn.execute(
                "ALTER TABLE documents ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 1"
            )
            self._conn.commit()
            logger.info(
                "fts_index: migrated documents table — added chunk_count column"
            )
```

(Adapt the indentation to match the surrounding constructor body. The migration must run *after* the schema script and *before* any `SELECT chunk_count` happens.)

- [ ] **Step 5: Populate `chunk_count` in `_insert_document` and `upsert_note`**

Find `_insert_document` (or equivalent — search for the `INSERT INTO documents (...) VALUES (...)` statement). Add `chunk_count` to the column list and pass `len(note.chunks)`:

```python
                cur.execute(
                    """
                    INSERT INTO documents
                        (path, title, folder, frontmatter_json,
                         content_hash, modified_at, chunk_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note.path,
                        note.title,
                        _derive_folder(note.path),
                        json.dumps(note.frontmatter, default=_json_default)
                        if note.frontmatter
                        else None,
                        note.content_hash,
                        note.modified_at,
                        len(note.chunks),
                    ),
                )
```

If `upsert_note` deletes and re-inserts, the change above suffices. If it does an in-place `UPDATE`, also update the `UPDATE documents SET ... WHERE id = ?` to include `chunk_count = ?`. Re-read the function to confirm which strategy is used; both are common.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_fts_chunk_count.py -v`
Expected: PASS (all four tests).

Run the full FTS suite for regressions: `uv run pytest tests/test_fts_index.py -v` — Expected: PASS.

- [ ] **Step 7: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/fts_index.py tests/test_fts_chunk_count.py
git commit -m "feat(fts): add chunk_count column on documents

Stored at index/upsert time as len(note.chunks); used downstream by
the length-downweight ranking step. Pre-existing FTS databases are
migrated via ALTER TABLE ADD COLUMN with default 1; existing rows
will be corrected on next reindex."
```

---

## Task 4: FTS5 `snippet()` projection + `chunk_count` on `FTSResult`

**Goal:** `FTSIndex.search()` can return a tokenizer-aware snippet of the matched content instead of the full chunk, and exposes `chunk_count` for downstream ranking.

**Files:**
- Modify: `src/markdown_vault_mcp/types.py:96+` (`FTSResult`)
- Modify: `src/markdown_vault_mcp/fts_index.py:559-667` (`FTSIndex.search`)
- Test: `tests/test_fts_index.py` (extend) + new `tests/test_fts_snippet.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_fts_snippet.py`:

```python
"""Tests for FTS5 snippet() projection in FTSIndex.search."""

from __future__ import annotations

from markdown_vault_mcp.fts_index import FTSIndex
from markdown_vault_mcp.scanner import HeadingChunker, parse_note


def _upsert(tmp_path, fts: FTSIndex, name: str, body: str) -> None:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    fts.upsert_note(parse_note(p, tmp_path, HeadingChunker()))


def test_snippet_words_zero_returns_full_content(tmp_path):
    """snippet_words=0 (or None) returns the full chunk content."""
    fts = FTSIndex(db_path=":memory:")
    body = "# A\n" + "alpha " * 50 + "needle " + "alpha " * 50 + "\n"
    _upsert(tmp_path, fts, "doc.md", body)

    [r] = fts.search("needle", limit=10, snippet_words=0)
    # Full chunk: ~101 words.
    assert "alpha alpha" in r.content
    assert len(r.content.split()) > 50


def test_snippet_words_caps_returned_text(tmp_path):
    """snippet_words=20 returns roughly 20 tokens centered on the match."""
    fts = FTSIndex(db_path=":memory:")
    body = "# A\n" + "alpha " * 100 + "needle " + "alpha " * 100 + "\n"
    _upsert(tmp_path, fts, "doc.md", body)

    [r] = fts.search("needle", limit=10, snippet_words=20)
    assert "needle" in r.content
    assert len(r.content.split()) <= 30  # 20 + ellipsis slack


def test_snippet_includes_ellipsis_marker_when_truncated(tmp_path):
    """Truncated snippets include the … marker."""
    fts = FTSIndex(db_path=":memory:")
    body = "# A\n" + "alpha " * 200 + "needle " + "alpha " * 200 + "\n"
    _upsert(tmp_path, fts, "doc.md", body)

    [r] = fts.search("needle", limit=10, snippet_words=10)
    assert "…" in r.content


def test_chunk_count_populated_on_fts_result(tmp_path):
    """FTSResult exposes the parent doc's chunk_count."""
    fts = FTSIndex(db_path=":memory:")
    body = "# A\nalpha needle\n## B\nbeta\n## C\ngamma\n"
    _upsert(tmp_path, fts, "doc.md", body)

    results = fts.search("needle", limit=10)
    assert results[0].chunk_count >= 1
    assert results[0].chunk_count == fts._conn.execute(
        "SELECT chunk_count FROM documents WHERE path = 'doc.md'"
    ).fetchone()["chunk_count"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fts_snippet.py -v`
Expected: FAIL — `TypeError: search() got an unexpected keyword argument 'snippet_words'` (and `AttributeError: 'FTSResult' object has no attribute 'chunk_count'` once that one runs).

- [ ] **Step 3: Add `chunk_count` to `FTSResult`**

In `src/markdown_vault_mcp/types.py`, find `FTSResult` (around line 96) and add a field:

```python
@dataclass
class FTSResult:
    """A raw search result from the FTS5 index layer.

    Attributes:
        path: Relative path of the document containing this chunk.
        title: Document title.
        folder: Parent folder path.
        heading: Section heading this chunk falls under, or ``None``.
        content: Matched chunk text — full chunk by default; truncated to a
            tokenizer-aware snippet when ``snippet_words`` is passed to the
            search call.
        score: BM25 relevance score (higher is better).
        chunk_count: Total number of chunks belonging to the parent document.
    """

    path: str
    title: str
    folder: str
    heading: str | None
    content: str
    score: float
    chunk_count: int = 1
```

- [ ] **Step 4: Add `snippet_words` parameter to `FTSIndex.search`**

In `src/markdown_vault_mcp/fts_index.py`, edit `search` (lines 559-667):

```python
    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        folder: str | None = None,
        filters: dict[str, str] | None = None,
        snippet_words: int | None = None,
    ) -> list[FTSResult]:
        """Full-text search using BM25 ranking.

        Args:
            query: FTS5 query string.
            limit: Maximum number of results to return.
            folder: If provided, only return documents whose ``folder``
                starts with this string.
            filters: Dict of ``{tag_key: tag_value}`` pairs (AND semantics).
            snippet_words: When set to a positive integer, returned
                ``content`` is replaced with FTS5's ``snippet()`` of the
                matched content column, sized to approximately this many
                tokens. ``None`` or ``0`` returns the full chunk.

        Returns:
            List of :class:`~markdown_vault_mcp.types.FTSResult` ordered by
            descending BM25 score.
        """
        # Build tag subquery filters (one per entry, ANDed).
        tag_clauses: list[str] = []
        tag_params: list[str] = []
        if filters:
            for key, value in filters.items():
                tag_clauses.append(
                    "d.id IN ("
                    "  SELECT document_id FROM document_tags"
                    "  WHERE tag_key = ? AND tag_value = ?"
                    ")"
                )
                tag_params.extend([key, value])

        folder_clause = ""
        folder_params: list[str] = []
        if folder is not None:
            escaped = _escape_like(folder)
            folder_clause = "AND (d.folder = ? OR d.folder LIKE ? ESCAPE '\\')"
            folder_params = [folder, escaped + "/%"]

        tag_filter_sql = ""
        if tag_clauses:
            tag_filter_sql = "AND " + " AND ".join(tag_clauses)

        # column index 4 is the 'content' column in
        #   notes_fts USING fts5(path, title, folder, heading, content, ...)
        if snippet_words and snippet_words > 0:
            content_expr = "snippet(notes_fts, 4, '', '', '…', ?) AS content"
            snippet_params: list[object] = [snippet_words]
        else:
            content_expr = "f.content AS content"
            snippet_params = []

        sql = f"""
            SELECT
                f.path,
                d.title,
                d.folder,
                f.heading,
                {content_expr},
                ABS(f.rank) AS score,
                d.chunk_count AS chunk_count
            FROM notes_fts f
            JOIN documents d ON d.path = f.path
            WHERE notes_fts MATCH ?
              {folder_clause}
              {tag_filter_sql}
            ORDER BY score DESC
            LIMIT ?
        """

        if not query:
            return []

        params: list[object] = [
            *snippet_params,
            query,
            *folder_params,
            *tag_params,
            limit,
        ]
        logger.debug(
            "FTS search: query=%r folder=%r filters=%r limit=%d snippet_words=%r",
            query,
            folder,
            filters,
            limit,
            snippet_words,
        )
        try:
            cur = self._conn.execute(sql, params)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if (
                "fts5" in msg
                or "syntax error" in msg
                or "no such column" in msg
                or "unterminated" in msg
            ):
                logger.debug("FTS search: malformed query %r — %s", query, exc)
                return []
            raise
        rows = cur.fetchall()
        logger.debug("FTS search: %d results for query=%r", len(rows), query)

        results: list[FTSResult] = []
        for row in rows:
            results.append(
                FTSResult(
                    path=row["path"],
                    title=row["title"],
                    folder=row["folder"],
                    heading=row["heading"] or None,
                    content=row["content"],
                    score=row["score"],
                    chunk_count=row["chunk_count"],
                )
            )
        return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_fts_snippet.py tests/test_fts_index.py -v`
Expected: PASS.

- [ ] **Step 6: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/fts_index.py src/markdown_vault_mcp/types.py tests/test_fts_snippet.py
git commit -m "feat(fts): snippet_words projection and chunk_count on FTSResult

FTSIndex.search now accepts snippet_words; when set, returned
content is FTS5's tokenizer-aware snippet() of the matched chunk
instead of the full text. Each FTSResult also exposes the parent
document's chunk_count for downstream length-downweight ranking."
```

---

## Task 5: `_apply_length_downweight` helper

**Goal:** A reusable helper that adjusts a result list's scores by `score / (1 + alpha * log(chunk_count))` and re-sorts. Pure function on a list — easy to unit-test in isolation.

**Files:**
- Modify: `src/markdown_vault_mcp/managers/search.py:54+` (add helper near top of `SearchManager`)
- Test: `tests/test_search_length_downweight.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_search_length_downweight.py`:

```python
"""Tests for the per-channel length-downweight helper."""

from __future__ import annotations

import math
from dataclasses import dataclass

from markdown_vault_mcp.managers.search import _apply_length_downweight


@dataclass
class _Row:
    """Stand-in for either an FTSResult or a vector-search dict."""

    path: str
    score: float
    chunk_count: int


def test_alpha_zero_is_identity():
    rows = [_Row("a.md", 1.0, 10), _Row("b.md", 0.5, 1)]
    out = _apply_length_downweight(rows, alpha=0.0)
    assert [r.path for r in out] == ["a.md", "b.md"]
    assert out[0].score == 1.0


def test_long_doc_slides_down_with_positive_alpha():
    """A 10-chunk doc and a 1-chunk doc with equal raw scores: 1-chunk wins."""
    rows = [_Row("long.md", 1.0, 10), _Row("short.md", 1.0, 1)]
    out = _apply_length_downweight(rows, alpha=0.25)
    assert [r.path for r in out] == ["short.md", "long.md"]
    assert out[1].score == 1.0 / (1 + 0.25 * math.log(10))


def test_short_doc_unchanged_for_chunk_count_one():
    """log(1) = 0, so chunk_count=1 is unaffected by any alpha."""
    rows = [_Row("only.md", 0.7, 1)]
    out = _apply_length_downweight(rows, alpha=10.0)
    assert out[0].score == 0.7


def test_higher_alpha_pushes_long_doc_further_down():
    long10 = _Row("L.md", 1.0, 10)
    short = _Row("S.md", 0.95, 1)
    out_low = _apply_length_downweight([long10, short], alpha=0.1)
    out_high = _apply_length_downweight([long10, short], alpha=2.0)
    # At low alpha, L.md still ranks first; at high alpha, S.md wins.
    assert out_low[0].path == "L.md"
    assert out_high[0].path == "S.md"


def test_score_recomputation_does_not_mutate_input():
    rows = [_Row("a.md", 1.0, 10)]
    _ = _apply_length_downweight(rows, alpha=0.5)
    # Original list elements are not mutated in place.
    assert rows[0].score == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_search_length_downweight.py -v`
Expected: FAIL — `ImportError: cannot import name '_apply_length_downweight'`.

- [ ] **Step 3: Implement the helper**

In `src/markdown_vault_mcp/managers/search.py`, just after the imports/constants block (around line 50, before `class SearchManager`), add:

```python
import math
from dataclasses import replace as _dc_replace
from typing import TypeVar


_RankT = TypeVar("_RankT")


def _apply_length_downweight(rows: list[_RankT], *, alpha: float) -> list[_RankT]:
    """Re-rank ``rows`` by ``score / (1 + alpha * log(chunk_count))``.

    Each element must expose ``score: float`` and ``chunk_count: int``
    attributes (works for both :class:`FTSResult` and dicts via
    duck-typed attribute access on dataclass-like rows; for plain dicts
    the caller should adapt to a tiny shim).

    Returns a new list sorted by descending adjusted score; input is not
    mutated.
    """
    if alpha <= 0 or not rows:
        return list(rows)

    adjusted: list[tuple[_RankT, float]] = []
    for row in rows:
        chunk_count = max(1, getattr(row, "chunk_count", 1))
        # log(1) = 0 → factor = 1 → no change for short docs.
        factor = 1.0 + alpha * math.log(chunk_count)
        new_score = getattr(row, "score") / factor
        # dataclasses.replace works for FTSResult; for non-frozen ones, a
        # shallow copy with attribute set is fine. We avoid mutating input.
        try:
            new_row = _dc_replace(row, score=new_score)  # type: ignore[type-var]
        except TypeError:
            # Not a dataclass — fall back to a plain attribute write on a copy.
            import copy as _copy

            new_row = _copy.copy(row)
            new_row.score = new_score  # type: ignore[attr-defined]
        adjusted.append((new_row, new_score))

    adjusted.sort(key=lambda t: t[1], reverse=True)
    return [r for r, _ in adjusted]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_search_length_downweight.py -v`
Expected: PASS.

- [ ] **Step 5: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/managers/search.py tests/test_search_length_downweight.py
git commit -m "feat(search): per-channel length-downweight helper

Pure helper that re-ranks a result list by
score / (1 + alpha * log(chunk_count)). alpha=0 is identity;
log(1)=0 leaves single-chunk docs unaffected at any alpha. Input
list is not mutated."
```

---

## Task 6: `_apply_chunks_per_doc_cap` helper

**Goal:** Drop excess same-doc chunks from a ranked list, keeping at most N per `path` until `limit` results are collected.

**Files:**
- Modify: `src/markdown_vault_mcp/managers/search.py` (add helper next to Task 5's)
- Test: `tests/test_search_chunks_per_doc_cap.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_search_chunks_per_doc_cap.py`:

```python
"""Tests for the per-document result cap helper."""

from __future__ import annotations

from dataclasses import dataclass

from markdown_vault_mcp.managers.search import _apply_chunks_per_doc_cap


@dataclass
class _Row:
    path: str
    score: float


def test_cap_one_keeps_first_per_path():
    rows = [
        _Row("a.md", 1.0),
        _Row("a.md", 0.9),
        _Row("b.md", 0.8),
        _Row("a.md", 0.7),
    ]
    out = _apply_chunks_per_doc_cap(rows, n=1, limit=10)
    assert [r.path for r in out] == ["a.md", "b.md"]


def test_cap_two_keeps_first_two_per_path():
    rows = [
        _Row("a.md", 1.0),
        _Row("a.md", 0.9),
        _Row("a.md", 0.8),
        _Row("b.md", 0.7),
    ]
    out = _apply_chunks_per_doc_cap(rows, n=2, limit=10)
    assert [r.path for r in out] == ["a.md", "a.md", "b.md"]


def test_cap_truncates_to_limit():
    rows = [_Row("a.md", 1.0), _Row("b.md", 0.9), _Row("c.md", 0.8)]
    out = _apply_chunks_per_doc_cap(rows, n=10, limit=2)
    assert len(out) == 2


def test_cap_preserves_order_of_remaining_results():
    rows = [
        _Row("a.md", 1.0),
        _Row("a.md", 0.9),  # dropped
        _Row("b.md", 0.8),
        _Row("c.md", 0.7),
    ]
    out = _apply_chunks_per_doc_cap(rows, n=1, limit=10)
    assert [r.score for r in out] == [1.0, 0.8, 0.7]


def test_cap_empty_list_returns_empty():
    assert _apply_chunks_per_doc_cap([], n=2, limit=10) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_search_chunks_per_doc_cap.py -v`
Expected: FAIL — `ImportError: cannot import name '_apply_chunks_per_doc_cap'`.

- [ ] **Step 3: Implement the helper**

In `src/markdown_vault_mcp/managers/search.py`, just after `_apply_length_downweight`, add:

```python
def _apply_chunks_per_doc_cap(
    rows: list[_RankT], *, n: int, limit: int
) -> list[_RankT]:
    """Walk ``rows`` in order; keep at most ``n`` rows per ``path``; stop at ``limit``.

    Each element must expose a ``path`` attribute. Order is preserved.
    """
    if n < 1:
        raise ValueError(f"chunks_per_doc cap must be >= 1, got {n}")
    out: list[_RankT] = []
    counts: dict[str, int] = {}
    for row in rows:
        path = getattr(row, "path")
        if counts.get(path, 0) >= n:
            continue
        counts[path] = counts.get(path, 0) + 1
        out.append(row)
        if len(out) >= limit:
            break
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_search_chunks_per_doc_cap.py -v`
Expected: PASS.

- [ ] **Step 5: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/managers/search.py tests/test_search_chunks_per_doc_cap.py
git commit -m "feat(search): per-document result cap helper

Walks a ranked list in order and keeps at most n results per path,
stopping once limit results have been collected. Order of surviving
results is preserved."
```

---

## Task 7: `_compute_snippet_for_semantic` helper (word-window scan)

**Goal:** When a result was matched only via cosine similarity, compute a snippet by sliding a `snippet_words`-wide window across the chunk and picking the window with the highest count of query tokens. Falls back to first-N words when no overlap.

**Files:**
- Modify: `src/markdown_vault_mcp/managers/search.py` (add helper next to Tasks 5–6)
- Test: `tests/test_search_snippets.py` (new — additional cases follow in later tasks)

- [ ] **Step 1: Write failing tests**

Create `tests/test_search_snippets.py`:

```python
"""Tests for snippet generation in SearchManager."""

from __future__ import annotations

from markdown_vault_mcp.managers.search import _compute_snippet_for_semantic


def test_snippet_words_zero_returns_full_content():
    content = " ".join(f"word{i}" for i in range(50))
    assert _compute_snippet_for_semantic(content, "anything", snippet_words=0) == content


def test_window_centered_on_densest_query_match():
    """Slide a 10-word window; pick the one with most query tokens."""
    content = (
        " ".join(["filler"] * 20)
        + " needle midway needle "
        + " ".join(["filler"] * 20)
    )
    out = _compute_snippet_for_semantic(content, "needle", snippet_words=10)
    assert "needle" in out
    assert len(out.split()) <= 12  # 10 + slack for ellipses


def test_no_overlap_falls_back_to_first_n_words():
    content = " ".join(f"word{i}" for i in range(50))
    out = _compute_snippet_for_semantic(content, "completely-unrelated-token", snippet_words=10)
    assert out.split()[0] == "word0"
    assert len(out.split()) <= 12


def test_short_chunk_returned_intact():
    content = "five word chunk only here"
    out = _compute_snippet_for_semantic(content, "chunk", snippet_words=200)
    assert out == content


def test_query_tokenization_is_case_insensitive():
    content = (
        " ".join(["filler"] * 20)
        + " Needle hit Needle "
        + " ".join(["filler"] * 20)
    )
    out = _compute_snippet_for_semantic(content, "NEEDLE", snippet_words=10)
    assert "Needle" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_search_snippets.py -v`
Expected: FAIL — `ImportError: cannot import name '_compute_snippet_for_semantic'`.

- [ ] **Step 3: Implement the helper**

In `src/markdown_vault_mcp/managers/search.py`, after `_apply_chunks_per_doc_cap`, add:

```python
import re as _re


_QUERY_TOKEN_RE = _re.compile(r"[A-Za-z0-9]+")


def _compute_snippet_for_semantic(
    content: str, query: str, *, snippet_words: int
) -> str:
    """Pick a ``snippet_words``-wide window from ``content``.

    Returns the full content when ``snippet_words`` is 0, when the chunk is
    already shorter, or as a fallback when no query tokens overlap (in which
    case the first ``snippet_words`` words are returned with a trailing
    ellipsis).

    Uses simple case-insensitive substring matching on alphanumeric tokens.
    """
    if snippet_words <= 0:
        return content

    words = content.split()
    if len(words) <= snippet_words:
        return content

    query_tokens = {t.lower() for t in _QUERY_TOKEN_RE.findall(query)}
    if not query_tokens:
        return " ".join(words[:snippet_words]) + " …"

    # Score each window position by query-token count.
    lower_words = [_QUERY_TOKEN_RE.sub("", w).lower() or w.lower() for w in words]
    # Build initial window count.
    best_start = 0
    best_score = sum(1 for w in lower_words[:snippet_words] if w in query_tokens)
    cur_score = best_score
    for i in range(1, len(words) - snippet_words + 1):
        if lower_words[i - 1] in query_tokens:
            cur_score -= 1
        if lower_words[i + snippet_words - 1] in query_tokens:
            cur_score += 1
        if cur_score > best_score:
            best_score = cur_score
            best_start = i

    if best_score == 0:
        # No literal overlap anywhere — fall back to first-N words.
        return " ".join(words[:snippet_words]) + " …"

    snippet = " ".join(words[best_start : best_start + snippet_words])
    if best_start > 0:
        snippet = "… " + snippet
    if best_start + snippet_words < len(words):
        snippet = snippet + " …"
    return snippet
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_search_snippets.py -v`
Expected: PASS (all five tests).

- [ ] **Step 5: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/managers/search.py tests/test_search_snippets.py
git commit -m "feat(search): word-window snippet helper for semantic-only hits

Slides a snippet_words-wide window across the chunk and picks the
window with the most case-insensitive query-token matches. Falls back
to the first N words with an ellipsis when no overlap exists. Used by
pure-semantic search results and semantic-only hits in hybrid mode."
```

---

## Task 8: Wire pipeline through `_keyword_search`

**Goal:** Apply length downweight, per-doc cap, and snippet projection in keyword mode.

**Files:**
- Modify: `src/markdown_vault_mcp/managers/search.py` — `_keyword_search`, `SearchManager.__init__`
- Test: `tests/test_managers_search.py` (extend with new keyword-mode tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_managers_search.py`:

```python
def test_keyword_search_applies_chunks_per_doc_cap(search_mgr):
    """Two chunks from the same doc cannot both occupy the top-N."""
    # alpha.md has only one chunk in the search_vault fixture, so synthesize
    # a fixture scenario via a fresh manager.
    # This test relies on the broader integration test in
    # tests/test_search_pipeline_integration.py — here we just assert the
    # manager honours the chunks_per_doc parameter.
    results = search_mgr.search("world", mode="keyword", chunks_per_doc=1, limit=10)
    paths_in_top = [r.path for r in results]
    assert len(set(paths_in_top)) == len(paths_in_top)


def test_keyword_search_returns_snippet(search_mgr):
    """When snippet_words is set, content is shorter than the full chunk."""
    long_results = search_mgr.search("world", mode="keyword", snippet_words=0, limit=10)
    short_results = search_mgr.search("world", mode="keyword", snippet_words=3, limit=10)
    assert all(
        len(s.content.split()) <= len(l.content.split())
        for s, l in zip(short_results, long_results, strict=False)
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_managers_search.py -k 'chunks_per_doc_cap or keyword_search_returns_snippet' -v`
Expected: FAIL — `TypeError: search() got an unexpected keyword argument 'chunks_per_doc'`.

- [ ] **Step 3: Add ranking config to `SearchManager.__init__`**

In `src/markdown_vault_mcp/managers/search.py`, extend the `__init__` signature with the four new knobs (with sensible defaults so callers that omit them keep working):

```python
    def __init__(
        self,
        fts: FTSIndex,
        source_dir: Path,
        *,
        embeddings_path: Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        indexed_frontmatter_fields: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        attachment_extensions: list[str] | None = None,
        link_manager: LinkManager | None = None,
        flush_embeddings: Callable[[], None] | None = None,
        rebuild_embeddings: Callable[[], None] | None = None,
        chunks_per_doc: int = 2,
        snippet_words: int = 200,
        length_downweight_alpha: float = 0.25,
    ) -> None:
        ...
        # store the new fields
        self._chunks_per_doc = chunks_per_doc
        self._snippet_words = snippet_words
        self._length_downweight_alpha = length_downweight_alpha
```

- [ ] **Step 4: Add the new params to `search()` and rewrite `_keyword_search`**

Rework the public `search()` to accept and thread `chunks_per_doc` and `snippet_words` overrides:

```python
    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        mode: Literal["keyword", "semantic", "hybrid"] = "keyword",
        filters: dict[str, str] | None = None,
        folder: str | None = None,
        chunks_per_doc: int | None = None,
        snippet_words: int | None = None,
    ) -> list[SearchResult]:
        eff_cap = chunks_per_doc if chunks_per_doc is not None else self._chunks_per_doc
        eff_snip = snippet_words if snippet_words is not None else self._snippet_words

        if mode == "keyword":
            return self._keyword_search(
                query,
                limit=limit,
                filters=filters,
                folder=folder,
                chunks_per_doc=eff_cap,
                snippet_words=eff_snip,
            )

        if mode == "semantic":
            self._require_vectors()
            return self._semantic_search(
                query,
                limit=limit,
                filters=filters,
                folder=folder,
                chunks_per_doc=eff_cap,
                snippet_words=eff_snip,
            )

        # hybrid
        self._require_vectors()
        return self._hybrid_search(
            query,
            limit=limit,
            filters=filters,
            folder=folder,
            chunks_per_doc=eff_cap,
            snippet_words=eff_snip,
        )
```

Then rewrite `_keyword_search`:

```python
    def _keyword_search(
        self,
        query: str,
        *,
        limit: int,
        filters: dict[str, str] | None,
        folder: str | None,
        chunks_per_doc: int,
        snippet_words: int,
    ) -> list[SearchResult]:
        # Widen candidate pool so the cap doesn't starve us of `limit` rows.
        candidate_limit = max(limit * (chunks_per_doc + 4), 50)

        # NOTE: snippet projection is applied inside FTS only AFTER the cap,
        # because we don't want to compute snippets for candidates that get
        # dropped. So fetch raw content first, downweight, cap, then re-fetch
        # snippets for the survivors via a second FTS query.
        raw = self._fts.search(
            query,
            limit=candidate_limit,
            filters=filters,
            folder=folder,
            snippet_words=None,  # full content for downweight scoring
        )
        downweighted = _apply_length_downweight(
            raw, alpha=self._length_downweight_alpha
        )
        capped = _apply_chunks_per_doc_cap(
            downweighted, n=chunks_per_doc, limit=limit
        )

        # Snippet projection for the survivors.
        if snippet_words > 0:
            snippets_by_key = self._fetch_snippet_map(
                query, capped, snippet_words=snippet_words
            )
        else:
            snippets_by_key = {}

        return [
            SearchResult(
                path=r.path,
                title=r.title,
                folder=r.folder,
                heading=r.heading,
                content=snippets_by_key.get((r.path, r.heading), r.content),
                score=r.score,
                search_type="keyword",
                frontmatter=self._get_frontmatter(r.path),
            )
            for r in capped
        ]

    def _fetch_snippet_map(
        self,
        query: str,
        survivors: list[FTSResult],
        *,
        snippet_words: int,
    ) -> dict[tuple[str, str | None], str]:
        """Re-query FTS with snippet projection, restricted to survivor paths.

        Returns a ``{(path, heading): snippet}`` map. Falls back to the
        survivor's own ``content`` field when an FTS row cannot be located
        (e.g. because the cap kept a downweighted-only candidate that BM25
        ranked outside its top-N).
        """
        if not survivors:
            return {}
        # We use a single FTS5 search with a generous limit and filter by
        # survivor paths in Python. FTS5 does not support IN(?,?,...) on the
        # path column directly without a JOIN, but JOIN expansion is more
        # complex than the post-filter and the survivor count is small.
        candidate_n = max(len(survivors) * 4, 20)
        rows = self._fts.search(
            query,
            limit=candidate_n,
            snippet_words=snippet_words,
        )
        wanted = {(s.path, s.heading) for s in survivors}
        return {
            (r.path, r.heading): r.content for r in rows if (r.path, r.heading) in wanted
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_managers_search.py -v`
Expected: PASS (existing tests + the two new ones).

- [ ] **Step 6: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/managers/search.py tests/test_managers_search.py
git commit -m "feat(search): wire pipeline through keyword mode

_keyword_search now applies length downweight, per-doc cap, and FTS5
snippet projection. snippet_words=0 retains today's full-content
behaviour; default 200-word snippets centered on BM25-matched terms
when set. Candidate pool is widened by chunks_per_doc + 4."
```

---

## Task 9: Wire pipeline through `_semantic_search`

**Goal:** Same pipeline for pure-semantic mode; the snippet stage uses the Python word-window helper from Task 7.

**Files:**
- Modify: `src/markdown_vault_mcp/managers/search.py` — `_semantic_search`
- Test: extend `tests/test_managers_search.py` and `tests/test_search_snippets.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_managers_search.py`:

```python
def test_semantic_search_applies_chunks_per_doc_cap_and_snippet(
    search_mgr_with_embeddings,  # fixture — see below if missing
):
    """Semantic mode honours chunks_per_doc and snippet_words."""
    results = search_mgr_with_embeddings.search(
        "world",
        mode="semantic",
        chunks_per_doc=1,
        snippet_words=5,
        limit=10,
    )
    paths = [r.path for r in results]
    assert len(set(paths)) == len(paths)
    assert all(len(r.content.split()) <= 10 for r in results)
```

If a `search_mgr_with_embeddings` fixture does not yet exist in `tests/test_managers_search.py`, define it locally (in the same file, near the top of the test). Otherwise, reuse the existing one and skip this step.

```python
@pytest.fixture()
def search_mgr_with_embeddings(search_vault: Path) -> SearchManager:
    """Build a SearchManager with a deterministic mock embedding provider."""
    from tests.conftest import MockEmbeddingProvider  # standard fixture
    from markdown_vault_mcp.vector_index import VectorIndex

    fts = FTSIndex(db_path=":memory:", indexed_frontmatter_fields=["tags"])
    for note in scan_directory(search_vault):
        fts.upsert_note(note)
    fts.resolve_vault_wikilinks()
    provider = MockEmbeddingProvider(dim=8)
    embeddings_path = search_vault / "embeddings"
    vectors = VectorIndex(provider)
    for note in scan_directory(search_vault):
        vectors.add_document(note)
    vectors.save(embeddings_path)
    mgr = SearchManager(
        fts=fts,
        source_dir=search_vault,
        embeddings_path=embeddings_path,
        embedding_provider=provider,
        indexed_frontmatter_fields=["tags"],
    )
    mgr._vectors = vectors
    return mgr
```

(Adjust to match the actual `MockEmbeddingProvider` import location; `tests/conftest.py` already exports it per the project memory.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_managers_search.py -k semantic_search_applies -v`
Expected: FAIL — same `chunks_per_doc` keyword-arg error or `snippet_words` not honoured.

- [ ] **Step 3: Rewrite `_semantic_search`**

```python
    def _semantic_search(
        self,
        query: str,
        *,
        limit: int,
        filters: dict[str, str] | None,
        folder: str | None,
        chunks_per_doc: int,
        snippet_words: int,
    ) -> list[SearchResult]:
        self._flush_embeddings()
        vectors = self._load_vectors()
        candidate_limit = max(limit * (chunks_per_doc + 4), 50)
        raw = vectors.search(query, limit=candidate_limit)

        # Materialise into row objects with score + chunk_count + heading attrs.
        # vectors.search returns dicts; we adapt to a small RowLike namespace.
        rows: list[_SemanticRow] = []
        for r in raw:
            if folder is not None:
                r_folder = r.get("folder", "")
                if r_folder != folder and not r_folder.startswith(folder + "/"):
                    continue
            if filters and not self._row_matches_filters(r["path"], filters):
                continue
            chunk_count = self._fts_chunk_count_for(r["path"])
            rows.append(
                _SemanticRow(
                    path=r["path"],
                    title=r["title"],
                    folder=r["folder"],
                    heading=r.get("heading"),
                    content=r["content"],
                    score=r["score"],
                    chunk_count=chunk_count,
                )
            )

        downweighted = _apply_length_downweight(
            rows, alpha=self._length_downweight_alpha
        )
        capped = _apply_chunks_per_doc_cap(
            downweighted, n=chunks_per_doc, limit=limit
        )

        return [
            SearchResult(
                path=r.path,
                title=r.title,
                folder=r.folder,
                heading=r.heading,
                content=_compute_snippet_for_semantic(
                    r.content, query, snippet_words=snippet_words
                ),
                score=r.score,
                search_type="semantic",
                frontmatter=self._get_frontmatter(r.path),
            )
            for r in capped
        ]
```

Add the supporting `_SemanticRow` dataclass and helpers near the top of the file:

```python
@dataclass
class _SemanticRow:
    """Adapter row for vector search results so they expose .score / .chunk_count."""

    path: str
    title: str
    folder: str
    heading: str | None
    content: str
    score: float
    chunk_count: int
```

And helpers on `SearchManager`:

```python
    def _fts_chunk_count_for(self, path: str) -> int:
        """Look up parent doc chunk_count from the FTS index, default 1."""
        row = self._fts._conn.execute(
            "SELECT chunk_count FROM documents WHERE path = ?", (path,)
        ).fetchone()
        return int(row["chunk_count"]) if row else 1

    def _row_matches_filters(self, path: str, filters: dict[str, str]) -> bool:
        note_row = self._fts.get_note(path)
        if note_row is None:
            return False
        fm_raw = note_row.get("frontmatter_json")
        fm: dict[str, Any] = {}
        if fm_raw:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                fm = json.loads(fm_raw)
        for key, value in filters.items():
            fm_val = fm.get(key)
            if fm_val is None:
                return False
            if isinstance(fm_val, list):
                if str(value) not in [str(v) for v in fm_val]:
                    return False
            else:
                if str(fm_val) != str(value):
                    return False
        return True
```

(The filter helper consolidates the duplicated logic that previously lived inline in both `_semantic_search` and `_hybrid_search`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_managers_search.py -v`
Expected: PASS.

- [ ] **Step 5: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/managers/search.py tests/test_managers_search.py
git commit -m "feat(search): wire pipeline through semantic mode

_semantic_search applies length downweight, per-doc cap, and word-
window snippet truncation. Chunk-count lookup uses the new
documents.chunk_count column. Filter logic consolidated into a
single helper used by semantic and hybrid modes."
```

---

## Task 10: Wire pipeline through `_hybrid_search`

**Goal:** RRF first, then cap on the merged list, then per-result snippet — FTS5 snippet for keyword-side hits, Python word-window for semantic-only hits.

**Files:**
- Modify: `src/markdown_vault_mcp/managers/search.py` — `_hybrid_search`
- Test: `tests/test_managers_search.py` (extend) + `tests/test_search_snippets.py` (extend)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_managers_search.py`:

```python
def test_hybrid_search_caps_per_doc_after_rrf(search_mgr_with_embeddings):
    results = search_mgr_with_embeddings.search(
        "world",
        mode="hybrid",
        chunks_per_doc=1,
        snippet_words=5,
        limit=10,
    )
    paths = [r.path for r in results]
    assert len(set(paths)) == len(paths)


def test_hybrid_search_uses_fts_snippet_for_keyword_hits(search_mgr_with_embeddings):
    """Results that show up on the keyword side should carry FTS5 ellipsis markers
    when truncated; semantic-only fallbacks may also include ellipses but use the
    Python helper."""
    results = search_mgr_with_embeddings.search(
        "world",
        mode="hybrid",
        chunks_per_doc=2,
        snippet_words=3,
        limit=10,
    )
    # Just assert size bound; concrete tokenizer behaviour is exercised in
    # tests/test_fts_snippet.py.
    assert all(len(r.content.split()) <= 8 for r in results)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_managers_search.py -k hybrid -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `_hybrid_search`**

```python
    def _hybrid_search(
        self,
        query: str,
        *,
        limit: int,
        filters: dict[str, str] | None,
        folder: str | None,
        chunks_per_doc: int,
        snippet_words: int,
    ) -> list[SearchResult]:
        self._flush_embeddings()
        candidate_limit = max(limit * (chunks_per_doc + 4), 50)

        fts_results = self._fts.search(
            query,
            limit=candidate_limit,
            filters=filters,
            folder=folder,
            snippet_words=None,  # full content; snippet applied later
        )
        # Apply length downweight inside the keyword channel.
        fts_results = _apply_length_downweight(
            fts_results, alpha=self._length_downweight_alpha
        )

        vectors = self._load_vectors()
        vec_raw = vectors.search(query, limit=candidate_limit)
        vec_rows: list[_SemanticRow] = []
        for r in vec_raw:
            if folder is not None:
                r_folder = r.get("folder", "")
                if r_folder != folder and not r_folder.startswith(folder + "/"):
                    continue
            if filters and not self._row_matches_filters(r["path"], filters):
                continue
            vec_rows.append(
                _SemanticRow(
                    path=r["path"],
                    title=r["title"],
                    folder=r["folder"],
                    heading=r.get("heading"),
                    content=r["content"],
                    score=r["score"],
                    chunk_count=self._fts_chunk_count_for(r["path"]),
                )
            )
        vec_rows = _apply_length_downweight(
            vec_rows, alpha=self._length_downweight_alpha
        )

        # RRF fusion on adjusted-rank order.
        rrf_scores: dict[tuple[str, str | None], float] = {}
        chunk_meta: dict[tuple[str, str | None], dict[str, Any]] = {}
        keyword_keys: set[tuple[str, str | None]] = set()

        for rank, r in enumerate(fts_results, start=1):
            key = (r.path, r.heading)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
            keyword_keys.add(key)
            chunk_meta.setdefault(
                key,
                {
                    "path": r.path,
                    "title": r.title,
                    "folder": r.folder,
                    "heading": r.heading,
                    "content": r.content,
                    "search_type": "keyword",
                },
            )

        for rank, vr in enumerate(vec_rows, start=1):
            vkey = (vr.path, vr.heading)
            rrf_scores[vkey] = rrf_scores.get(vkey, 0.0) + 1.0 / (_RRF_K + rank)
            chunk_meta.setdefault(
                vkey,
                {
                    "path": vr.path,
                    "title": vr.title,
                    "folder": vr.folder,
                    "heading": vr.heading,
                    "content": vr.content,
                    "search_type": "semantic",
                },
            )

        # Sort merged keys by RRF score, then cap per path.
        sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)

        # Wrap in a tiny adapter so _apply_chunks_per_doc_cap can read .path.
        @dataclass
        class _CapRow:
            path: str
            heading: str | None
            score: float

        cap_input = [
            _CapRow(path=k[0], heading=k[1], score=rrf_scores[k]) for k in sorted_keys
        ]
        capped = _apply_chunks_per_doc_cap(
            cap_input, n=chunks_per_doc, limit=limit
        )

        # Resolve snippets:
        # - keyword-side hits: re-query FTS with snippet projection.
        # - semantic-only:    Python word-window.
        keyword_capped = [c for c in capped if (c.path, c.heading) in keyword_keys]
        snippet_map: dict[tuple[str, str | None], str] = {}
        if snippet_words > 0 and keyword_capped:
            survivor_fts_rows = [
                fts_r for fts_r in fts_results
                if (fts_r.path, fts_r.heading) in {(c.path, c.heading) for c in keyword_capped}
            ]
            snippet_map = self._fetch_snippet_map(
                query, survivor_fts_rows, snippet_words=snippet_words
            )

        out: list[SearchResult] = []
        for c in capped:
            key = (c.path, c.heading)
            meta = chunk_meta[key]
            if key in snippet_map:
                content = snippet_map[key]
            elif key in keyword_keys:
                # Keyword hit but snippet_words=0 or fetch failed → use raw chunk.
                content = meta["content"]
            else:
                content = _compute_snippet_for_semantic(
                    meta["content"], query, snippet_words=snippet_words
                )
            out.append(
                SearchResult(
                    path=meta["path"],
                    title=meta["title"],
                    folder=meta["folder"],
                    heading=meta["heading"],
                    content=content,
                    score=rrf_scores[key],
                    search_type=meta["search_type"],
                    frontmatter=self._get_frontmatter(meta["path"]),
                )
            )
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_managers_search.py -v`
Expected: PASS.

- [ ] **Step 5: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/managers/search.py tests/test_managers_search.py
git commit -m "feat(search): wire pipeline through hybrid mode

Per-channel length downweight, RRF fusion, then cap on merged sorted
list. Snippet projection uses FTS5 native snippet() for keyword-side
hits and the Python word-window helper for semantic-only hits."
```

---

## Task 11: `read(path, *, section=...)` extension

**Goal:** Recovery affordance for snippet-truncated `search` results — fetch the full chunk by `(path, heading)`.

**Files:**
- Modify: `src/markdown_vault_mcp/managers/document.py:225+` (`DocumentManager.read`)
- Test: `tests/test_documents_read_section.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_documents_read_section.py`:

```python
"""Tests for DocumentManager.read(path, section=...) section retrieval."""

from __future__ import annotations

import pytest

from markdown_vault_mcp.fts_index import FTSIndex
from markdown_vault_mcp.managers.document import DocumentManager
from markdown_vault_mcp.scanner import HeadingChunker, scan_directory


@pytest.fixture()
def doc_mgr(tmp_path):
    a = tmp_path / "a.md"
    a.write_text(
        "# A\n\nIntro body\n\n## Section One\n\nFirst section body\n\n"
        "## Section Two\n\nSecond section body\n",
        encoding="utf-8",
    )
    fts = FTSIndex(db_path=":memory:")
    chunker = HeadingChunker()
    for note in scan_directory(tmp_path, chunk_strategy=chunker):
        fts.upsert_note(note)
    return DocumentManager(fts=fts, source_dir=tmp_path, chunk_strategy=chunker)


def test_read_no_section_returns_full_file(doc_mgr):
    nc = doc_mgr.read("a.md")
    assert nc is not None
    assert "Section One" in nc.content
    assert "Section Two" in nc.content


def test_read_with_section_returns_only_that_chunk(doc_mgr):
    nc = doc_mgr.read("a.md", section="Section One")
    assert nc is not None
    assert "First section body" in nc.content
    assert "Second section body" not in nc.content


def test_read_unknown_section_raises(doc_mgr):
    with pytest.raises(ValueError, match="Section"):
        doc_mgr.read("a.md", section="No Such Heading")


def test_read_empty_section_raises(doc_mgr):
    with pytest.raises(ValueError):
        doc_mgr.read("a.md", section="   ")


def test_read_returns_none_when_path_unknown(doc_mgr):
    assert doc_mgr.read("missing.md") is None
    # With section, missing path also raises (cannot resolve section in
    # nonexistent doc).
    with pytest.raises(ValueError):
        doc_mgr.read("missing.md", section="Anything")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_documents_read_section.py -v`
Expected: FAIL — `TypeError: read() got an unexpected keyword argument 'section'`.

- [ ] **Step 3: Extend `DocumentManager.read`**

In `src/markdown_vault_mcp/managers/document.py`, replace the existing `read` (around line 225) with:

```python
    def read(
        self, path: str, *, section: str | None = None
    ) -> NoteContent | None:
        """Read a document or a single section from disk.

        Args:
            path: Relative document path (e.g. ``"Journal/note.md"``).
            section: When provided, return only the chunk whose heading
                matches *section* exactly. ``None`` returns the whole
                document (today's behaviour).

        Returns:
            A :class:`~markdown_vault_mcp.types.NoteContent`, or ``None`` if
            the file does not exist (whole-document mode).

        Raises:
            ValueError: When *section* is provided and is empty / whitespace,
                or when the document does not contain a chunk with that
                heading. (Path-not-found also raises in section mode rather
                than returning ``None``, since "no document" implies "no
                section".)
        """
        if section is not None:
            if not section.strip():
                raise ValueError(
                    "section must be a non-empty heading or None"
                )
            return self._read_section(path, section.strip())

        abs_path = (self._source_dir / path).resolve()
        if not abs_path.is_relative_to(self._source_dir.resolve()):
            return None
        if not abs_path.is_file():
            return None

        try:
            note = parse_note(abs_path, self._source_dir, self._chunk_strategy)
        except (UnicodeDecodeError, OSError) as exc:
            logger.warning("read(%s): could not parse file — %s", path, exc)
            return None

        raw_content = abs_path.read_text(encoding="utf-8")
        etag = note.content_hash
        folder = str(Path(path).parent)
        if folder == ".":
            folder = ""

        return NoteContent(
            path=note.path,
            title=note.title,
            folder=folder,
            content=raw_content,
            frontmatter=note.frontmatter,
            modified_at=note.modified_at,
            etag=etag,
        )

    def _read_section(self, path: str, heading: str) -> NoteContent:
        """Return a NoteContent containing only the named section's chunk."""
        doc_row = self._fts.get_note(path)
        if doc_row is None:
            raise ValueError(
                f"Section '{heading}' not found in document {path}: "
                "document is not indexed or does not exist"
            )
        section_row = self._fts._conn.execute(
            """
            SELECT s.content, s.heading, s.heading_level
            FROM sections s
            JOIN documents d ON d.id = s.document_id
            WHERE d.path = ? AND s.heading = ?
            ORDER BY s.start_line ASC
            LIMIT 1
            """,
            (path, heading),
        ).fetchone()
        if section_row is None:
            raise ValueError(
                f"Section '{heading}' not found in document {path}"
            )

        folder = str(Path(path).parent)
        if folder == ".":
            folder = ""

        return NoteContent(
            path=path,
            title=doc_row["title"],
            folder=folder,
            content=section_row["content"],
            frontmatter={},  # section reads do not synthesise frontmatter
            modified_at=doc_row["modified_at"],
            etag="",  # ETag is whole-file; not meaningful for a section
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_documents_read_section.py tests/test_managers_document.py -v`
Expected: PASS.

- [ ] **Step 5: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/managers/document.py tests/test_documents_read_section.py
git commit -m "feat(document): read(path, section=...) for chunk recovery

Optional section parameter on DocumentManager.read returns just the
named chunk's content, looked up by exact heading match in the FTS
sections table. Empty/whitespace section or unknown heading raises
ValueError. section=None preserves today's whole-document behaviour."
```

---

## Task 12: Wire config knobs into `Collection` and `HeadingChunker`

**Goal:** Plumb the four new config fields end-to-end so server startup uses them.

**Files:**
- Modify: `src/markdown_vault_mcp/collection.py` — wherever `SearchManager` and `HeadingChunker` are constructed; wherever `to_collection_kwargs()` consumes the config.
- Test: extend `tests/test_collection.py` and `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_collection.py`:

```python
def test_collection_constructs_chunker_with_max_chunk_words(tmp_path):
    """Collection plumbs max_chunk_words into HeadingChunker."""
    from markdown_vault_mcp.collection import Collection
    from markdown_vault_mcp.scanner import HeadingChunker

    coll = Collection(source_dir=tmp_path, max_chunk_words=250)
    assert isinstance(coll._chunk_strategy, HeadingChunker)
    assert coll._chunk_strategy.max_chunk_words == 250


def test_collection_search_honours_default_chunks_per_doc(tmp_path):
    """A Collection-level search uses chunks_per_doc=2 by default."""
    from markdown_vault_mcp.collection import Collection

    # Build a tiny vault with one multi-section doc + a few singletons.
    (tmp_path / "long.md").write_text(
        "# Top\n## A\nworld a\n## B\nworld b\n## C\nworld c\n",
        encoding="utf-8",
    )
    (tmp_path / "short.md").write_text("# Short\nworld\n", encoding="utf-8")
    coll = Collection(source_dir=tmp_path)
    coll.build_index()
    results = coll.search("world", mode="keyword", limit=10)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.path] = counts.get(r.path, 0) + 1
    assert counts.get("long.md", 0) <= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_collection.py -k 'collection_constructs_chunker_with_max_chunk_words or honours_default_chunks_per_doc' -v`
Expected: FAIL.

- [ ] **Step 3: Plumb config knobs through `Collection`**

In `src/markdown_vault_mcp/collection.py`, extend `__init__` to accept the four knobs (with the same defaults as the spec) and pass them to `SearchManager` and `HeadingChunker`. Sketch:

```python
    def __init__(
        self,
        source_dir: Path,
        *,
        # ... existing params ...
        chunks_per_doc: int = 2,
        snippet_words: int = 200,
        length_downweight_alpha: float = 0.25,
        max_chunk_words: int = 400,
    ) -> None:
        ...
        self._chunk_strategy = HeadingChunker(max_chunk_words=max_chunk_words)
        ...
        self._search = SearchManager(
            fts=...,
            source_dir=source_dir,
            ...,
            chunks_per_doc=chunks_per_doc,
            snippet_words=snippet_words,
            length_downweight_alpha=length_downweight_alpha,
        )
```

- [ ] **Step 4: Update `CollectionConfig.to_collection_kwargs()`**

Find `to_collection_kwargs` in `src/markdown_vault_mcp/config.py` and add the four new fields to the kwargs dict:

```python
        return {
            "source_dir": self.source_dir,
            # ... existing kwargs ...
            "chunks_per_doc": self.chunks_per_doc,
            "snippet_words": self.snippet_words,
            "length_downweight_alpha": self.length_downweight_alpha,
            "max_chunk_words": self.max_chunk_words,
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_collection.py tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 6: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/collection.py src/markdown_vault_mcp/config.py tests/test_collection.py
git commit -m "feat(collection): wire ranking and snippet config knobs

Collection now constructs HeadingChunker with max_chunk_words and
SearchManager with chunks_per_doc / snippet_words /
length_downweight_alpha. CollectionConfig.to_collection_kwargs
forwards the four fields."
```

---

## Task 13: Surface `chunks_per_doc` and `snippet_words` on the `search` MCP tool

**Goal:** End-user / agentic consumers can override the cap and snippet width per call.

**Files:**
- Modify: `src/markdown_vault_mcp/_server_tools.py` (around line 83 — the `search` tool definition).
- Test: `tests/test_server.py` (extend) — drive the tool through `fastmcp.Client`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
async def test_search_tool_accepts_chunks_per_doc_and_snippet_words(
    server_factory, tmp_path
):
    """The `search` MCP tool surfaces the new knobs as optional parameters."""
    from fastmcp import Client

    (tmp_path / "long.md").write_text(
        "# Top\n## A\nworld a\n## B\nworld b\n## C\nworld c\n",
        encoding="utf-8",
    )
    (tmp_path / "short.md").write_text("# S\nworld\n", encoding="utf-8")
    server = server_factory(source_dir=tmp_path)

    async with Client(server) as client:
        result = await client.call_tool(
            "search",
            {
                "query": "world",
                "mode": "keyword",
                "chunks_per_doc": 1,
                "snippet_words": 5,
                "limit": 10,
            },
        )
        results = result.data
        paths = [r["path"] for r in results]
        assert len(set(paths)) == len(paths)
        assert all(len((r["content"] or "").split()) <= 8 for r in results)
```

(`server_factory` is the existing test fixture that creates a fresh FastMCP server bound to a tmp vault. If a different fixture name is in use, adapt accordingly — see existing `tests/test_server.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py -k chunks_per_doc -v`
Expected: FAIL — `ToolError` or `ValidationError` because the tool does not accept these parameters yet.

- [ ] **Step 3: Update the `search` tool**

In `src/markdown_vault_mcp/_server_tools.py`, locate the `@mcp.tool(...)`-decorated `async def search(...)` (≈ line 83). Update its signature, docstring, and the call into the manager:

```python
    @mcp.tool(...)  # keep existing decorator args
    async def search(
        query: str,
        *,
        limit: int = 10,
        mode: Literal["keyword", "semantic", "hybrid"] = "keyword",
        filters: dict[str, str] | None = None,
        folder: str | None = None,
        chunks_per_doc: int | None = None,
        snippet_words: int | None = None,
    ) -> list[SearchResult]:
        """Search the vault.

        ...

        Args:
            ...
            chunks_per_doc: Maximum number of result chunks per document
                in the returned list. ``None`` uses the server default
                (configured via ``MARKDOWN_VAULT_MCP_CHUNKS_PER_DOC``,
                default 2). Pass an integer to override per call.
            snippet_words: Approximate word budget for the per-result
                ``content`` snippet. ``None`` uses the server default
                (default 200). Pass ``0`` for the full chunk verbatim;
                recover the full chunk after seeing a snippet via
                ``read(path, section=heading)``.

        Returns:
            List of SearchResult. ``content`` is a snippet by default (≤
            ``snippet_words`` words, centred on the matched terms). Each
            result's ``heading`` plus ``path`` is the chunk identity used
            by ``read(path, section=heading)`` for full recovery.
        """
        coll = await get_collection()
        return await asyncio.to_thread(
            coll.search,
            query,
            limit=limit,
            mode=mode,
            filters=filters,
            folder=folder,
            chunks_per_doc=chunks_per_doc,
            snippet_words=snippet_words,
        )
```

(Confirm the actual `coll.search` signature accepts the two new kwargs from Task 8/11; if the `Collection` facade re-exports `SearchManager.search`, confirm it does too. If not, add a thin pass-through on `Collection.search`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 5: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/_server_tools.py tests/test_server.py
git commit -m "feat(server): chunks_per_doc and snippet_words on search tool

The search MCP tool surfaces both knobs as optional parameters; None
falls back to server defaults. Tool docstring documents that content
is now a snippet by default and points consumers at read(path,
section=heading) for full chunk recovery."
```

---

## Task 14: Surface `section` on the `read` MCP tool

**Goal:** Consumers can fetch a specific chunk via `read(path, section=heading)`.

**Files:**
- Modify: `src/markdown_vault_mcp/_server_tools.py` (≈ line 154 — the `read` tool).
- Test: `tests/test_server.py` (extend)

- [ ] **Step 1: Write failing test**

Add to `tests/test_server.py`:

```python
async def test_read_tool_returns_only_named_section(server_factory, tmp_path):
    from fastmcp import Client

    (tmp_path / "a.md").write_text(
        "# A\n## One\nfirst body\n## Two\nsecond body\n",
        encoding="utf-8",
    )
    server = server_factory(source_dir=tmp_path)
    async with Client(server) as client:
        whole = await client.call_tool("read", {"path": "a.md"})
        assert "first body" in whole.data["content"]
        assert "second body" in whole.data["content"]

        partial = await client.call_tool(
            "read", {"path": "a.md", "section": "One"}
        )
        assert "first body" in partial.data["content"]
        assert "second body" not in partial.data["content"]

        # Unknown section → tool error.
        with pytest.raises(Exception) as excinfo:
            await client.call_tool(
                "read", {"path": "a.md", "section": "Nope"}
            )
        assert "Nope" in str(excinfo.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py -k read_tool_returns_only_named_section -v`
Expected: FAIL.

- [ ] **Step 3: Update the `read` tool**

In `src/markdown_vault_mcp/_server_tools.py`, locate `async def read(...)` (≈ line 154). Update:

```python
    @mcp.tool(...)  # keep existing decorator args
    async def read(
        path: str,
        *,
        section: str | None = None,
    ) -> NoteContent | AttachmentContent:
        """Read a document — either the whole file or one named section.

        ...

        Args:
            path: Relative vault path.
            section: When provided, return just that section's chunk content
                (matched by exact heading text). ``None`` returns the whole
                document. Empty / whitespace section or an unknown heading
                raises ``ValueError``.
        """
        coll = await get_collection()
        return await asyncio.to_thread(coll.read, path, section=section)
```

If `Collection.read` does not yet accept `section`, add a thin pass-through delegating to `DocumentManager.read`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 5: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add src/markdown_vault_mcp/_server_tools.py tests/test_server.py
git commit -m "feat(server): section parameter on read tool

read(path, section=heading) returns just that section's chunk content,
serving as the recovery affordance for snippet-truncated search
results. Unknown / empty section raises ValueError surfaced as a
ToolError to consumers."
```

---

## Task 15: End-to-end pipeline integration test

**Goal:** A single test that mirrors the diagnostic pathology — one long doc + many short notes, verify essay occupies ≤ 2 of 10 slots and snippets are sentence-scale.

**Files:**
- Test: `tests/test_search_pipeline_integration.py` (new)

- [ ] **Step 1: Write the integration test**

Create `tests/test_search_pipeline_integration.py`:

```python
"""End-to-end integration test for the search ranking pipeline.

Mirrors the diagnostic case described in
docs/superpowers/specs/2026-04-30-search-ranking-and-snippets-design.md:
one 12-section essay plus many short atomic notes that all mention the
query terms. The essay must not occupy more than 2 of the top 10 slots,
result payloads must be bounded, and other notes must get representation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from markdown_vault_mcp.collection import Collection


@pytest.fixture()
def diagnostic_vault(tmp_path: Path) -> Path:
    # One big essay with 12 sections, all mentioning "etymology" and "secura".
    sections = []
    for i in range(12):
        sections.append(f"## Section {i}")
        sections.append(
            (f"On the etymology of secura: this {i} section repeats key "
             "terms etymology security care.") * 30
        )
    essay = "# Lexicon Essay\n" + "\n\n".join(sections) + "\n"
    (tmp_path / "essay.md").write_text(essay, encoding="utf-8")

    # Twenty short atomic notes, each genuinely related.
    for i in range(20):
        (tmp_path / f"note_{i:02d}.md").write_text(
            f"# Note {i}\n\netymology and secura — note {i} discusses "
            "security and care in brief.\n",
            encoding="utf-8",
        )
    return tmp_path


@pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
def test_essay_capped_in_top_ten(diagnostic_vault, mode):
    coll = Collection(source_dir=diagnostic_vault)
    coll.build_index()
    if mode in ("semantic", "hybrid"):
        coll.build_embeddings()

    results = coll.search(
        "etymology secura security care", mode=mode, limit=10
    )
    essay_slots = sum(1 for r in results if r.path == "essay.md")
    assert essay_slots <= 2, f"essay.md occupied {essay_slots} of 10 slots ({mode})"
    # Other docs get representation.
    other_paths = {r.path for r in results} - {"essay.md"}
    assert len(other_paths) >= 5, f"too few other docs in top 10 ({mode})"


def test_payloads_bounded_by_default(diagnostic_vault):
    coll = Collection(source_dir=diagnostic_vault)
    coll.build_index()
    results = coll.search("etymology secura", mode="keyword", limit=10)
    for r in results:
        # Default snippet_words=200; allow slack for ellipsis tokens.
        assert len(r.content.split()) <= 220
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_search_pipeline_integration.py -v`
Expected: PASS for all four parameter combinations.

- [ ] **Step 3: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add tests/test_search_pipeline_integration.py
git commit -m "test(search): end-to-end pipeline integration test

Mirrors the diagnostic case: one 12-section essay + 20 short notes,
all mentioning the query terms. Verifies essay <= 2 of top 10 slots,
other docs get representation, and default snippet payloads stay
under ~220 words."
```

---

## Task 16: Documentation updates

**Goal:** Spec, configuration, tools, and example env files reflect the new behaviour.

**Files:**
- Modify: `docs/design.md` — add a "Search ranking and snippet truncation" section under Search architecture; update HeadingChunker description for adaptive H-level splitting.
- Modify: `docs/configuration.md` — document the four new env vars.
- Modify: `docs/tools/index.md` — update `search` and `read` tool signatures.
- Modify: `examples/.env.example` — add commented-out entries for the four new vars at their default values.
- Modify: `README.md` — short paragraph in the Features section noting per-doc cap, snippets, and adaptive chunking.

- [ ] **Step 1: Update `docs/design.md`**

Find the existing "Search" section. Append a new "Search ranking and snippet truncation" subsection summarising goals, the pipeline diagram (copy from spec section "Pipeline overview"), and the four config knobs. Update the chunker subsection to describe adaptive H-level splitting (sentence: "When `max_chunk_words` is set, oversize chunks are recursively re-split at deeper heading levels (H1 → H6) until each fits or no headings of the next level exist inside.").

- [ ] **Step 2: Update `docs/configuration.md`**

Add a new "Search ranking and snippet truncation" section listing each env var (name, default, type, what it controls). Mirror the spec's API-surface table.

- [ ] **Step 3: Update `docs/tools/index.md`**

In the `search` tool entry, update the parameter table and Returns block to mention `chunks_per_doc`, `snippet_words`, and the snippet semantics. In the `read` tool entry, document the optional `section` parameter and how it pairs with snippet results.

- [ ] **Step 4: Update `examples/.env.example`**

Append:

```ini
# --- Search ranking and snippet truncation ---
# Per-document result cap. 0 rejected. Per-call override via search tool.
# MARKDOWN_VAULT_MCP_CHUNKS_PER_DOC=2

# Snippet word budget. 0 = no truncation, full chunk. Per-call override.
# MARKDOWN_VAULT_MCP_SNIPPET_WORDS=200

# Length downweight strength. 0 disables. Operator-only (no per-call override).
# MARKDOWN_VAULT_MCP_LENGTH_DOWNWEIGHT_ALPHA=0.25

# Adaptive chunker word threshold. Set very high (e.g. 100000) to disable.
# MARKDOWN_VAULT_MCP_MAX_CHUNK_WORDS=400
```

- [ ] **Step 5: Update `README.md`**

Add a short bullet to the "Features" or "Search" section, e.g.:

> - **Diversity-aware ranking.** Each search result list caps a single document at 2 chunks (configurable), downweights chunks of long documents, and returns sentence-scale snippets — bounded LLM context cost per query, with full chunk recovery via `read(path, section=heading)`.

- [ ] **Step 6: Verify docs build**

Run: `uv run mkdocs build --strict`
Expected: PASS, no broken links / orphaned pages.

- [ ] **Step 7: Pre-commit gates + commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/ tests/ && uv run pytest -x -q
git add docs/design.md docs/configuration.md docs/tools/index.md examples/.env.example README.md
git commit -m "docs: search ranking and snippet truncation

Document the new MARKDOWN_VAULT_MCP_CHUNKS_PER_DOC,
MARKDOWN_VAULT_MCP_SNIPPET_WORDS,
MARKDOWN_VAULT_MCP_LENGTH_DOWNWEIGHT_ALPHA, and
MARKDOWN_VAULT_MCP_MAX_CHUNK_WORDS env vars; the new search/read
tool parameters; and the adaptive chunker behaviour. Updates
design.md with the ranking pipeline diagram."
```

---

## Self-Review (before opening the PR)

Run through this checklist locally:

1. **Spec coverage:** Cross-reference the spec's Goals (1–6) and Non-goals (1–4) against the task list. Each goal has at least one task (cap → Tasks 6, 8, 9, 10; downweight → Tasks 5, 8, 9, 10; snippet → Tasks 4, 7, 8, 9, 10; adaptive chunker → Task 2; mode-uniform → Tasks 8, 9, 10; no shape break → preserved by `content`-field reuse in Tasks 8–10). Non-goals: no frontmatter conventions (codified in spec, not in code); no re-embed (Task 7 uses string scan only); no paragraph chunking (Task 2 deliberately stops at H6); no new modes (search tool keeps the same three).
2. **Reindex required.** Task 16 docs must call this out for operators upgrading.
3. **Default-behavior change.** Existing search consumers will see shorter `content` after this PR ships. Captured in Task 13's commit message and Task 16's docs; also surface in the eventual PR description.
4. **Backwards compatibility.** `SearchResult` shape unchanged; `read(path)` unchanged. New parameters are all keyword-only and optional.
5. **Pre-commit hooks.** Each task ends with the same lint/format/mypy/pytest gauntlet; no `--no-verify`.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-30-search-ranking-and-snippets.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
