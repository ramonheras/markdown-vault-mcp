#!/usr/bin/env python3
"""Bump versioned manifests to match the semantic-release version.

Invoked by python-semantic-release via ``[tool.semantic_release] build_command``.
PSR sets ``NEW_VERSION`` in the environment and, because the three manifest
paths are listed in ``[tool.semantic_release] assets``, PSR stages and commits
them together with ``pyproject.toml`` + ``CHANGELOG.md`` as the single release
commit — which is the commit it then tags.

The script runs inside PSR's Docker action container (python:3.14-slim), which
has Python but no ``jq`` — hence Python rather than a shell+jq wrapper.

This MV-specific version extends the template's single-manifest (server.json)
bumper with two extra Claude Code plugin manifests that also need to move in
lockstep with the released package version:

- ``.claude-plugin/plugin/.claude-plugin/plugin.json`` — plugin ``version``
- ``.claude-plugin/plugin/.mcp.json`` — ``uvx --from markdown-vault-mcp[all]==<ver>``
  pin in the server's launch args.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _dump(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as fh:
        # ensure_ascii=False preserves UTF-8 characters literally, matching
        # jq's default behavior and how a human editor would save the file.
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def main() -> int:
    version = os.environ.get("NEW_VERSION")
    if not version:
        print(
            "NEW_VERSION must be set (python-semantic-release build_command env)",
            file=sys.stderr,
        )
        return 1

    # server.json: top-level version, PyPI package version, OCI tag suffix.
    # Replace only the ``:v<old>`` suffix of the OCI identifier so forks/renames
    # keep their own ``ghcr.io/<owner>/<image>`` base.
    server_path = Path("server.json")
    if not server_path.exists():
        print(
            f"server.json not found in {Path.cwd()} — run from repo root",
            file=sys.stderr,
        )
        return 1
    server = _load(server_path)
    if not isinstance(server, dict):
        print(
            f"{server_path} must contain a JSON object (top-level), "
            f"got {type(server).__name__}",
            file=sys.stderr,
        )
        return 1
    server["version"] = version
    packages = server.get("packages", [])
    if not isinstance(packages, list):
        print(
            f"{server_path}: 'packages' must be a JSON array, got "
            f"{type(packages).__name__}",
            file=sys.stderr,
        )
        return 1
    for i, pkg in enumerate(packages):
        if not isinstance(pkg, dict):
            print(
                f"WARNING: packages[{i}] is not a JSON object "
                f"(got {type(pkg).__name__}) — skipped",
                file=sys.stderr,
            )
            continue
        if pkg.get("registryType") == "pypi":
            pkg["version"] = version
        elif pkg.get("registryType") == "oci":
            # ``or ""`` covers both the absent-key and the JSON-null cases;
            # ``dict.get(key, default)`` only returns default when the key
            # is absent, not when the value is None.
            identifier = pkg.get("identifier") or ""
            new_id, n = re.subn(r":v[^:]+$", f":v{version}", identifier)
            if n == 0:
                print(
                    f"WARNING: OCI identifier {identifier!r} has no ':v<tag>' "
                    "suffix to bump — left unchanged",
                    file=sys.stderr,
                )
            pkg["identifier"] = new_id
    _dump(server_path, server)

    # Claude Code plugin.json: plugin version, lockstep with the package.
    plugin_path = Path(".claude-plugin/plugin/.claude-plugin/plugin.json")
    plugin = _load(plugin_path)
    plugin["version"] = version
    _dump(plugin_path, plugin)

    # Claude Code .mcp.json: pin uvx --from spec to the released version.
    mcp_path = Path(".claude-plugin/plugin/.mcp.json")
    mcp = _load(mcp_path)
    mcp["markdown-vault-mcp"]["args"] = [
        "--from",
        f"markdown-vault-mcp[all]=={version}",
        "markdown-vault-mcp",
        "serve",
    ]
    _dump(mcp_path, mcp)

    print(f"bump_manifests: server.json → {version}")
    print(f"bump_manifests: {plugin_path} → {version}")
    print(f"bump_manifests: {mcp_path} → markdown-vault-mcp[all]=={version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
