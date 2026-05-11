"""Tests for field-collapsing types and helpers (issue #469)."""

from __future__ import annotations

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
