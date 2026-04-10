"""Smoke tests for the Claude Desktop .mcpb bundle and Claude Code plugin.

These tests do not run the packaged server — they assert that the packaging
files are syntactically valid and that invariants the release workflow
depends on (version strings, import paths) stay consistent.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MCPB_DIR = REPO_ROOT / "packaging" / "mcpb"
PLUGIN_DIR = REPO_ROOT / ".claude-plugin" / "plugin"


def test_cli_main_import_target_exists() -> None:
    """The mcpb shim imports markdown_vault_mcp.cli.main — make sure it exists."""
    from markdown_vault_mcp.cli import main

    assert callable(main)
