"""End-to-end tests for the ``git_sync`` MCP tool (added in #444).

The tool composes :meth:`GitWriteStrategy.force_pull` and
:meth:`GitWriteStrategy.force_push` behind a single MCP call.  These
tests drive the tool through the in-memory :class:`fastmcp.Client` so we
verify both the registered shape and the wire-level response.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from fastmcp import Client

from markdown_vault_mcp.server import make_server
from tests.fixtures.git import _run_git

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.git import GitRepoPair


_CLEAR_VARS = (
    "MARKDOWN_VAULT_MCP_INDEX_PATH",
    "MARKDOWN_VAULT_MCP_EMBEDDINGS_PATH",
    "MARKDOWN_VAULT_MCP_STATE_PATH",
    "MARKDOWN_VAULT_MCP_INDEXED_FIELDS",
    "MARKDOWN_VAULT_MCP_REQUIRED_FIELDS",
    "MARKDOWN_VAULT_MCP_EXCLUDE",
    "MARKDOWN_VAULT_MCP_GIT_TOKEN",
    "MARKDOWN_VAULT_MCP_GIT_REPO_URL",
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
)


@pytest.fixture
def _git_managed_env(
    git_repo_pair: GitRepoPair, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Wire ``make_server`` to the bare-remote + local-clone fixture in managed mode.

    Sets ``READ_ONLY=false`` (write tools must be visible) and disables
    the periodic pull loop (the test drives sync explicitly via the
    tool).  Returns the local clone path so tests can stage commits
    against the working tree.
    """
    for var in _CLEAR_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(git_repo_pair.local_path))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_READ_ONLY", "false")
    monkeypatch.setenv(
        "MARKDOWN_VAULT_MCP_GIT_REPO_URL", str(git_repo_pair.remote_path)
    )
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_GIT_PULL_INTERVAL_S", "0")
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_GIT_PUSH_DELAY_S", "0")
    return git_repo_pair.local_path


def _seed_remote_commit(
    pair: GitRepoPair, *, clone_name: str, file_name: str, body: str
) -> None:
    """Push one new commit to the bare remote from a sibling clone.

    Mirrors the helper in ``test_git_force_methods.py`` so this module is
    self-contained — both modules use the same bare-remote fixture but
    test different layers (strategy unit tests vs. MCP tool integration).
    """
    sibling = pair.remote_path.parent / clone_name
    sibling.mkdir()
    _run_git(sibling, "init", "--initial-branch=main")
    _run_git(sibling, "config", "user.email", "other@example.com")
    _run_git(sibling, "config", "user.name", "Other")
    _run_git(sibling, "remote", "add", "origin", str(pair.remote_path))
    _run_git(sibling, "pull", "origin", "main")
    (sibling / file_name).write_text(body)
    _run_git(sibling, "add", file_name)
    _run_git(sibling, "commit", "-m", f"remote commit: {file_name}")
    _run_git(sibling, "push", "origin", "main")


def _parse_tool_data(result: Any) -> Any:
    """Extract the tool's structured payload from a ``CallToolResult``.

    FastMCP v2 returns dicts directly via ``result.data``; this helper
    falls back to parsing the raw text content when the typed accessor
    cannot resolve the shape.
    """
    data = result.data
    if isinstance(data, dict):
        return data
    raw = result.content[0].text if result.content else "{}"
    return json.loads(raw)


class TestGitSync:
    """:tool:`git_sync` integration tests through the in-memory MCP client."""

    async def test_clean_both_direction_pulls_and_pushes(
        self, git_repo_pair: GitRepoPair, _git_managed_env: Path
    ) -> None:
        """direction='both' on a clean clone runs both legs and reports applied=True."""
        # Stage one local commit so the push leg has something to send.
        (git_repo_pair.local_path / "local.md").write_text("local\n")
        _run_git(git_repo_pair.local_path, "add", "local.md")
        _run_git(git_repo_pair.local_path, "commit", "-m", "local commit")

        server = make_server()
        async with Client(server) as client:
            result = await client.call_tool("git_sync", {"direction": "both"})

        payload = _parse_tool_data(result)

        assert payload["direction"] == "both"
        assert "head_sha" in payload and len(payload["head_sha"]) == 40
        assert "branch" in payload
        assert payload["pull"] is not None
        assert payload["pull"]["applied"] is True
        assert payload["push"] is not None
        assert payload["push"]["applied"] is True
        assert payload["push"]["commits_pushed"] == 1
        # dry_run key is only present when the caller passed dry_run=True.
        assert "dry_run" not in payload

    async def test_pull_only_direction_skips_push(
        self, git_repo_pair: GitRepoPair, _git_managed_env: Path
    ) -> None:
        """direction='pull' fast-forwards the local clone and leaves push untouched."""
        _seed_remote_commit(
            git_repo_pair,
            clone_name="clone_pull_only",
            file_name="seeded.md",
            body="seeded\n",
        )

        server = make_server()
        async with Client(server) as client:
            result = await client.call_tool("git_sync", {"direction": "pull"})

        payload = _parse_tool_data(result)

        assert payload["direction"] == "pull"
        assert payload["pull"] is not None
        assert payload["pull"]["applied"] is True
        assert payload["pull"]["commits_pulled"] == 1
        assert payload["push"] is None  # push leg not invoked

    async def test_dry_run_pull_does_not_modify_head(
        self, git_repo_pair: GitRepoPair, _git_managed_env: Path
    ) -> None:
        """dry_run=True predicts the would-be pull without moving HEAD."""
        _seed_remote_commit(
            git_repo_pair,
            clone_name="clone_dry",
            file_name="dryseed.md",
            body="dry\n",
        )

        head_before = _run_git(git_repo_pair.local_path, "rev-parse", "HEAD").strip()

        server = make_server()
        async with Client(server) as client:
            result = await client.call_tool(
                "git_sync", {"direction": "pull", "dry_run": True}
            )

        head_after = _run_git(git_repo_pair.local_path, "rev-parse", "HEAD").strip()
        payload = _parse_tool_data(result)

        assert head_before == head_after  # HEAD did not move
        assert payload["dry_run"] is True
        assert payload["pull"] is not None
        # In dry-run mode the response carries the projection, not actual.
        assert payload["pull"]["applied"] is False
        assert payload["pull"]["would_apply"] is True
        assert payload["pull"]["commits_pulled"] == 1
        assert not (git_repo_pair.local_path / "dryseed.md").exists()
