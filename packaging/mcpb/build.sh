#!/usr/bin/env bash
# Build a markdown-vault-mcp .mcpb bundle locally.
#
# Usage:
#   VERSION=1.20.1 ./packaging/mcpb/build.sh
#
# With no VERSION set, builds a "dev" bundle for validation only.
set -euo pipefail

VERSION="${VERSION:-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_DIR="${REPO_ROOT}/packaging/mcpb/build"
DIST_DIR="${REPO_ROOT}/packaging/mcpb/dist"

command -v mcpb >/dev/null 2>&1 || {
  echo "error: mcpb CLI not found. Install with:" >&2
  echo "  npm install -g @anthropic-ai/mcpb@latest" >&2
  exit 1
}

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/src" "${DIST_DIR}"

VERSION="${VERSION}" envsubst < "${SCRIPT_DIR}/manifest.json.in" \
  > "${BUILD_DIR}/manifest.json"
VERSION="${VERSION}" envsubst < "${SCRIPT_DIR}/pyproject.toml.in" \
  > "${BUILD_DIR}/pyproject.toml"
cp "${SCRIPT_DIR}/src/server.py" "${BUILD_DIR}/src/server.py"

mcpb validate "${BUILD_DIR}/manifest.json"
mcpb pack "${BUILD_DIR}" "${DIST_DIR}/markdown-vault-mcp-${VERSION}.mcpb"

echo "built ${DIST_DIR}/markdown-vault-mcp-${VERSION}.mcpb"
