"""Entry shim for the markdown-vault-mcp .mcpb bundle.

This file is only executed when the host uses the ``uv run src/server.py``
code path (``server.type: "uv"`` + ``entry_point``).  The primary launch path
is ``mcp_config.command: "uvx"`` which fetches markdown-vault-mcp directly
from PyPI and bypasses this shim entirely.

The shim injects ``serve`` into ``sys.argv`` because ``cli.main()`` delegates
to argparse which reads ``sys.argv``; the bundle host does not pass subcommands.
"""

import sys

from markdown_vault_mcp.cli import main

sys.argv = [sys.argv[0], "serve"]
main()
