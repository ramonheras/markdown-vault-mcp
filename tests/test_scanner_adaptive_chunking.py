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
    # Use one word per line so the fixture clears the 30-line short-doc bypass.
    top_body = "\n".join(["lorem"] * 15)
    sub_a_body = "\n".join(["lorem"] * 15)
    deep_body = "\n".join(["lorem"] * 800)
    body = (
        f"# Top\n{top_body}\n"
        f"## Sub A\n{sub_a_body}\n"
        f"### Deep\n{deep_body}\n"  # H3, would not split today and must not split.
    )
    chunker = HeadingChunker(max_chunk_words=None)
    chunks = chunker.chunk(body, {})
    # H1 + H2 produce 2 chunks; H3 stays inside the H2 chunk.
    assert len(chunks) == 2
    headings = [c.heading for c in chunks]
    assert headings == ["Top", "Sub A"]


def test_oversize_h1_splits_at_h2():
    """An H1 chunk exceeding max_chunk_words is re-split at H2."""
    # Use one word per line so the fixture clears the 30-line short-doc bypass.
    sub_body = "\n".join(["lorem"] * 300)
    body = f"# Top\n## Sub A\n{sub_body}\n## Sub B\n{sub_body}\n"
    chunker = HeadingChunker(max_chunk_words=200)
    chunks = chunker.chunk(body, {})
    assert [c.heading for c in chunks] == ["Sub A", "Sub B"]
    assert all(c.heading_level == 2 for c in chunks)


def test_recursion_descends_to_h6():
    """An H1 chunk with deeply nested oversized sub-headings descends to H6."""
    # Use a long enough body to clear the 30-line short-doc bypass.
    long_body = "\n".join(["lorem"] * 50)  # 50 lines per body
    body = (
        f"# L1\n{long_body}\n"
        f"## L2\n{long_body}\n"
        f"### L3\n{long_body}\n"
        f"#### L4\n{long_body}\n"
        f"##### L5\n{long_body}\n"
        "###### L6a\n" + " ".join(["lorem"] * 50) + "\n"
        "###### L6b\n" + " ".join(["lorem"] * 50) + "\n"
    )
    chunker = HeadingChunker(max_chunk_words=40)
    chunks = chunker.chunk(body, {})
    headings = [c.heading for c in chunks]
    assert "L6a" in headings and "L6b" in headings


def test_oversize_chunk_with_no_deeper_headings_stays_one_chunk():
    """A 1000-word H6 with no deeper headings stays as one chunk."""
    body = "###### Solo\n" + "\n".join(["lorem"] * 100) + "\n"
    chunker = HeadingChunker(max_chunk_words=50)
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
    # Use one word per line so the fixture clears the 30-line short-doc bypass.
    inner_body = "\n".join(["lorem"] * 300)
    body = f"# Top\n## Inner\n{inner_body}\n"
    chunker = HeadingChunker(max_chunk_words=200)
    chunks = chunker.chunk(body, {})
    inner = next(c for c in chunks if c.heading == "Inner")
    assert inner.heading_level == 2
    # start_line points at the H2 line in the document.
    body_lines = body.splitlines()
    assert body_lines[inner.start_line].lstrip().startswith("## Inner")


def test_legacy_mode_h3_only_doc_returns_single_chunk_no_heading():
    """Legacy mode (max_chunk_words=None) preserves pre-PR behaviour:
    a doc with only H3 headings returns one chunk with heading=None
    (rather than being split at H3, which is the adaptive-mode behaviour).

    Body uses 20 lines per section (one word per line) to clear the
    30-line short-doc bypass, so the test exercises the H1/H2-only
    heading logic rather than the short-doc fast-path.
    """
    body = (
        "### A\n"
        + "\n".join(["body"] * 20)
        + "\n### B\n"
        + "\n".join(["word"] * 20)
        + "\n"
    )
    chunker = HeadingChunker(max_chunk_words=None)
    chunks = chunker.chunk(body, {})
    assert len(chunks) == 1
    assert chunks[0].heading is None


def test_adaptive_mode_h3_only_doc_splits_at_h3():
    """Adaptive mode descends to H3 when H1/H2 are absent.

    Body uses 20 lines per section (one word per line) to clear the
    30-line short-doc bypass, which would otherwise return a single chunk
    before the H3-descent code is reached.
    """
    body = (
        "### A\n"
        + "\n".join(["body"] * 20)
        + "\n### B\n"
        + "\n".join(["word"] * 20)
        + "\n"
    )
    chunker = HeadingChunker(max_chunk_words=400)
    chunks = chunker.chunk(body, {})
    assert len(chunks) == 2
    assert {c.heading for c in chunks} == {"A", "B"}
    assert all(c.heading_level == 3 for c in chunks)
