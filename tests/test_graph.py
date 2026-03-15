"""Tests for orphan detection and hub notes (get_orphan_notes, get_most_linked)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from markdown_vault_mcp.collection import Collection
from markdown_vault_mcp.fts_index import FTSIndex
from markdown_vault_mcp.types import (
    Chunk,
    LinkInfo,
    MostLinkedNote,
    NoteInfo,
    ParsedNote,
)

if TYPE_CHECKING:
    from pathlib import Path


def _parse_tool_data(result: Any) -> Any:
    """Extract list/dict from a CallToolResult, handling FastMCP serialization."""
    data = result.data
    if isinstance(data, list) and data and not isinstance(data[0], (dict, str)):
        raw = result.content[0].text if result.content else "[]"
        return json.loads(raw)
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_note(
    path: str,
    title: str = "Test",
    links: list[LinkInfo] | None = None,
) -> ParsedNote:
    return ParsedNote(
        path=path,
        frontmatter={},
        title=title,
        chunks=[Chunk(heading=None, heading_level=0, content="body", start_line=0)],
        content_hash="abc",
        modified_at=0.0,
        links=links or [],
    )


# ---------------------------------------------------------------------------
# FTSIndex.get_orphan_notes
# ---------------------------------------------------------------------------


class TestFTSGetOrphanNotes:
    def test_note_with_no_links_is_orphan(self) -> None:
        """A note with no outlinks and no backlinks is an orphan."""
        idx = FTSIndex(":memory:")
        idx.upsert_note(make_note("orphan.md"))
        rows = idx.get_orphan_notes()
        assert len(rows) == 1
        assert rows[0]["path"] == "orphan.md"

    def test_note_with_only_outlinks_is_not_orphan(self) -> None:
        """A note that has outlinks (even to non-indexed paths) is not an orphan."""
        idx = FTSIndex(":memory:")
        idx.upsert_note(
            make_note(
                "linker.md",
                links=[
                    LinkInfo(
                        target_path="other.md", link_text="T", link_type="markdown"
                    )
                ],
            )
        )
        rows = idx.get_orphan_notes()
        assert all(r["path"] != "linker.md" for r in rows)

    def test_note_with_only_backlinks_is_not_orphan(self) -> None:
        """A note that is linked to by other notes is not an orphan."""
        idx = FTSIndex(":memory:")
        idx.upsert_note(make_note("target.md"))
        idx.upsert_note(
            make_note(
                "source.md",
                links=[
                    LinkInfo(
                        target_path="target.md", link_text="T", link_type="markdown"
                    )
                ],
            )
        )
        rows = idx.get_orphan_notes()
        paths = {r["path"] for r in rows}
        assert "target.md" not in paths  # has backlink → not orphan
        assert "source.md" not in paths  # has outlink → not orphan

    def test_multiple_orphans_returned(self) -> None:
        """All orphan notes are returned."""
        idx = FTSIndex(":memory:")
        for i in range(3):
            idx.upsert_note(make_note(f"orphan{i}.md"))
        rows = idx.get_orphan_notes()
        assert len(rows) == 3

    def test_orphan_notes_ordered_by_path(self) -> None:
        """Results are ordered by path."""
        idx = FTSIndex(":memory:")
        for name in ["z.md", "a.md", "m.md"]:
            idx.upsert_note(make_note(name))
        rows = idx.get_orphan_notes()
        paths = [r["path"] for r in rows]
        assert paths == sorted(paths)

    def test_empty_vault_returns_empty(self) -> None:
        """get_orphan_notes returns [] when no documents are indexed."""
        idx = FTSIndex(":memory:")
        assert idx.get_orphan_notes() == []

    def test_orphan_row_includes_title_and_folder(self) -> None:
        """Each row contains path, title, folder, frontmatter_json, modified_at."""
        idx = FTSIndex(":memory:")
        note = ParsedNote(
            path="folder/note.md",
            frontmatter={"key": "val"},
            title="My Note",
            chunks=[Chunk(heading=None, heading_level=0, content="x", start_line=0)],
            content_hash="h",
            modified_at=1234.5,
        )
        idx.upsert_note(note)
        rows = idx.get_orphan_notes()
        assert len(rows) == 1
        assert rows[0]["title"] == "My Note"
        assert rows[0]["folder"] == "folder"


# ---------------------------------------------------------------------------
# FTSIndex.get_most_linked
# ---------------------------------------------------------------------------


class TestFTSGetMostLinked:
    def test_most_linked_returns_correct_counts(self) -> None:
        """get_most_linked returns notes sorted by backlink_count descending."""
        idx = FTSIndex(":memory:")
        idx.upsert_note(make_note("hub.md"))
        idx.upsert_note(make_note("less.md"))
        for i in range(3):
            idx.upsert_note(
                make_note(
                    f"src{i}.md",
                    links=[
                        LinkInfo(
                            target_path="hub.md", link_text="H", link_type="markdown"
                        )
                    ],
                )
            )
        idx.upsert_note(
            make_note(
                "src_less.md",
                links=[
                    LinkInfo(target_path="less.md", link_text="L", link_type="markdown")
                ],
            )
        )
        rows = idx.get_most_linked()
        assert rows[0]["path"] == "hub.md"
        assert rows[0]["backlink_count"] == 3
        assert rows[1]["path"] == "less.md"
        assert rows[1]["backlink_count"] == 1

    def test_get_most_linked_limit(self) -> None:
        """limit caps the number of results."""
        idx = FTSIndex(":memory:")
        for i in range(5):
            idx.upsert_note(make_note(f"target{i}.md"))
            idx.upsert_note(
                make_note(
                    f"src{i}.md",
                    links=[
                        LinkInfo(
                            target_path=f"target{i}.md",
                            link_text="T",
                            link_type="markdown",
                        )
                    ],
                )
            )
        rows = idx.get_most_linked(limit=3)
        assert len(rows) == 3

    def test_get_most_linked_empty_vault(self) -> None:
        """get_most_linked returns [] when no links exist."""
        idx = FTSIndex(":memory:")
        assert idx.get_most_linked() == []

    def test_most_linked_row_keys(self) -> None:
        """Each row contains path, title, backlink_count."""
        idx = FTSIndex(":memory:")
        idx.upsert_note(make_note("target.md", title="Target Note"))
        idx.upsert_note(
            make_note(
                "src.md",
                links=[
                    LinkInfo(
                        target_path="target.md", link_text="T", link_type="markdown"
                    )
                ],
            )
        )
        rows = idx.get_most_linked()
        assert rows[0]["path"] == "target.md"
        assert rows[0]["title"] == "Target Note"
        assert "backlink_count" in rows[0]


# ---------------------------------------------------------------------------
# Collection.get_orphan_notes / Collection.get_most_linked
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_vault(tmp_path: Path) -> Path:
    """Vault with a hub note, a linked note, and an orphan note.

    hub.md        linked to by source.md and source2.md
    source.md     links to hub.md
    source2.md    links to hub.md
    orphan.md     no links in or out
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "hub.md").write_text("# Hub\n\nThe central note.\n")
    (vault / "source.md").write_text("# Source\n\nSee [Hub](hub.md).\n")
    (vault / "source2.md").write_text("# Source 2\n\nAlso see [Hub](hub.md).\n")
    (vault / "orphan.md").write_text("# Orphan\n\nIsolated note.\n")
    return vault


class TestCollectionOrphanAndHub:
    def test_get_orphan_notes_returns_note_info(self, graph_vault: Path) -> None:
        """Collection.get_orphan_notes() returns NoteInfo objects."""
        col = Collection(source_dir=graph_vault)
        col.build_index()
        orphans = col.get_orphan_notes()
        assert all(isinstance(n, NoteInfo) for n in orphans)

    def test_get_orphan_notes_finds_orphan(self, graph_vault: Path) -> None:
        """The orphan note appears in results."""
        col = Collection(source_dir=graph_vault)
        col.build_index()
        paths = {n.path for n in col.get_orphan_notes()}
        assert "orphan.md" in paths

    def test_get_orphan_notes_excludes_linked(self, graph_vault: Path) -> None:
        """Notes with links (in or out) are not orphans."""
        col = Collection(source_dir=graph_vault)
        col.build_index()
        paths = {n.path for n in col.get_orphan_notes()}
        assert "hub.md" not in paths
        assert "source.md" not in paths
        assert "source2.md" not in paths

    def test_get_most_linked_returns_dataclasses(self, graph_vault: Path) -> None:
        """Collection.get_most_linked() returns list of MostLinkedNote dataclasses."""
        col = Collection(source_dir=graph_vault)
        col.build_index()
        results = col.get_most_linked()
        assert all(isinstance(r, MostLinkedNote) for r in results)

    def test_get_most_linked_hub_is_first(self, graph_vault: Path) -> None:
        """The hub note (most backlinks) appears first."""
        col = Collection(source_dir=graph_vault)
        col.build_index()
        results = col.get_most_linked()
        assert results[0].path == "hub.md"
        assert results[0].backlink_count == 2

    def test_get_most_linked_limit(self, graph_vault: Path) -> None:
        """limit caps the result count."""
        col = Collection(source_dir=graph_vault)
        col.build_index()
        results = col.get_most_linked(limit=1)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_graph_vault(tmp_path: Path) -> Path:
    """Minimal vault for MCP graph tool tests."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "hub.md").write_text("# Hub\n\nCentral.\n")
    (vault / "src.md").write_text("# Src\n\nSee [Hub](hub.md).\n")
    (vault / "orphan.md").write_text("# Orphan\n\nAlone.\n")
    return vault


@pytest.fixture
def _mcp_env_graph(mcp_graph_vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _CLEAR_VARS = [
        "MARKDOWN_VAULT_MCP_SOURCE_DIR",
        "MARKDOWN_VAULT_MCP_DB_PATH",
        "MARKDOWN_VAULT_MCP_EMBEDDINGS_PATH",
        "MARKDOWN_VAULT_MCP_BEARER_TOKEN",
        "MARKDOWN_VAULT_MCP_OIDC_CONFIG_URL",
        "MARKDOWN_VAULT_MCP_READ_ONLY",
    ]
    for var in _CLEAR_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(mcp_graph_vault))


class TestMCPGraphTools:
    async def test_get_orphan_notes_tool(self, _mcp_env_graph: None) -> None:
        """get_orphan_notes MCP tool returns orphan notes."""
        from fastmcp import Client

        from markdown_vault_mcp.mcp_server import create_server

        server = create_server()
        async with Client(server) as client:
            result = await client.call_tool("get_orphan_notes", {})
        items = _parse_tool_data(result)
        assert isinstance(items, list)
        paths = {item["path"] for item in items}
        assert "orphan.md" in paths
        assert "hub.md" not in paths

    async def test_get_most_linked_tool(self, _mcp_env_graph: None) -> None:
        """get_most_linked MCP tool returns hub note first."""
        from fastmcp import Client

        from markdown_vault_mcp.mcp_server import create_server

        server = create_server()
        async with Client(server) as client:
            result = await client.call_tool("get_most_linked", {"limit": 5})
        items = _parse_tool_data(result)
        assert isinstance(items, list)
        assert len(items) >= 1
        assert items[0]["path"] == "hub.md"
        assert items[0]["backlink_count"] == 1

    async def test_get_most_linked_tool_limit(self, _mcp_env_graph: None) -> None:
        """get_most_linked respects the limit parameter."""
        from fastmcp import Client

        from markdown_vault_mcp.mcp_server import create_server

        server = create_server()
        async with Client(server) as client:
            result = await client.call_tool("get_most_linked", {"limit": 1})
        items = _parse_tool_data(result)
        assert len(items) == 1
