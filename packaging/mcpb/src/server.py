"""Entry shim for the markdown-vault-mcp .mcpb bundle.

Claude Desktop invokes this file through the host-provided uv runtime. The
bundle's pyproject.toml pins ``markdown-vault-mcp[all]==<version>``; uv
resolves the dependency tree on install and this shim just delegates to the
package's CLI.
"""

from markdown_vault_mcp.cli import main

if __name__ == "__main__":
    main(["serve"])
