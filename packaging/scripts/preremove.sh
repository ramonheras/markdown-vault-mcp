#!/bin/bash
# Pre-remove script: stop and disable the service.
set -eu

SERVICE_NAME="markdown-vault-mcp"

# Stop the service if running
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl stop "$SERVICE_NAME"
fi

# Disable the service
if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl disable "$SERVICE_NAME"
fi
