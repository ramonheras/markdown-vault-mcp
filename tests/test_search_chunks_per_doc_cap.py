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
