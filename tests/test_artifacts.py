"""Tests for the ArtifactStore, create_download_link tool, and artifact endpoint.

Covers:
- ArtifactStore: create, consume, expire, double-consume
- create_download_link tool: valid paths, missing BASE_URL, non-existent path
- Artifact HTTP handler: serve bytes, one-time use, expired 404
- Tool not registered on stdio transport
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from markdown_vault_mcp.artifacts import ArtifactStore, TokenRecord
from markdown_vault_mcp.mcp_server import create_server

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Env var list for clean fixture setup
# ---------------------------------------------------------------------------

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
    "MARKDOWN_VAULT_MCP_BASE_URL",
    "MARKDOWN_VAULT_MCP_OIDC_CONFIG_URL",
    "MARKDOWN_VAULT_MCP_OIDC_CLIENT_ID",
    "MARKDOWN_VAULT_MCP_OIDC_CLIENT_SECRET",
    "MARKDOWN_VAULT_MCP_OIDC_JWT_SIGNING_KEY",
    "MARKDOWN_VAULT_MCP_OIDC_AUDIENCE",
    "MARKDOWN_VAULT_MCP_OIDC_REQUIRED_SCOPES",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> ArtifactStore:
    """Fresh ArtifactStore for each test."""
    return ArtifactStore()


@pytest.fixture
def _artifact_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Writable vault with a note and an attachment for artifact tests."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Note\n\nSome content.\n", encoding="utf-8")
    (vault / "assets").mkdir()
    (vault / "assets" / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_READ_ONLY", "false")
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_BASE_URL", "https://mcp.example.com")
    for var in _CLEAR_VARS:
        if var != "MARKDOWN_VAULT_MCP_BASE_URL":
            monkeypatch.delenv(var, raising=False)
    return vault


# ---------------------------------------------------------------------------
# ArtifactStore: create and consume
# ---------------------------------------------------------------------------


class TestArtifactStoreCreateConsume:
    """ArtifactStore basic create/consume contract."""

    def test_create_returns_hex_string(self, store: ArtifactStore) -> None:
        token = store.create_token("note.md")
        assert isinstance(token, str)
        assert len(token) == 32  # uuid4().hex is 32 hex chars
        int(token, 16)  # raises if not valid hex

    def test_consume_returns_record(self, store: ArtifactStore) -> None:
        token = store.create_token("note.md", ttl_seconds=60)
        record = store.consume_token(token)
        assert record is not None
        assert record.path == "note.md"
        assert record.ttl_seconds == 60

    def test_consume_removes_token(self, store: ArtifactStore) -> None:
        """Consuming a token makes it unavailable for a second attempt."""
        token = store.create_token("note.md")
        store.consume_token(token)
        second = store.consume_token(token)
        assert second is None

    def test_unknown_token_returns_none(self, store: ArtifactStore) -> None:
        result = store.consume_token("deadbeef" * 4)
        assert result is None

    def test_create_stores_correct_path(self, store: ArtifactStore) -> None:
        path = "assets/diagram.png"
        token = store.create_token(path)
        record = store.consume_token(token)
        assert record is not None
        assert record.path == path


# ---------------------------------------------------------------------------
# ArtifactStore: expiry
# ---------------------------------------------------------------------------


class TestArtifactStoreExpiry:
    """Expired tokens return None from consume_token."""

    def test_expired_token_returns_none(self, store: ArtifactStore) -> None:
        token = store.create_token("note.md", ttl_seconds=1)
        # Manually backdate the created_at to simulate expiry
        record = store._tokens[token]
        store._tokens[token] = TokenRecord(
            path=record.path,
            created_at=record.created_at - 10,  # 10 seconds in the past
            ttl_seconds=1,
        )
        result = store.consume_token(token)
        assert result is None

    def test_expired_token_is_removed_from_store(self, store: ArtifactStore) -> None:
        """consume_token removes the token even when expired."""
        token = store.create_token("note.md", ttl_seconds=1)
        record = store._tokens[token]
        store._tokens[token] = TokenRecord(
            path=record.path,
            created_at=record.created_at - 10,
            ttl_seconds=1,
        )
        store.consume_token(token)
        # Token is gone from the store
        assert token not in store._tokens

    def test_cleanup_expired_on_create(self, store: ArtifactStore) -> None:
        """Creating a token cleans up already-expired tokens."""
        token = store.create_token("note.md", ttl_seconds=1)
        # Expire it manually without consuming
        record = store._tokens[token]
        store._tokens[token] = TokenRecord(
            path=record.path,
            created_at=record.created_at - 10,
            ttl_seconds=1,
        )
        # Creating a new token triggers cleanup
        store.create_token("other.md")
        assert token not in store._tokens


# ---------------------------------------------------------------------------
# create_download_link tool: registration
# ---------------------------------------------------------------------------


class TestCreateDownloadLinkRegistration:
    """create_download_link is only registered for non-stdio transports."""

    @pytest.fixture(autouse=True)
    def _env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "note.md").write_text("# Note\n")
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault))
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_READ_ONLY", "true")
        for var in _CLEAR_VARS:
            monkeypatch.delenv(var, raising=False)

    async def test_not_registered_on_stdio(self) -> None:
        server = create_server(transport="stdio")
        async with Client(server) as client:
            tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "create_download_link" not in names

    async def test_registered_on_http(self) -> None:
        server = create_server(transport="http")
        async with Client(server) as client:
            tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "create_download_link" in names

    async def test_registered_on_sse(self) -> None:
        server = create_server(transport="sse")
        async with Client(server) as client:
            tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "create_download_link" in names


# ---------------------------------------------------------------------------
# create_download_link tool: functional
# ---------------------------------------------------------------------------


class TestCreateDownloadLinkTool:
    """Functional tests for the create_download_link tool."""

    async def test_returns_json_with_download_url(self, _artifact_vault: Path) -> None:
        server = create_server(transport="http")
        async with Client(server) as client:
            result = await client.call_tool("create_download_link", {"path": "note.md"})
        data = json.loads(result.content[0].text)
        assert "download_url" in data
        assert "expires_in_seconds" in data
        assert "path" in data
        assert "content_type" in data

    async def test_download_url_contains_base_url(self, _artifact_vault: Path) -> None:
        server = create_server(transport="http")
        async with Client(server) as client:
            result = await client.call_tool("create_download_link", {"path": "note.md"})
        data = json.loads(result.content[0].text)
        assert data["download_url"].startswith("https://mcp.example.com/artifacts/")

    async def test_content_type_markdown_for_notes(self, _artifact_vault: Path) -> None:
        server = create_server(transport="http")
        async with Client(server) as client:
            result = await client.call_tool("create_download_link", {"path": "note.md"})
        data = json.loads(result.content[0].text)
        assert data["content_type"] == "text/markdown; charset=utf-8"

    async def test_content_type_for_attachment(self, _artifact_vault: Path) -> None:
        server = create_server(transport="http")
        async with Client(server) as client:
            result = await client.call_tool(
                "create_download_link", {"path": "assets/image.png"}
            )
        data = json.loads(result.content[0].text)
        assert data["content_type"] == "image/png"

    async def test_expires_in_seconds_matches_ttl(self, _artifact_vault: Path) -> None:
        server = create_server(transport="http")
        async with Client(server) as client:
            result = await client.call_tool(
                "create_download_link",
                {"path": "note.md", "ttl_seconds": 120},
            )
        data = json.loads(result.content[0].text)
        assert data["expires_in_seconds"] == 120

    async def test_raises_on_missing_base_url(
        self, _artifact_vault: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MARKDOWN_VAULT_MCP_BASE_URL", raising=False)
        server = create_server(transport="http")
        async with Client(server) as client:
            with pytest.raises(ToolError, match="MARKDOWN_VAULT_MCP_BASE_URL"):
                await client.call_tool("create_download_link", {"path": "note.md"})

    async def test_raises_on_nonexistent_path(self, _artifact_vault: Path) -> None:
        server = create_server(transport="http")
        async with Client(server) as client:
            with pytest.raises(ToolError, match=r"not found|does not exist"):
                await client.call_tool("create_download_link", {"path": "missing.md"})

    async def test_raises_on_path_traversal(self, _artifact_vault: Path) -> None:
        server = create_server(transport="http")
        async with Client(server) as client:
            with pytest.raises(ToolError, match="traversal"):
                await client.call_tool(
                    "create_download_link",
                    {"path": "../../../etc/shadow.md"},
                )


# ---------------------------------------------------------------------------
# Artifact HTTP endpoint handler
# ---------------------------------------------------------------------------


class TestArtifactHandler:
    """Tests for the GET /artifacts/{token} Starlette handler."""

    def _make_app(self, vault: Path) -> TestClient:
        """Build a minimal Starlette app with the artifact endpoint."""
        from starlette.applications import Starlette
        from starlette.routing import Route

        from markdown_vault_mcp.artifacts import (
            ArtifactStore,
            make_artifact_handler,
            set_artifact_store,
            set_collection_store,
        )
        from markdown_vault_mcp.collection import Collection

        collection = Collection(source_dir=vault, read_only=True)
        collection.build_index()

        art_store = ArtifactStore()
        set_artifact_store(art_store)
        set_collection_store(collection)

        handler = make_artifact_handler()
        app = Starlette(
            routes=[
                Route(
                    "/artifacts/{token}",
                    endpoint=handler,
                    methods=["GET"],
                )
            ]
        )
        client = TestClient(app, raise_server_exceptions=False)
        client._artifact_store = art_store  # type: ignore[attr-defined]
        client._collection = collection  # type: ignore[attr-defined]
        return client

    def test_serves_note_bytes(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        note_text = "# Hello\n\nWorld.\n"
        (vault / "hello.md").write_text(note_text, encoding="utf-8")

        client = self._make_app(vault)
        art_store: ArtifactStore = client._artifact_store  # type: ignore[attr-defined]
        token = art_store.create_token("hello.md")
        response = client.get(f"/artifacts/{token}")

        assert response.status_code == 200
        assert "text/markdown" in response.headers["content-type"]
        assert response.text == note_text

    def test_serves_attachment_bytes(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "dummy.md").write_text("# Dummy\n")
        (vault / "assets").mkdir()
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        (vault / "assets" / "image.png").write_bytes(raw)

        client = self._make_app(vault)
        art_store: ArtifactStore = client._artifact_store  # type: ignore[attr-defined]
        token = art_store.create_token("assets/image.png")
        response = client.get(f"/artifacts/{token}")

        assert response.status_code == 200
        assert "image/png" in response.headers["content-type"]
        assert response.content == raw

    def test_one_time_use(self, tmp_path: Path) -> None:
        """Second request with same token returns 404."""
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "note.md").write_text("# Note\n")

        client = self._make_app(vault)
        art_store: ArtifactStore = client._artifact_store  # type: ignore[attr-defined]
        token = art_store.create_token("note.md")
        first = client.get(f"/artifacts/{token}")
        second = client.get(f"/artifacts/{token}")

        assert first.status_code == 200
        assert second.status_code == 404

    def test_unknown_token_returns_404(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "note.md").write_text("# Note\n")

        client = self._make_app(vault)
        response = client.get("/artifacts/" + "deadbeef" * 4)
        assert response.status_code == 404

    def test_expired_token_returns_404(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "note.md").write_text("# Note\n")

        client = self._make_app(vault)
        art_store: ArtifactStore = client._artifact_store  # type: ignore[attr-defined]
        token = art_store.create_token("note.md", ttl_seconds=1)
        # Backdate the token to simulate expiry
        record = art_store._tokens[token]
        art_store._tokens[token] = TokenRecord(
            path=record.path,
            created_at=record.created_at - 10,
            ttl_seconds=1,
        )

        response = client.get(f"/artifacts/{token}")
        assert response.status_code == 404

    def test_missing_file_returns_404(self, tmp_path: Path) -> None:
        """Token valid but file deleted from disk returns 404."""
        vault = tmp_path / "vault"
        vault.mkdir()
        note = vault / "note.md"
        note.write_text("# Note\n")

        client = self._make_app(vault)
        art_store: ArtifactStore = client._artifact_store  # type: ignore[attr-defined]
        token = art_store.create_token("note.md")

        # Delete after creating token
        note.unlink()

        response = client.get(f"/artifacts/{token}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# create_server: artifact route mounted on HTTP but not stdio
# ---------------------------------------------------------------------------


class TestCreateServerArtifactRoute:
    """create_server mounts the artifact route for HTTP transport only."""

    @pytest.fixture(autouse=True)
    def _env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "note.md").write_text("# Note\n")
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault))
        monkeypatch.setenv("MARKDOWN_VAULT_MCP_READ_ONLY", "true")
        for var in _CLEAR_VARS:
            monkeypatch.delenv(var, raising=False)

    def test_artifact_route_not_registered_for_stdio(self) -> None:
        server = create_server(transport="stdio")
        routes = server._additional_http_routes
        paths = [getattr(r, "path", "") for r in routes]
        assert not any("/artifacts/" in p for p in paths)

    def test_artifact_route_registered_for_http(self) -> None:
        server = create_server(transport="http")
        routes = server._additional_http_routes
        paths = [getattr(r, "path", "") for r in routes]
        assert any("/artifacts/" in p for p in paths)
