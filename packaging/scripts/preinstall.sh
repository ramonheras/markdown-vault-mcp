#!/bin/bash
# Pre-install script: create system user and group for markdown-vault-mcp.
# Idempotent — safe to run multiple times.
set -eu

SERVICE_USER="markdown-vault-mcp"

if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
    groupadd --system "$SERVICE_USER"
fi

if ! getent passwd "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system \
        --gid "$SERVICE_USER" \
        --no-create-home \
        --home-dir /var/lib/markdown-vault-mcp \
        --shell /usr/sbin/nologin \
        --comment "Markdown Vault MCP Server" \
        "$SERVICE_USER"
fi
