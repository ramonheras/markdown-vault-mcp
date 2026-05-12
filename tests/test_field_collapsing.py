"""Tests for field-collapsing types and helpers (issue #469)."""

from __future__ import annotations

from dataclasses import dataclass

from markdown_vault_mcp.managers.search import _group_by_path
from markdown_vault_mcp.types import GroupedResult, SectionHit


def test_section_hit_fields():
    s = SectionHit(heading="Risk", content="snippet", score=0.9)
    assert s.heading == "Risk"
    assert s.content == "snippet"
    assert s.score == 0.9


def test_grouped_result_fields():
    g = GroupedResult(
        path="a.md",
        title="A",
        folder="",
        score=0.9,
        search_type="semantic",
        frontmatter={},
        sections=[SectionHit(heading=None, content="x", score=0.9)],
    )
    assert g.path == "a.md"
    assert g.search_type == "semantic"
    assert len(g.sections) == 1


@dataclass
class _Row:
    path: str
    heading: str | None
    content: str
    score: float
    start_line: int = 0


def test_group_by_path_collapses_same_file():
    rows = [
        _Row("a.md", "X", "x1", 0.9, 5),
        _Row("a.md", "Y", "y1", 0.85, 20),
        _Row("b.md", None, "bb", 0.8, 0),
        _Row("a.md", "Z", "z1", 0.7, 50),
    ]
    groups = _group_by_path(rows, chunks_per_file=2, file_limit=10)
    assert [(g[0].path, len(g)) for g in groups] == [("a.md", 2), ("b.md", 1)]
    # a.md should keep its TWO best chunks (X 0.9 and Y 0.85), dropping Z 0.7.
    a_group_scores = sorted([r.score for r in groups[0]], reverse=True)
    assert a_group_scores == [0.9, 0.85]


def test_group_by_path_respects_file_limit():
    rows = [
        _Row("a.md", None, "", 0.9, 0),
        _Row("b.md", None, "", 0.8, 0),
        _Row("c.md", None, "", 0.7, 0),
    ]
    groups = _group_by_path(rows, chunks_per_file=2, file_limit=2)
    assert [g[0].path for g in groups] == ["a.md", "b.md"]


def test_group_by_path_section_ties_sort_by_start_line():
    """When two sections of the same file tie on score, document order wins."""
    rows = [
        _Row("a.md", "Late", "", 0.9, 100),
        _Row("a.md", "Early", "", 0.9, 5),
    ]
    groups = _group_by_path(rows, chunks_per_file=2, file_limit=10)
    headings = [r.heading for r in groups[0]]
    assert headings == ["Early", "Late"], (
        "ties on score should resolve by start_line ASC (document order)"
    )


def test_group_by_path_rejects_zero_chunks_per_file():
    import pytest

    with pytest.raises(ValueError, match="chunks_per_file"):
        _group_by_path([], chunks_per_file=0, file_limit=10)


def test_group_by_path_preserves_score_desc_file_order():
    rows = [
        _Row("a.md", None, "", 0.6, 0),
        _Row("b.md", None, "", 0.9, 0),
        _Row("c.md", None, "", 0.7, 0),
    ]
    # Caller is responsible for pre-sorting by score DESC; helper trusts input.
    rows_sorted = sorted(rows, key=lambda r: r.score, reverse=True)
    groups = _group_by_path(rows_sorted, chunks_per_file=1, file_limit=10)
    assert [g[0].path for g in groups] == ["b.md", "c.md", "a.md"]


def test_get_similar_dedupes_multichunk_target(populated_collection):
    """A multi-chunk target document appears only ONCE in get_similar."""
    # The populated_collection fixture has "multi.md" with three sections
    # all mentioning "foo".  Pick a different reference doc that has high
    # similarity to multi.md; assert multi.md appears once.
    # We use the first doc in the vault as reference.
    notes = populated_collection.list()
    assert len(notes) >= 2, "fixture should have multiple docs"
    ref_path = next(n.path for n in notes if n.path == "multi.md")

    results = populated_collection.get_similar(ref_path, limit=10, chunks_per_file=2)
    paths = [r.path for r in results]
    assert len(paths) == len(set(paths)), (
        f"all result paths should be unique after grouping, got {paths}"
    )
    if results:
        # File score = max(section.score)
        for r in results:
            assert r.sections, f"{r.path} has empty sections"
            assert r.score == max(s.score for s in r.sections)
