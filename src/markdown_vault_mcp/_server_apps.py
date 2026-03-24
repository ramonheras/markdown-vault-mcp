"""MCP Apps registrations — SPA shell resource and app-related tools.

Provides :func:`register_apps` to set up the vault SPA shell as a
``ui://`` resource and register app-aware tools (``browse_vault``,
``show_context``, and app-only data-fetching tools hidden from the LLM).

Call :func:`register_apps` after constructing the :class:`~fastmcp.FastMCP`
instance in :func:`~markdown_vault_mcp.mcp_server.create_server`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import asdict
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.dependencies import Depends
from fastmcp.server.apps import AppConfig, ResourceCSP

from markdown_vault_mcp.collection import Collection
from markdown_vault_mcp.config import _ENV_PREFIX

from ._icons import _TOOL_ICONS
from ._server_deps import get_collection

logger = logging.getLogger(__name__)

_VAULT_APP_URI = "ui://vault/app.html"

# CDN dependencies loaded by the SPA shell.
_CDN_RESOURCE_DOMAINS = ["https://unpkg.com"]


def _compute_claude_app_domain() -> str | None:
    """Auto-compute Claude's MCP Apps sandbox domain from BASE_URL.

    Claude requires ``{sha256_prefix}.claudemcpcontent.com`` where the hash
    is derived from the full MCP endpoint URL the client connects to.

    Returns:
        The computed domain string, or ``None`` when ``BASE_URL`` is not set
        (e.g. stdio transport or local development).
    """
    base_url = os.environ.get(f"{_ENV_PREFIX}_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return None
    http_path = os.environ.get(f"{_ENV_PREFIX}_HTTP_PATH", "/mcp").strip() or "/mcp"
    if not http_path.startswith("/"):
        http_path = f"/{http_path}"
    if len(http_path) > 1:
        http_path = http_path.rstrip("/")
    mcp_url = f"{base_url}{http_path}"
    hash_prefix = hashlib.sha256(mcp_url.encode()).hexdigest()[:32]
    return f"{hash_prefix}.claudemcpcontent.com"


# ---------------------------------------------------------------------------
# SPA shell HTML
# ---------------------------------------------------------------------------

_SPA_SHELL_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Vault Explorer</title>
<script type="module" src="https://unpkg.com/@anthropic-ai/claude-mcp-ext-apps@latest/dist/index.js"></script>
<style>
  :root {
    --fallback-bg: #ffffff;
    --fallback-fg: #1a1a1a;
    --fallback-border: #e0e0e0;
    --fallback-accent: #6366f1;
    --fallback-muted: #6b7280;
    --fallback-surface: #f5f5f5;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: var(--host-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
    background: var(--host-bg, var(--fallback-bg));
    color: var(--host-fg, var(--fallback-fg));
    line-height: 1.5;
    overflow: hidden;
    height: 100vh;
  }
  .app-container {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  /* Tab bar */
  .tab-bar {
    display: flex;
    border-bottom: 1px solid var(--host-border, var(--fallback-border));
    background: var(--host-surface, var(--fallback-surface));
    flex-shrink: 0;
  }
  .tab-bar button {
    flex: 1;
    padding: 8px 12px;
    border: none;
    background: transparent;
    color: var(--host-muted, var(--fallback-muted));
    cursor: pointer;
    font-size: 13px;
    font-family: inherit;
    border-bottom: 2px solid transparent;
    transition: color 0.15s, border-color 0.15s;
  }
  .tab-bar button:hover {
    color: var(--host-fg, var(--fallback-fg));
  }
  .tab-bar button.active {
    color: var(--host-accent, var(--fallback-accent));
    border-bottom-color: var(--host-accent, var(--fallback-accent));
    font-weight: 600;
  }
  /* Header with fullscreen toggle */
  .app-header {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    padding: 4px 8px;
    flex-shrink: 0;
  }
  .fullscreen-btn {
    background: none;
    border: 1px solid var(--host-border, var(--fallback-border));
    color: var(--host-muted, var(--fallback-muted));
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-family: inherit;
  }
  .fullscreen-btn:hover {
    color: var(--host-fg, var(--fallback-fg));
    background: var(--host-surface, var(--fallback-surface));
  }
  /* Tab panels */
  .tab-panel {
    display: none;
    flex: 1;
    overflow: auto;
    padding: 12px;
  }
  .tab-panel.active { display: flex; flex-direction: column; }
  .placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    flex: 1;
    color: var(--host-muted, var(--fallback-muted));
    font-size: 14px;
  }
  /* Toast notifications */
  .toast {
    position: fixed;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--host-fg, var(--fallback-fg));
    color: var(--host-bg, var(--fallback-bg));
    padding: 8px 16px;
    border-radius: 6px;
    font-size: 13px;
    opacity: 0;
    transition: opacity 0.3s;
    pointer-events: none;
    z-index: 1000;
  }
  .toast.visible { opacity: 1; }
</style>
</head>
<body>
<div class="app-container">
  <div class="app-header">
    <button class="fullscreen-btn" id="fullscreenBtn" style="display:none;"
            title="Toggle fullscreen">&#x26F6; Fullscreen</button>
  </div>
  <div class="tab-bar" id="tabBar">
    <button data-tab="context" class="active">Context</button>
    <button data-tab="graph">Graph</button>
    <button data-tab="browse">Browse</button>
  </div>
  <div class="tab-panel active" id="panel-context" data-tab="context">
    <div class="placeholder">Select a note to view its context</div>
  </div>
  <div class="tab-panel" id="panel-graph" data-tab="graph">
    <div class="placeholder">Graph explorer — loading&hellip;</div>
  </div>
  <div class="tab-panel" id="panel-browse" data-tab="browse">
    <div class="placeholder">Vault browser — loading&hellip;</div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script type="module">
import { createApp } from 'https://unpkg.com/@anthropic-ai/claude-mcp-ext-apps@latest/dist/index.js';

// ── Globals ──────────────────────────────────────────────────────────────
const app = createApp();
let currentTab = 'context';
let isFullscreen = false;

// ── Host theming ─────────────────────────────────────────────────────────
function applyHostTheme(hostContext) {
  if (!hostContext) return;
  const root = document.documentElement;
  if (hostContext.theme) {
    root.style.setProperty('--host-bg', hostContext.theme.backgroundColor || '');
    root.style.setProperty('--host-fg', hostContext.theme.foregroundColor || '');
    root.style.setProperty('--host-border', hostContext.theme.borderColor || '');
    root.style.setProperty('--host-accent', hostContext.theme.accentColor || '');
    root.style.setProperty('--host-muted', hostContext.theme.mutedColor || '');
    root.style.setProperty('--host-surface', hostContext.theme.surfaceColor || '');
  }
  if (hostContext.fonts) {
    root.style.setProperty('--host-font-family', hostContext.fonts.fontFamily || '');
  }
}

// ── Tab navigation ───────────────────────────────────────────────────────
function switchTab(tabName) {
  currentTab = tabName;
  document.querySelectorAll('.tab-bar button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.dataset.tab === tabName);
  });
  // Emit event for views to react
  window.dispatchEvent(new CustomEvent('vault-tab-changed', { detail: { tab: tabName } }));
}

document.getElementById('tabBar').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-tab]');
  if (btn) switchTab(btn.dataset.tab);
});

// ── Cross-view navigation API ────────────────────────────────────────────
window.navigateTo = function navigateTo(view, params = {}) {
  switchTab(view);
  window.dispatchEvent(new CustomEvent('vault-navigate', {
    detail: { view, ...params }
  }));
};

// ── Display mode (fullscreen toggle) ─────────────────────────────────────
const fullscreenBtn = document.getElementById('fullscreenBtn');

function updateFullscreenButton(available) {
  fullscreenBtn.style.display = available ? 'block' : 'none';
}

fullscreenBtn.addEventListener('click', async () => {
  try {
    if (isFullscreen) {
      await app.setDisplayMode('inline');
      fullscreenBtn.textContent = '\\u26F6 Fullscreen';
      isFullscreen = false;
    } else {
      await app.setDisplayMode('fullscreen');
      fullscreenBtn.textContent = '\\u2716 Exit Fullscreen';
      isFullscreen = true;
    }
  } catch (err) {
    console.warn('Display mode change failed:', err);
  }
});

// ── Toast helper ─────────────────────────────────────────────────────────
window.showToast = function showToast(message, durationMs = 2000) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.classList.add('visible');
  setTimeout(() => toast.classList.remove('visible'), durationMs);
};

// ── Shared send-to-LLM helper ───────────────────────────────────────────
window.sendToLLM = async function sendToLLM(path, content) {
  const MAX_LEN = 4000;
  let body = content;
  if (body.length > MAX_LEN) {
    body = body.slice(0, MAX_LEN) + "\\n... [truncated \\u2014 use read('" + path + "') for full content]";
  }
  try {
    await app.sendMessage({
      role: 'user',
      content: { type: 'text', text: '[From Vault App] Note: ' + path + '\\n\\n' + body }
    });
    window.showToast('Sent to Claude');
  } catch (err) {
    window.showToast('Send failed: ' + (err.message || err));
  }
};

// ── Shared ambient context helper ────────────────────────────────────────
window.updateContext = async function updateContext(viewName, path, title, extras) {
  const lines = ['User is viewing ' + viewName + ': ' + path];
  if (title) lines.push('Title: ' + title);
  if (extras) lines.push(extras);
  try {
    await app.updateModelContext({
      content: [{ type: 'text', text: lines.join('\\n') }]
    });
  } catch (err) {
    console.warn('updateModelContext failed:', err);
  }
};

// ── Expose app for views ─────────────────────────────────────────────────
window.vaultApp = app;

// ── Handler registration (before connect) ────────────────────────────────

app.onToolResult(async (result) => {
  // Tool results are dispatched to views via custom events
  window.dispatchEvent(new CustomEvent('vault-tool-result', { detail: result }));
});

app.onDisplayModeChanged((mode) => {
  isFullscreen = mode === 'fullscreen';
  fullscreenBtn.textContent = isFullscreen ? '\\u2716 Exit Fullscreen' : '\\u26F6 Fullscreen';
});

// ── Connect ──────────────────────────────────────────────────────────────
app.connect().then((hostContext) => {
  applyHostTheme(hostContext);

  // Show fullscreen button if host supports it
  const modes = hostContext?.availableDisplayModes || [];
  updateFullscreenButton(modes.includes('fullscreen'));

  // If launched with initial params, navigate
  const params = hostContext?.toolInput;
  if (params?.view) {
    switchTab(params.view);
  }
  if (params?.path) {
    window.dispatchEvent(new CustomEvent('vault-navigate', {
      detail: { view: params.view || currentTab, path: params.path }
    }));
  }

  console.log('Vault Explorer connected', hostContext);
}).catch(err => {
  console.error('Failed to connect to host:', err);
});

// ── Teardown ─────────────────────────────────────────────────────────────
app.onTeardown(() => {
  console.log('Vault Explorer teardown');
});
</script>
</body>
</html>
"""


def register_apps(mcp: FastMCP) -> None:
    """Register MCP Apps resources and app-related tools on *mcp*.

    Sets up the vault SPA shell as a ``ui://vault/app.html`` resource
    and registers the ``browse_vault`` primary tool and app-only tools
    for downstream views.

    Args:
        mcp: The :class:`~fastmcp.FastMCP` instance to register on.
    """
    # Resolve app domain for Claude's sandbox iframe.
    app_domain: str | None = (
        os.environ.get(f"{_ENV_PREFIX}_APP_DOMAIN", "").strip()
        or _compute_claude_app_domain()
    )
    if app_domain:
        logger.info("MCP Apps domain: %s", app_domain)
    else:
        logger.debug("MCP Apps domain: not configured (stdio or no BASE_URL)")

    app_config = AppConfig(
        domain=app_domain,
        csp=ResourceCSP(resourceDomains=_CDN_RESOURCE_DOMAINS),
    )

    # -- SPA shell resource -------------------------------------------------

    @mcp.resource(
        _VAULT_APP_URI,
        description="Interactive vault explorer with context card, graph, and browser views.",
        icons=_TOOL_ICONS["browse_vault"],
        app=app_config,
    )
    def vault_app() -> str:
        """HTML SPA shell loaded by MCP Apps-capable clients.

        Provides tabbed navigation between Context, Graph, and Browse views.
        Loaded in a sandboxed iframe by Claude Desktop or claude.ai.
        """
        return _SPA_SHELL_HTML

    # -- Primary tool: browse_vault -----------------------------------------

    @mcp.tool(
        icons=_TOOL_ICONS["browse_vault"],
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
        app=AppConfig(resourceUri=_VAULT_APP_URI),
    )
    async def browse_vault(
        path: str | None = None,
        view: Literal["context", "graph", "browse"] | None = None,
        collection: Collection = Depends(get_collection),
    ) -> dict[str, Any]:
        """Open the vault explorer to browse notes, view context, or explore the link graph.

        Opens an interactive visual explorer in MCP Apps-capable clients.
        For non-MCP-Apps clients, returns a text summary of the vault or note.

        Args:
            path: Optional note path to focus on (e.g. ``"Journal/2024-01-15.md"``).
            view: Which view to open: ``"context"`` (note relationships),
                ``"graph"`` (link visualization), or ``"browse"`` (tree + preview).
                Defaults to ``"context"`` if a path is given, ``"browse"`` otherwise.

        Returns:
            - ``path``: the requested path (or ``null``)
            - ``view``: the requested view
            - ``summary``: text summary for non-Apps clients
        """
        effective_view = view or ("context" if path else "browse")
        summary_parts: list[str] = []

        if path:
            note = await asyncio.to_thread(collection.read, path)
            if note:
                summary_parts.append(f"Note: {note.title} ({path})")
                summary_parts.append(f"Folder: {note.folder}")
                if note.frontmatter:
                    fm_keys = ", ".join(note.frontmatter.keys())
                    summary_parts.append(f"Frontmatter: {fm_keys}")
            else:
                summary_parts.append(f"Note not found: {path}")
        else:
            stats = await asyncio.to_thread(collection.stats)
            summary_parts.append(
                f"Vault: {stats.document_count} notes, {stats.folder_count} folders"
            )
            if stats.semantic_search_available:
                summary_parts.append("Semantic search: available")

        return {
            "path": path,
            "view": effective_view,
            "summary": "\n".join(summary_parts),
        }

    # -- App-only tools (hidden from LLM, used by SPA via callServerTool) ---

    @mcp.tool(
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        app=AppConfig(resourceUri=_VAULT_APP_URI, visibility=["app"]),
    )
    async def _vault_context(
        path: str,
        collection: Collection = Depends(get_collection),
    ) -> dict[str, Any]:
        """Return the full NoteContext for a note (app-only).

        Called by the SPA context card view via ``app.callServerTool()``.
        Not visible to the LLM.

        Args:
            path: Relative note path (e.g. ``"Journal/2024-01-15.md"``).

        Returns:
            NoteContext as a JSON-serializable dict.
        """
        ctx = await asyncio.to_thread(collection.get_context, path)
        return asdict(ctx)

    @mcp.tool(
        icons=_TOOL_ICONS["get_context"],
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
        app=AppConfig(resourceUri=_VAULT_APP_URI),
    )
    async def show_context(
        path: str,
        collection: Collection = Depends(get_collection),
    ) -> dict[str, Any]:
        """Show a visual context card for a note in the vault explorer.

        Opens the context card view in MCP Apps-capable clients, showing
        backlinks, outlinks, similar notes, tags, and frontmatter.
        For non-Apps clients, returns a text summary.

        Args:
            path: Relative note path (e.g. ``"Journal/2024-01-15.md"``).

        Returns:
            - ``path``: the note path
            - ``view``: ``"context"``
            - ``summary``: text summary with relationship counts
        """
        ctx = await asyncio.to_thread(collection.get_context, path)
        summary_parts = [
            f"Context for: {ctx.title} ({path})",
            f"Folder: {ctx.folder}",
            f"Backlinks: {len(ctx.backlinks)}",
            f"Outlinks: {len(ctx.outlinks)}",
            f"Similar notes: {len(ctx.similar)}",
            f"Folder peers: {len(ctx.folder_notes)}",
        ]
        if ctx.tags:
            tag_count = sum(len(v) for v in ctx.tags.values())
            summary_parts.append(f"Tags: {tag_count} across {len(ctx.tags)} fields")

        return {
            "path": path,
            "view": "context",
            "summary": "\n".join(summary_parts),
        }

    @mcp.tool(
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        app=AppConfig(resourceUri=_VAULT_APP_URI, visibility=["app"]),
    )
    async def _vault_graph_neighborhood(
        path: str,
        depth: int = 1,
        collection: Collection = Depends(get_collection),
    ) -> dict[str, Any]:
        """Return the link neighborhood of a note as a node/edge graph (app-only).

        Called by the SPA graph view via ``app.callServerTool()``.
        Not visible to the LLM.

        Args:
            path: Center note path.
            depth: How many hops to traverse (default 1).

        Returns:
            ``{nodes: [{id, label, group}], edges: [{from, to, type}]}``
        """
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(path, 0)]

        while queue:
            current, d = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            # Add node
            note = await asyncio.to_thread(collection.read, current)
            label = (
                note.title if note else current.rsplit("/", 1)[-1].replace(".md", "")
            )
            nodes[current] = {"id": current, "label": label, "group": "note"}

            if d >= depth:
                continue

            # Get backlinks
            backlinks = await asyncio.to_thread(collection.get_backlinks, current)
            for bl in backlinks:
                edges.append(
                    {
                        "from": bl.source_path,
                        "to": current,
                        "type": bl.link_type,
                    }
                )
                if bl.source_path not in visited:
                    queue.append((bl.source_path, d + 1))

            # Get outlinks
            outlinks = await asyncio.to_thread(collection.get_outlinks, current)
            for ol in outlinks:
                if ol.exists:
                    edges.append(
                        {
                            "from": current,
                            "to": ol.target_path,
                            "type": ol.link_type,
                        }
                    )
                    if ol.target_path not in visited:
                        queue.append((ol.target_path, d + 1))

        # Deduplicate edges
        seen_edges: set[tuple[str, str]] = set()
        unique_edges: list[dict[str, Any]] = []
        for e in edges:
            key = (e["from"], e["to"])
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)

        return {"nodes": list(nodes.values()), "edges": unique_edges}

    @mcp.tool(
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        app=AppConfig(resourceUri=_VAULT_APP_URI, visibility=["app"]),
    )
    async def _vault_graph_hubs(
        limit: int = 20,
        collection: Collection = Depends(get_collection),
    ) -> dict[str, Any]:
        """Return the most-linked notes and their connections as a graph (app-only).

        Called by the SPA graph view for the hub overview.
        Not visible to the LLM.

        Args:
            limit: Max number of hub notes to include.

        Returns:
            ``{nodes: [{id, label, group, backlink_count}], edges: [{from, to, type}]}``
        """
        hubs = await asyncio.to_thread(collection.get_most_linked, limit=limit)
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        for hub in hubs:
            nodes[hub.path] = {
                "id": hub.path,
                "label": hub.title,
                "group": "hub",
                "backlink_count": hub.backlink_count,
            }

            # Get immediate connections for each hub
            backlinks = await asyncio.to_thread(collection.get_backlinks, hub.path)
            for bl in backlinks:
                if bl.source_path not in nodes:
                    note = await asyncio.to_thread(collection.read, bl.source_path)
                    label = (
                        note.title
                        if note
                        else bl.source_path.rsplit("/", 1)[-1].replace(".md", "")
                    )
                    nodes[bl.source_path] = {
                        "id": bl.source_path,
                        "label": label,
                        "group": "note",
                    }
                edges.append(
                    {
                        "from": bl.source_path,
                        "to": hub.path,
                        "type": bl.link_type,
                    }
                )

        return {"nodes": list(nodes.values()), "edges": edges}

    @mcp.tool(
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        app=AppConfig(resourceUri=_VAULT_APP_URI, visibility=["app"]),
    )
    async def _vault_list(
        folder: str | None = None,
        collection: Collection = Depends(get_collection),
    ) -> dict[str, Any]:
        """List folders and notes in a vault directory (app-only).

        Called by the SPA browser view via ``app.callServerTool()``.
        Not visible to the LLM.

        Args:
            folder: Folder to list (root if omitted).

        Returns:
            ``{folders: [str], notes: [{path, title, kind}]}``
        """
        docs = await asyncio.to_thread(
            collection.list, folder=folder, include_attachments=True
        )
        folders = await asyncio.to_thread(collection.list_folders)

        # Filter folders to direct children of the requested folder
        prefix = (folder.rstrip("/") + "/") if folder else ""
        child_folders = sorted(
            {
                f
                for f in folders
                if f.startswith(prefix) and "/" not in f[len(prefix) :] and f != folder
            }
        )

        notes = [
            {
                "path": d.path,
                "title": getattr(d, "title", d.path.rsplit("/", 1)[-1]),
                "kind": d.kind,
            }
            for d in docs
        ]

        return {"folders": child_folders, "notes": notes}

    @mcp.tool(
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        app=AppConfig(resourceUri=_VAULT_APP_URI, visibility=["app"]),
    )
    async def _vault_read(
        path: str,
        collection: Collection = Depends(get_collection),
    ) -> dict[str, Any] | None:
        """Read a note's full content for preview rendering (app-only).

        Called by the SPA browser view via ``app.callServerTool()``.
        Not visible to the LLM.

        Args:
            path: Relative note path.

        Returns:
            ``{path, title, frontmatter, content, modified_at}`` or ``null``.
        """
        note = await asyncio.to_thread(collection.read, path)
        if note is None:
            return None
        return {
            "path": note.path,
            "title": note.title,
            "frontmatter": note.frontmatter,
            "content": note.content,
            "modified_at": note.modified_at,
        }

    @mcp.tool(
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        app=AppConfig(resourceUri=_VAULT_APP_URI, visibility=["app"]),
    )
    async def _vault_search(
        query: str,
        mode: Literal["keyword", "semantic", "hybrid"] = "hybrid",
        limit: int = 20,
        collection: Collection = Depends(get_collection),
    ) -> list[dict[str, Any]]:
        """Search the vault (app-only).

        Called by the SPA browser search bar via ``app.callServerTool()``.
        Not visible to the LLM.

        Args:
            query: Search query string.
            mode: Search mode (keyword, semantic, or hybrid).
            limit: Max results.

        Returns:
            List of ``{path, title, snippet, score}``.
        """
        results = await asyncio.to_thread(
            collection.search, query, limit=limit, mode=mode
        )
        return [
            {
                "path": r.path,
                "title": r.title,
                "snippet": r.content[:200] if r.content else "",
                "score": r.score,
            }
            for r in results
        ]
