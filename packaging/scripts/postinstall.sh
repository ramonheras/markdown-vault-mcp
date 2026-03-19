#!/bin/bash
# Post-install script: create venv and install markdown-vault-mcp from PyPI.
set -eu

INSTALL_DIR="/opt/markdown-vault-mcp"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE_USER="markdown-vault-mcp"

# Determine package version — set by nfpm via VERSION env var, or read
# from the installed package metadata as fallback.
PKG_VERSION="${VERSION:-}"

# Create install directory
mkdir -p "$INSTALL_DIR"

# Create or update the virtual environment
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Upgrade pip and install the package
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip

if [ -n "$PKG_VERSION" ]; then
    "${VENV_DIR}/bin/pip" install --quiet "markdown-vault-mcp[all]==${PKG_VERSION}"
else
    "${VENV_DIR}/bin/pip" install --quiet "markdown-vault-mcp[all]"
fi

# Ensure state directory exists with correct ownership
mkdir -p /var/lib/markdown-vault-mcp
chown "$SERVICE_USER:$SERVICE_USER" /var/lib/markdown-vault-mcp

# Ensure config directory exists
mkdir -p /etc/markdown-vault-mcp

# Copy example env if no config exists yet
if [ ! -f /etc/markdown-vault-mcp/env ]; then
    if [ -f /etc/markdown-vault-mcp/env.example ]; then
        cp /etc/markdown-vault-mcp/env.example /etc/markdown-vault-mcp/env
    fi
fi

# Reload systemd to pick up the unit file
systemctl daemon-reload
