"""Tests for the Note Context Card MCP App view.

Covers issue #274: _vault_context tool, show_context tool, and
HTML context card rendering.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from fastmcp import Client

from markdown_vault_mcp.mcp_server import create_server

if TYPE_CHECKING:
    from pathlib import Path


_CLEAR_VARS = (
    "MARKDOWN_VAULT_MCP_INDEX_PATH",
    "MARKDOWN_VAULT_MCP_EMBEDDINGS_PATH",
    "MARKDOWN_VAULT_MCP_STATE_PATH",
    "MARKDOWN_VAULT_MCP_INDEXED_FIELDS",
    "MARKDOWN_VAULT_MCP_REQUIRED_FIELDS",
    "MARKDOWN_VAULT_MCP_EXCLUDE",
    "MARKDOWN_VAULT_MCP_GIT_TOKEN",
    "MARKDOWN_VAULT_MCP_TEMPLATES_FOLDER",
    "MARKDOWN_VAULT_MCP_SERVER_NAME",
    "MARKDOWN_VAULT_MCP_INSTRUCTIONS",
    "MARKDOWN_VAULT_MCP_BEARER_TOKEN",
    "MARKDOWN_VAULT_MCP_AUTH_MODE",
    "MARKDOWN_VAULT_MCP_BASE_URL",
    "MARKDOWN_VAULT_MCP_OIDC_CONFIG_URL",
    "MARKDOWN_VAULT_MCP_OIDC_CLIENT_ID",
    "MARKDOWN_VAULT_MCP_OIDC_CLIENT_SECRET",
    "MARKDOWN_VAULT_MCP_OIDC_JWT_SIGNING_KEY",
    "MARKDOWN_VAULT_MCP_OIDC_AUDIENCE",
    "MARKDOWN_VAULT_MCP_OIDC_REQUIRED_SCOPES",
    "MARKDOWN_VAULT_MCP_APP_DOMAIN",
)


@pytest.fixture
def _mcp_env(vault_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault_path))
    monkeypatch.delenv("MARKDOWN_VAULT_MCP_READ_ONLY", raising=False)
    for var in _CLEAR_VARS:
        monkeypatch.delenv(var, raising=False)


def _parse_tool_data(result: Any) -> Any:
    data = result.data
    if isinstance(data, list) and data and not isinstance(data[0], (dict, str)):
        raw = result.content[0].text if result.content else "[]"
        return json.loads(raw)
    return data


# ---------------------------------------------------------------------------
# Context card HTML content
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_mcp_env")
class TestContextCardHTML:
    """Verify context card sections exist in the SPA HTML."""

    async def _get_html(self) -> str:
        server = create_server()
        async with Client(server) as client:
            resource = await client.read_resource("ui://vault/app.html")
            return (
                resource[0].text if hasattr(resource[0], "text") else str(resource[0])
            )

    async def test_context_card_container(self) -> None:
        html = await self._get_html()
        assert 'id="context-card"' in html

    async def test_context_header_elements(self) -> None:
        html = await self._get_html()
        assert 'id="ctx-title"' in html
        assert 'id="ctx-path"' in html
        assert 'id="ctx-folder"' in html

    async def test_collapsible_sections(self) -> None:
        html = await self._get_html()
        for section_id in [
            "ctx-frontmatter",
            "ctx-tags",
            "ctx-backlinks",
            "ctx-outlinks",
            "ctx-similar",
            "ctx-peers",
        ]:
            assert f'id="{section_id}"' in html

    async def test_send_to_claude_button(self) -> None:
        html = await self._get_html()
        assert 'id="ctx-send-btn"' in html
        assert "sendToLLM" in html

    async def test_call_server_tool_for_context(self) -> None:
        html = await self._get_html()
        assert "callServerTool" in html
        assert "_vault_context" in html

    async def test_clickable_link_items(self) -> None:
        html = await self._get_html()
        assert "link-item" in html
        assert "data-path" in html

    async def test_host_css_variables(self) -> None:
        html = await self._get_html()
        assert "var(--host-accent" in html
        assert "var(--host-border" in html
        assert "var(--host-muted" in html

    async def test_update_model_context_on_view(self) -> None:
        html = await self._get_html()
        assert "updateContext" in html
        assert "'context card'" in html

    async def test_link_type_badges(self) -> None:
        html = await self._get_html()
        assert "link-type-badge" in html

    async def test_similar_score_bar(self) -> None:
        html = await self._get_html()
        assert "similar-score-fill" in html

    async def test_tag_pills(self) -> None:
        html = await self._get_html()
        assert "tag-pill" in html

    async def test_frontmatter_table(self) -> None:
        html = await self._get_html()
        assert "fm-table" in html


# ---------------------------------------------------------------------------
# _vault_context tool data
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_mcp_env")
class TestVaultContextToolData:
    """Verify _vault_context returns complete NoteContext fields."""

    async def test_all_context_fields_present(self) -> None:
        server = create_server()
        async with Client(server) as client:
            result = await client.call_tool("_vault_context", {"path": "simple.md"})
            data = _parse_tool_data(result)
            assert data["path"] == "simple.md"
            assert "title" in data
            assert "folder" in data
            assert "frontmatter" in data
            assert "modified_at" in data
            assert "backlinks" in data
            assert "outlinks" in data
            assert "similar" in data
            assert "folder_notes" in data
            assert "tags" in data

    async def test_context_with_frontmatter(self) -> None:
        server = create_server()
        async with Client(server) as client:
            result = await client.call_tool(
                "_vault_context", {"path": "full_frontmatter.md"}
            )
            data = _parse_tool_data(result)
            assert data["path"] == "full_frontmatter.md"
            assert isinstance(data["frontmatter"], dict)
