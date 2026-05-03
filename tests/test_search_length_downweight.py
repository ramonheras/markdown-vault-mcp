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
    long10 = _Row("L.md", 2.0, 10)
    short = _Row("S.md", 1.0, 1)
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
