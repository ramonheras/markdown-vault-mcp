"""Tests for snippet generation in SearchManager."""

from __future__ import annotations

from markdown_vault_mcp.managers.search import _compute_snippet_for_semantic


def test_snippet_words_zero_returns_full_content():
    content = " ".join(f"word{i}" for i in range(50))
    assert (
        _compute_snippet_for_semantic(content, "anything", snippet_words=0) == content
    )


def test_window_centered_on_densest_query_match():
    """Slide a 10-word window; pick the one with most query tokens."""
    content = (
        " ".join(["filler"] * 20) + " needle midway needle " + " ".join(["filler"] * 20)
    )
    out = _compute_snippet_for_semantic(content, "needle", snippet_words=10)
    assert "needle" in out
    assert len(out.split()) <= 12  # 10 + slack for ellipses


def test_no_overlap_falls_back_to_first_n_words():
    content = " ".join(f"word{i}" for i in range(50))
    out = _compute_snippet_for_semantic(
        content, "completely-unrelated-token", snippet_words=10
    )
    assert out.split()[0] == "word0"
    assert len(out.split()) <= 12


def test_short_chunk_returned_intact():
    content = "five word chunk only here"
    out = _compute_snippet_for_semantic(content, "chunk", snippet_words=200)
    assert out == content


def test_query_tokenization_is_case_insensitive():
    content = (
        " ".join(["filler"] * 20) + " Needle hit Needle " + " ".join(["filler"] * 20)
    )
    out = _compute_snippet_for_semantic(content, "NEEDLE", snippet_words=10)
    assert "Needle" in out


def test_window_matches_words_with_embedded_punctuation():
    """Query and content with apostrophes/hyphens normalise symmetrically."""
    content = (
        " ".join(["filler"] * 20)
        + " isn't midway test-driven "
        + " ".join(["filler"] * 20)
    )
    # User types the literal punctuation form — must match content words
    # that also have punctuation.
    out = _compute_snippet_for_semantic(content, "isn't test-driven", snippet_words=10)
    assert "isn't" in out or "test-driven" in out
    assert len(out.split()) <= 12  # 10 + ellipsis slack
