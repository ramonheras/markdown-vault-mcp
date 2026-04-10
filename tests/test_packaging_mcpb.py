"""Smoke tests for the Claude Desktop .mcpb bundle and Claude Code plugin.

These tests do not run the packaged server — they assert that the packaging
files are syntactically valid and that invariants the release workflow
depends on (version strings, import paths) stay consistent.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MCPB_DIR = REPO_ROOT / "packaging" / "mcpb"
PLUGIN_DIR = REPO_ROOT / ".claude-plugin" / "plugin"


def test_cli_main_import_target_exists() -> None:
    """The mcpb shim imports markdown_vault_mcp.cli.main — make sure it exists."""
    from markdown_vault_mcp.cli import main

    assert callable(main)


def test_mcpb_server_shim_calls_main_serve() -> None:
    """The shim's only job is to invoke `cli.main(["serve"])`."""
    shim = MCPB_DIR / "src" / "server.py"
    assert shim.exists(), f"missing shim at {shim}"
    content = shim.read_text(encoding="utf-8")
    assert "from markdown_vault_mcp.cli import main" in content
    assert 'main(["serve"])' in content


def _load_manifest_template() -> dict:
    """Load the mcpb manifest template with ${VERSION} replaced by a literal."""
    template = (MCPB_DIR / "manifest.json.in").read_text(encoding="utf-8")
    rendered = template.replace("${VERSION}", "0.0.0-test")
    return json.loads(rendered)


def test_mcpb_manifest_template_valid_and_complete() -> None:
    """The mcpb manifest must parse and carry the fields the spec requires."""
    manifest = _load_manifest_template()

    assert manifest["manifest_version"] == "0.4"
    assert manifest["name"] == "markdown-vault-mcp"
    assert manifest["version"] == "0.0.0-test"

    server = manifest["server"]
    assert server["type"] == "uv"
    assert server["entry_point"] == "src/server.py"

    # mcp_config must NOT use --from . (local source dir) — that would fail at runtime in
    # an installed bundle.  If command is present it must reference the PyPI package by name.
    mcp_config = server["mcp_config"]
    if "args" in mcp_config:
        assert "--from" not in mcp_config["args"] or "." not in mcp_config["args"], (
            "mcp_config.args must not use '--from .' (local source); "
            "use '--from markdown-vault-mcp[all]==${VERSION}' instead"
        )
    env = server["mcp_config"]["env"]
    # The one truly required env var must be wired to the form.
    assert env["MARKDOWN_VAULT_MCP_SOURCE_DIR"] == "${user_config.source_dir}"

    user_config = manifest["user_config"]
    assert user_config["source_dir"]["required"] is True
    assert user_config["source_dir"]["type"] == "directory"
    # Sensitive fields must be marked so the host stores them in the keychain.
    assert user_config["openai_api_key"]["sensitive"] is True
    assert user_config["git_token"]["sensitive"] is True
