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
