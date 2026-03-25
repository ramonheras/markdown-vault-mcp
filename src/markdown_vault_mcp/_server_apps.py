"""MCP Apps registrations — SPA shell resource and app-related tools.

Provides :func:`register_apps` to set up the vault SPA shell as a
``ui://`` resource and register app-aware tools (``browse_vault``,
``show_context``, and app-only data-fetching tools hidden from the LLM).

Call :func:`register_apps` after constructing the :class:`~fastmcp.FastMCP`
instance in :func:`~markdown_vault_mcp.mcp_server.create_server`.
"""

from __future__ import annotations

import asyncio
import collections
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
<script src="https://unpkg.com/vis-network@10.0.2/standalone/umd/vis-network.min.js"></script>
<script src="https://unpkg.com/marked@17.0.5/marked.min.js"></script>
<script src="https://unpkg.com/dompurify@3.3.3/dist/purify.min.js"></script>
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
    position: relative;
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
  /* Context card styles */
  .context-header { margin-bottom: 12px; }
  .context-title-row {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
  }
  .context-title-row h2 { font-size: 18px; margin: 0; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .context-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; font-size: 12px; color: var(--host-muted, var(--fallback-muted)); }
  .meta-item::before { content: ''; }
  .action-btn {
    background: var(--host-accent, var(--fallback-accent)); color: var(--host-accent-fg, #fff); border: none; padding: 4px 10px;
    border-radius: 4px; cursor: pointer; font-size: 12px; font-family: inherit; white-space: nowrap;
  }
  .action-btn:hover { opacity: 0.85; }
  .context-section { margin-bottom: 8px; border: 1px solid var(--host-border, var(--fallback-border)); border-radius: 6px; overflow: hidden; }
  .section-header {
    display: flex; align-items: center; justify-content: space-between; padding: 8px 12px;
    background: var(--host-surface, var(--fallback-surface)); cursor: pointer; font-size: 13px; font-weight: 600;
    user-select: none;
  }
  .section-header .badge { background: var(--host-accent, var(--fallback-accent)); color: var(--host-accent-fg, #fff); padding: 1px 6px; border-radius: 10px; font-size: 11px; font-weight: 500; }
  .section-body { padding: 8px 12px; font-size: 13px; display: none; }
  .context-section:not(.collapsed-section) .section-body { display: block; }
  .section-header::after { content: '\\25B6'; font-size: 10px; transition: transform 0.15s; }
  .context-section:not(.collapsed-section) .section-header::after { transform: rotate(90deg); }
  /* Tag pills */
  .tag-group { margin-bottom: 6px; }
  .tag-group-label { font-size: 11px; color: var(--host-muted, var(--fallback-muted)); text-transform: uppercase; margin-bottom: 2px; }
  .tag-pill {
    display: inline-block; padding: 2px 8px; margin: 2px 4px 2px 0; border-radius: 12px; font-size: 12px;
    background: var(--host-surface, var(--fallback-surface)); border: 1px solid var(--host-border, var(--fallback-border));
  }
  /* Link lists */
  .link-item {
    display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer;
    border-bottom: 1px solid var(--host-border, var(--fallback-border));
  }
  .link-item:last-child { border-bottom: none; }
  .link-item:hover { background: var(--host-surface, var(--fallback-surface)); }
  .link-path { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--host-accent, var(--fallback-accent)); }
  .link-type-badge {
    font-size: 10px; padding: 1px 5px; border-radius: 3px;
    background: var(--host-surface, var(--fallback-surface)); border: 1px solid var(--host-border, var(--fallback-border));
    color: var(--host-muted, var(--fallback-muted));
  }
  .link-exists-yes { color: var(--host-success, #22c55e); }
  .link-exists-no { color: var(--host-error, #ef4444); }
  .link-text { font-size: 11px; color: var(--host-muted, var(--fallback-muted)); }
  /* Similar notes */
  .similar-score {
    width: 60px; height: 6px; background: var(--host-border, var(--fallback-border)); border-radius: 3px; overflow: hidden; flex-shrink: 0;
  }
  .similar-score-fill { height: 100%; background: var(--host-accent, var(--fallback-accent)); border-radius: 3px; }
  /* Frontmatter table */
  .fm-table { width: 100%; border-collapse: collapse; }
  .fm-table td { padding: 3px 8px; border-bottom: 1px solid var(--host-border, var(--fallback-border)); font-size: 12px; vertical-align: top; }
  .fm-table td:first-child { font-weight: 600; white-space: nowrap; width: 1%; color: var(--host-muted, var(--fallback-muted)); }
  /* Graph styles */
  .graph-toolbar { display: flex; gap: 8px; padding: 4px 0; flex-shrink: 0; }
  #graph-container { border: 1px solid var(--host-border, var(--fallback-border)); border-radius: 6px; }
  .graph-mini-card {
    position: absolute; bottom: 16px; right: 16px; width: 280px; max-height: 200px; overflow-y: auto;
    background: var(--host-bg, var(--fallback-bg)); border: 1px solid var(--host-border, var(--fallback-border));
    border-radius: 8px; padding: 12px; font-size: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); z-index: 10;
  }
  .graph-mini-card h4 { margin: 0 0 6px; font-size: 14px; }
  .graph-mini-card .mini-links { margin: 4px 0; }
  .graph-mini-card .mini-link { color: var(--host-accent, var(--fallback-accent)); cursor: pointer; padding: 1px 0; }
  .graph-mini-card .mini-link:hover { text-decoration: underline; }
  .graph-mini-card .mini-actions { margin-top: 8px; display: flex; gap: 6px; }
  .graph-mini-card .mini-actions button {
    font-size: 11px; padding: 3px 8px; border-radius: 3px; cursor: pointer;
    background: var(--host-surface, var(--fallback-surface)); border: 1px solid var(--host-border, var(--fallback-border));
    color: var(--host-fg, var(--fallback-fg)); font-family: inherit;
  }
  .graph-mini-card .mini-actions button:hover { background: var(--host-border, var(--fallback-border)); }
  /* Browser styles */
  .browser-layout { display: flex; flex: 1; min-height: 0; gap: 0; }
  .browser-sidebar {
    width: 240px; min-width: 180px; flex-shrink: 0; display: flex; flex-direction: column;
    border-right: 1px solid var(--host-border, var(--fallback-border)); overflow: hidden;
  }
  .browser-search {
    display: flex; padding: 6px; gap: 4px; border-bottom: 1px solid var(--host-border, var(--fallback-border)); flex-shrink: 0;
  }
  .browser-search input {
    flex: 1; padding: 4px 8px; border: 1px solid var(--host-border, var(--fallback-border)); border-radius: 4px;
    font-size: 12px; font-family: inherit; background: var(--host-bg, var(--fallback-bg)); color: var(--host-fg, var(--fallback-fg));
  }
  .browser-search button {
    background: none; border: none; cursor: pointer; font-size: 16px; color: var(--host-muted, var(--fallback-muted)); padding: 0 4px;
  }
  .browser-tree { flex: 1; overflow-y: auto; padding: 4px; font-size: 12px; }
  .tree-folder {
    cursor: pointer; padding: 3px 4px; display: flex; align-items: center; gap: 4px;
    font-weight: 600; color: var(--host-fg, var(--fallback-fg));
  }
  .tree-folder:hover { background: var(--host-surface, var(--fallback-surface)); border-radius: 3px; }
  .tree-folder .arrow { font-size: 10px; width: 12px; transition: transform 0.15s; display: inline-block; }
  .tree-folder.expanded .arrow { transform: rotate(90deg); }
  .tree-children { padding-left: 16px; display: none; }
  .tree-folder.expanded + .tree-children { display: block; }
  .tree-note {
    cursor: pointer; padding: 3px 4px 3px 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    color: var(--host-fg, var(--fallback-fg));
  }
  .tree-note:hover { background: var(--host-surface, var(--fallback-surface)); border-radius: 3px; }
  .tree-note.active { background: var(--host-accent, var(--fallback-accent)); color: var(--host-accent-fg, #fff); border-radius: 3px; }
  .search-result {
    cursor: pointer; padding: 6px 8px; border-bottom: 1px solid var(--host-border, var(--fallback-border));
  }
  .search-result:hover { background: var(--host-surface, var(--fallback-surface)); }
  .search-result-title { font-weight: 600; font-size: 13px; }
  .search-result-snippet { font-size: 11px; color: var(--host-muted, var(--fallback-muted)); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  /* Preview pane */
  .browser-preview { flex: 1; overflow-y: auto; padding: 16px; min-width: 0; }
  .preview-header {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--host-border, var(--fallback-border));
  }
  .preview-header h1 { font-size: 18px; margin: 0; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .preview-actions { display: flex; gap: 6px; flex-shrink: 0; }
  .preview-fm { margin-bottom: 12px; }
  .preview-content { font-size: 14px; line-height: 1.6; }
  .preview-content h1, .preview-content h2, .preview-content h3 { margin-top: 16px; margin-bottom: 8px; }
  .preview-content p { margin: 8px 0; }
  .preview-content code { background: var(--host-surface, var(--fallback-surface)); padding: 1px 4px; border-radius: 3px; font-size: 13px; }
  .preview-content pre { background: var(--host-surface, var(--fallback-surface)); padding: 12px; border-radius: 6px; overflow-x: auto; }
  .preview-content pre code { background: none; padding: 0; }
  .preview-content blockquote { border-left: 3px solid var(--host-accent, var(--fallback-accent)); padding-left: 12px; color: var(--host-muted, var(--fallback-muted)); margin: 8px 0; }
  .preview-content a { color: var(--host-accent, var(--fallback-accent)); }
  .edit-btn-disabled {
    background: var(--host-surface, var(--fallback-surface)); color: var(--host-muted, var(--fallback-muted));
    border: 1px solid var(--host-border, var(--fallback-border)); padding: 4px 10px; border-radius: 4px;
    font-size: 12px; cursor: not-allowed; opacity: 0.6; font-family: inherit;
  }
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
    <div class="placeholder" id="context-placeholder">Select a note to view its context</div>
    <div id="context-card" style="display:none;">
      <div class="context-header">
        <div class="context-title-row">
          <h2 id="ctx-title"></h2>
          <div class="context-actions">
            <button class="action-btn" id="ctx-graph-btn" title="Show in Graph" style="background:var(--host-surface,var(--fallback-surface));color:var(--host-fg,var(--fallback-fg));border:1px solid var(--host-border,var(--fallback-border));">&#x1F517; Graph</button>
            <button class="action-btn" id="ctx-browse-btn" title="Open in Browser" style="background:var(--host-surface,var(--fallback-surface));color:var(--host-fg,var(--fallback-fg));border:1px solid var(--host-border,var(--fallback-border));">&#x1F4C4; Browse</button>
            <button class="action-btn" id="ctx-send-btn" title="Send to Claude">&#x1F4AC; Send</button>
          </div>
        </div>
        <div class="context-meta">
          <span id="ctx-path" class="meta-item"></span>
          <span id="ctx-folder" class="meta-item"></span>
          <span id="ctx-modified" class="meta-item"></span>
        </div>
      </div>
      <div id="ctx-frontmatter" class="context-section collapsed-section"></div>
      <div id="ctx-tags" class="context-section collapsed-section"></div>
      <div id="ctx-backlinks" class="context-section collapsed-section"></div>
      <div id="ctx-outlinks" class="context-section collapsed-section"></div>
      <div id="ctx-similar" class="context-section collapsed-section"></div>
      <div id="ctx-peers" class="context-section collapsed-section"></div>
    </div>
  </div>
  <div class="tab-panel" id="panel-graph" data-tab="graph">
    <div class="graph-toolbar" id="graph-toolbar">
      <button class="action-btn" id="graph-send-btn" title="Send graph summary to Claude">&#x1F4AC; Send</button>
      <button class="action-btn" id="graph-fullscreen-btn" title="Request fullscreen for graph" style="background:var(--host-surface,var(--fallback-surface));color:var(--host-fg,var(--fallback-fg));border:1px solid var(--host-border,var(--fallback-border));">&#x26F6; Expand</button>
    </div>
    <div id="graph-container" style="flex:1;min-height:300px;"></div>
    <div id="graph-mini-card" class="graph-mini-card" style="display:none;"></div>
  </div>
  <div class="tab-panel" id="panel-browse" data-tab="browse">
    <div class="browser-layout">
      <div class="browser-sidebar">
        <div class="browser-search">
          <input type="text" id="browser-search-input" placeholder="Search vault..." />
          <button id="browser-search-clear" style="display:none;" title="Clear search">&times;</button>
        </div>
        <div id="browser-tree" class="browser-tree"></div>
      </div>
      <div class="browser-preview" id="browser-preview">
        <div class="placeholder">Select a note to preview</div>
      </div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script type="module">
import { createApp } from 'https://unpkg.com/@anthropic-ai/claude-mcp-ext-apps@latest/dist/index.js';

// ── Globals ──────────────────────────────────────────────────────────────
const app = createApp();
let currentTab = 'context';
let isFullscreen = false;

// ── Utilities ─────────────────────────────────────────────────────────────
function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

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

// ── Context Card View ────────────────────────────────────────────────────
(function() {
  let currentContextPath = null;
  let currentContextData = null;

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function makeSection(id, title, count, bodyHtml) {
    const el = document.getElementById(id);
    if (!el) return;
    if (count === 0 && !bodyHtml) { el.style.display = 'none'; return; }
    el.style.display = '';
    el.innerHTML = '<div class="section-header"><span>' + escapeHtml(title) + '</span><span class="badge">' + count + '</span></div>'
      + '<div class="section-body">' + bodyHtml + '</div>';
    el.classList.add('collapsed-section');
    // toggle handled by delegated listener on #panel-context
  }

  function renderFrontmatter(fm) {
    if (!fm || Object.keys(fm).length === 0) return '';
    let rows = '';
    for (const [k, v] of Object.entries(fm)) {
      const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
      rows += '<tr><td>' + escapeHtml(k) + '</td><td>' + escapeHtml(val) + '</td></tr>';
    }
    return '<table class="fm-table">' + rows + '</table>';
  }

  function renderTags(tags) {
    if (!tags || Object.keys(tags).length === 0) return '';
    let html = '';
    for (const [field, values] of Object.entries(tags)) {
      html += '<div class="tag-group"><div class="tag-group-label">' + escapeHtml(field) + '</div>';
      for (const v of values) {
        html += '<span class="tag-pill">' + escapeHtml(v) + '</span>';
      }
      html += '</div>';
    }
    return html;
  }

  function renderBacklinks(backlinks) {
    if (!backlinks || backlinks.length === 0) return '';
    return backlinks.map(bl =>
      '<div class="link-item" data-path="' + escapeHtml(bl.source_path) + '">'
      + '<span class="link-path">' + escapeHtml(bl.source_path) + '</span>'
      + (bl.link_text ? '<span class="link-text">' + escapeHtml(bl.link_text) + '</span>' : '')
      + '<span class="link-type-badge">' + escapeHtml(bl.link_type) + '</span>'
      + '</div>'
    ).join('');
  }

  function renderOutlinks(outlinks) {
    if (!outlinks || outlinks.length === 0) return '';
    return outlinks.map(ol =>
      '<div class="link-item" data-path="' + escapeHtml(ol.target_path) + '">'
      + '<span class="link-path">' + escapeHtml(ol.target_path) + '</span>'
      + '<span class="' + (ol.exists ? 'link-exists-yes' : 'link-exists-no') + '">' + (ol.exists ? '\\u2713' : '\\u2717') + '</span>'
      + '<span class="link-type-badge">' + escapeHtml(ol.link_type) + '</span>'
      + '</div>'
    ).join('');
  }

  function renderSimilar(similar) {
    if (!similar || similar.length === 0) return '';
    const maxScore = Math.max(...similar.map(s => s.score), 0.001);
    return similar.map(s =>
      '<div class="link-item" data-path="' + escapeHtml(s.path) + '">'
      + '<span class="link-path">' + escapeHtml(s.title || s.path) + '</span>'
      + '<div class="similar-score"><div class="similar-score-fill" style="width:' + Math.round((s.score / maxScore) * 100) + '%"></div></div>'
      + '</div>'
    ).join('');
  }

  function renderPeers(peers) {
    if (!peers || peers.length === 0) return '';
    return peers.map(p =>
      '<div class="link-item" data-path="' + escapeHtml(p) + '">'
      + '<span class="link-path">' + escapeHtml(p) + '</span>'
      + '</div>'
    ).join('');
  }

  async function loadContext(path) {
    const placeholder = document.getElementById('context-placeholder');
    const card = document.getElementById('context-card');
    if (!path) { placeholder.style.display = ''; card.style.display = 'none'; return; }
    placeholder.style.display = 'none';
    card.style.display = '';

    try {
      const result = await app.callServerTool({ name: '_vault_context', arguments: { path } });
      const data = typeof result === 'string' ? JSON.parse(result) : result;
      currentContextPath = path;
      currentContextData = data;

      document.getElementById('ctx-title').textContent = data.title || path;
      document.getElementById('ctx-path').textContent = data.path;
      document.getElementById('ctx-folder').textContent = data.folder ? '\\uD83D\\uDCC1 ' + data.folder : '';
      document.getElementById('ctx-modified').textContent = '';
      if (data.modified_at) {
        const d = new Date(data.modified_at * 1000);
        document.getElementById('ctx-modified').textContent = d.toLocaleString();
      }

      const fmCount = data.frontmatter ? Object.keys(data.frontmatter).length : 0;
      makeSection('ctx-frontmatter', 'Frontmatter', fmCount, renderFrontmatter(data.frontmatter));
      const tagCount = data.tags ? Object.values(data.tags).reduce((a, v) => a + v.length, 0) : 0;
      makeSection('ctx-tags', 'Tags', tagCount, renderTags(data.tags));
      makeSection('ctx-backlinks', 'Backlinks', (data.backlinks || []).length, renderBacklinks(data.backlinks));
      makeSection('ctx-outlinks', 'Outlinks', (data.outlinks || []).length, renderOutlinks(data.outlinks));
      makeSection('ctx-similar', 'Similar', (data.similar || []).length, renderSimilar(data.similar));
      makeSection('ctx-peers', 'Folder Peers', (data.folder_notes || []).length, renderPeers(data.folder_notes));

      // Auto-expand sections with content
      for (const id of ['ctx-backlinks', 'ctx-outlinks']) {
        const el = document.getElementById(id);
        if (el && el.style.display !== 'none') el.classList.remove('collapsed-section');
      }

      window.updateContext('context card', path, data.title,
        'Backlinks: ' + (data.backlinks || []).length + ', Outlinks: ' + (data.outlinks || []).length);
    } catch (err) {
      placeholder.style.display = '';
      placeholder.textContent = 'Error loading context: ' + (err.message || String(err));
      card.style.display = 'none';
    }
  }

  // Delegated handler: link-item navigation + section-header toggle
  document.getElementById('panel-context').addEventListener('click', (e) => {
    const header = e.target.closest('.section-header');
    if (header) { header.closest('.context-section')?.classList.toggle('collapsed-section'); return; }
    const item = e.target.closest('.link-item[data-path]');
    if (item) loadContext(item.dataset.path);
  });

  // Show in Graph
  document.getElementById('ctx-graph-btn').addEventListener('click', () => {
    if (currentContextPath) window.navigateTo('graph', { path: currentContextPath });
  });

  // Open in Browser
  document.getElementById('ctx-browse-btn').addEventListener('click', () => {
    if (currentContextPath) window.navigateTo('browse', { path: currentContextPath });
  });

  // Send to Claude
  document.getElementById('ctx-send-btn').addEventListener('click', () => {
    if (!currentContextData) return;
    const d = currentContextData;
    const lines = [
      'Context for: ' + d.title + ' (' + d.path + ')',
      'Backlinks: ' + (d.backlinks || []).length,
      'Outlinks: ' + (d.outlinks || []).length,
      'Similar: ' + (d.similar || []).length,
    ];
    if (d.backlinks && d.backlinks.length > 0) {
      lines.push('Top backlinks: ' + d.backlinks.slice(0, 5).map(b => b.source_path).join(', '));
    }
    if (d.similar && d.similar.length > 0) {
      lines.push('Top similar: ' + d.similar.slice(0, 3).map(s => s.title || s.path).join(', '));
    }
    window.sendToLLM(d.path, lines.join('\\n'));
  });

  // Listen for navigation events
  window.addEventListener('vault-navigate', (e) => {
    if (e.detail.view === 'context' && e.detail.path) {
      loadContext(e.detail.path);
    }
  });

  // Expose for cross-view use
  window.loadContext = loadContext;
})();

// ── Graph Explorer View ──────────────────────────────────────────────────
(function() {
  let network = null;
  let nodesDS = null;
  let edgesDS = null;
  let graphCenterPath = null;
  let selectedNodeId = null;

  // Color scheme derived from CSS variables at init time
  function getColors() {
    const s = getComputedStyle(document.documentElement);
    return {
      bg: s.getPropertyValue('--host-bg').trim() || '#ffffff',
      fg: s.getPropertyValue('--host-fg').trim() || '#1a1a1a',
      accent: s.getPropertyValue('--host-accent').trim() || '#6366f1',
      muted: s.getPropertyValue('--host-muted').trim() || '#6b7280',
      border: s.getPropertyValue('--host-border').trim() || '#e0e0e0',
      surface: s.getPropertyValue('--host-surface').trim() || '#f5f5f5',
    };
  }

  function edgeColorByType(type, c) {
    if (type === 'wikilink') return c.accent;
    if (type === 'reference') return c.muted;
    return c.border; // markdown = default
  }

  function initNetwork() {
    if (network) return;
    const container = document.getElementById('graph-container');
    if (!container || typeof vis === 'undefined') return;
    const c = getColors();
    nodesDS = new vis.DataSet();
    edgesDS = new vis.DataSet();
    const options = {
      physics: { enabled: true, solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -40 } },
      nodes: {
        shape: 'dot', font: { size: 12, color: c.fg }, color: { background: c.accent, border: c.border, highlight: { background: c.accent, border: c.fg } },
        scaling: { min: 8, max: 30, label: { enabled: true, min: 10, max: 16 } },
      },
      edges: {
        arrows: { to: { enabled: true, scaleFactor: 0.5 } }, font: { size: 9 }, smooth: { type: 'continuous' },
      },
      interaction: { hover: true, tooltipDelay: 200 },
    };
    network = new vis.Network(container, { nodes: nodesDS, edges: edgesDS }, options);

    // Click: expand neighbors
    network.on('click', async (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        selectedNodeId = nodeId;
        await expandNode(nodeId);
        showMiniCard(nodeId);
      } else {
        hideMiniCard();
        selectedNodeId = null;
      }
    });

    // Hover: tooltip is built-in via node.title
    // Double-click: emit event for cross-navigation (#277)
    network.on('doubleClick', (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        window.dispatchEvent(new CustomEvent('vault-graph-dblclick', { detail: { path: nodeId } }));
      }
    });
  }

  function addGraphData(data) {
    if (!nodesDS || !edgesDS) return;
    const c = getColors();
    for (const n of data.nodes) {
      if (!nodesDS.get(n.id)) {
        const bc = n.backlink_count || 0;
        nodesDS.add({
          id: n.id, label: n.label,
          value: Math.max(bc, 1),
          title: n.label + (n.folder ? ' (' + n.folder + ')' : '') + (bc > 0 ? ' \u2014 ' + bc + ' backlinks' : ''),
          color: n.group === 'hub'
            ? { background: c.accent, border: c.fg }
            : { background: c.surface, border: c.border },
          font: { color: c.fg },
          borderWidth: n.group === 'orphan' ? 1 : 2,
          borderWidthSelected: 3,
          shapeProperties: n.group === 'orphan' ? { borderDashes: [5, 5] } : {},
        });
      }
    }
    for (const e of data.edges) {
      const edgeId = e.from + '->' + e.to;
      if (!edgesDS.get(edgeId)) {
        edgesDS.add({
          id: edgeId, from: e.from, to: e.to,
          color: { color: edgeColorByType(e.type, c), highlight: c.accent },
          title: e.type,
        });
      }
    }
  }

  async function expandNode(path) {
    try {
      const result = await app.callServerTool({
        name: '_vault_graph_neighborhood', arguments: { path, depth: 1 }
      });
      const data = typeof result === 'string' ? JSON.parse(result) : result;
      addGraphData(data);
      window.updateContext('graph explorer', path, nodesDS.get(path)?.label,
        'Visible: ' + nodesDS.length + ' notes, ' + edgesDS.length + ' links');
    } catch (err) {
      console.warn('Graph expand failed:', err);
    }
  }

  async function loadHubs() {
    try {
      const result = await app.callServerTool({ name: '_vault_graph_hubs', arguments: {} });
      const data = typeof result === 'string' ? JSON.parse(result) : result;
      addGraphData(data);
      if (data.nodes.length > 0) {
        window.updateContext('graph explorer', '(hub view)', null,
          'Showing ' + data.nodes.length + ' most-linked notes');
      }
    } catch (err) {
      console.warn('Graph hubs failed:', err);
    }
  }

  async function loadGraph(path) {
    initNetwork();
    if (!nodesDS || !edgesDS) return;  // vis CDN failed to load
    nodesDS.clear();
    edgesDS.clear();
    graphCenterPath = path || null;
    if (path) {
      await expandNode(path);
      network.fit({ animation: true });
    } else {
      await loadHubs();
      network.fit({ animation: true });
    }
  }

  // Mini context card on single click
  function showMiniCard(nodeId) {
    const card = document.getElementById('graph-mini-card');
    app.callServerTool({ name: '_vault_context', arguments: { path: nodeId } }).then(result => {
      const data = typeof result === 'string' ? JSON.parse(result) : result;
      const bl = (data.backlinks || []).slice(0, 3);
      const ol = (data.outlinks || []).slice(0, 3);
      let html = '<h4>' + escHtml(data.title || nodeId) + '</h4>';
      if (data.tags && Object.keys(data.tags).length > 0) {
        const allTags = Object.values(data.tags).flat().slice(0, 5);
        html += '<div>' + allTags.map(t => '<span class="tag-pill" style="font-size:10px">' + escHtml(t) + '</span>').join(' ') + '</div>';
      }
      if (bl.length > 0) {
        html += '<div class="mini-links"><strong>Backlinks:</strong>';
        for (const b of bl) html += '<div class="mini-link" data-path="' + escHtml(b.source_path) + '">' + escHtml(b.source_path) + '</div>';
        html += '</div>';
      }
      if (ol.length > 0) {
        html += '<div class="mini-links"><strong>Outlinks:</strong>';
        for (const o of ol) html += '<div class="mini-link" data-path="' + escHtml(o.target_path) + '">' + escHtml(o.target_path) + '</div>';
        html += '</div>';
      }
      html += '<div class="mini-actions">'
        + '<button id="mini-full-ctx">Full Context</button>'
        + '<button id="mini-open-browser">Open in Browser</button>'
        + '</div>';
      card.innerHTML = html;
      card.style.display = '';

      card.querySelector('#mini-full-ctx')?.addEventListener('click', () => {
        window.navigateTo('context', { path: nodeId });
        hideMiniCard();
      });
      card.querySelector('#mini-open-browser')?.addEventListener('click', () => {
        window.navigateTo('browse', { path: nodeId });
        hideMiniCard();
      });
      card.querySelectorAll('.mini-link').forEach(el => {
        el.addEventListener('click', () => expandNode(el.dataset.path));
      });
    }).catch(() => { card.style.display = 'none'; });
  }

  function hideMiniCard() {
    document.getElementById('graph-mini-card').style.display = 'none';
  }

  // Send graph summary to Claude
  document.getElementById('graph-send-btn').addEventListener('click', () => {
    if (!nodesDS || nodesDS.length === 0) return;
    const center = graphCenterPath || 'hub view';
    const nodeLabels = nodesDS.get().map(n => n.label).slice(0, 20).join(', ');
    const summary = 'Graph around ' + center + ': ' + nodesDS.length + ' notes, '
      + edgesDS.length + ' links\\nNotes: ' + nodeLabels;
    window.sendToLLM(center, summary);
  });

  // Fullscreen for graph
  document.getElementById('graph-fullscreen-btn').addEventListener('click', async () => {
    try { await app.setDisplayMode('fullscreen'); } catch (e) { console.warn(e); }
  });

  // Listen for navigation events
  window.addEventListener('vault-navigate', (e) => {
    if (e.detail.view === 'graph') {
      loadGraph(e.detail.path || null);
    }
  });

  // Auto-load when graph tab is selected
  window.addEventListener('vault-tab-changed', (e) => {
    if (e.detail.tab === 'graph' && (!nodesDS || nodesDS.length === 0)) {
      loadGraph(graphCenterPath);
    }
  });

  window.loadGraph = loadGraph;
})();

// ── Cross-view navigation wiring (#277) ──────────────────────────────────
// Graph double-click → Context Card
window.addEventListener('vault-graph-dblclick', (e) => {
  if (e.detail.path) window.navigateTo('context', { path: e.detail.path });
});

// ── Vault Browser View ──────────────────────────────────────────────────
(function() {
  function escHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  let currentPreviewPath = null;
  let currentPreviewData = null;
  let treeDataCache = {};
  let isSearchMode = false;

  const treeEl = document.getElementById('browser-tree');
  const previewEl = document.getElementById('browser-preview');
  const searchInput = document.getElementById('browser-search-input');
  const searchClear = document.getElementById('browser-search-clear');

  async function loadFolder(folder) {
    const key = folder || '__root__';
    if (treeDataCache[key]) return treeDataCache[key];
    try {
      const result = await app.callServerTool({ name: '_vault_list', arguments: { folder: folder || null } });
      const data = typeof result === 'string' ? JSON.parse(result) : result;
      treeDataCache[key] = data;
      return data;
    } catch (err) {
      console.warn('Failed to load folder:', err);
      return { folders: [], notes: [] };
    }
  }

  function renderTree(data, parentEl) {
    parentEl.innerHTML = '';
    // Folders
    for (const f of data.folders) {
      const name = f.includes('/') ? f.split('/').pop() : f;
      const folderDiv = document.createElement('div');
      folderDiv.className = 'tree-folder';
      folderDiv.innerHTML = '<span class="arrow">\\u25B6</span> \\uD83D\\uDCC1 ' + escHtml(name);
      folderDiv.dataset.folder = f;
      parentEl.appendChild(folderDiv);

      const childrenDiv = document.createElement('div');
      childrenDiv.className = 'tree-children';
      parentEl.appendChild(childrenDiv);

      folderDiv.addEventListener('click', async () => {
        const isExpanded = folderDiv.classList.contains('expanded');
        if (isExpanded) {
          folderDiv.classList.remove('expanded');
        } else {
          folderDiv.classList.add('expanded');
          if (childrenDiv.children.length === 0) {
            const subData = await loadFolder(f);
            renderTree(subData, childrenDiv);
          }
        }
      });
    }
    // Notes
    for (const n of data.notes) {
      const noteDiv = document.createElement('div');
      noteDiv.className = 'tree-note';
      noteDiv.textContent = n.title || n.path;
      noteDiv.title = n.path;
      noteDiv.dataset.path = n.path;
      noteDiv.addEventListener('click', () => loadPreview(n.path));
      parentEl.appendChild(noteDiv);
    }
  }

  async function loadRootTree() {
    treeDataCache = {};
    const data = await loadFolder(null);
    renderTree(data, treeEl);
  }

  async function loadPreview(path) {
    currentPreviewPath = path;
    // Highlight active note in tree
    treeEl.querySelectorAll('.tree-note').forEach(el => {
      el.classList.toggle('active', el.dataset.path === path);
    });

    try {
      const result = await app.callServerTool({ name: '_vault_read', arguments: { path } });
      const data = typeof result === 'string' ? JSON.parse(result) : result;
      if (!data) { previewEl.innerHTML = '<div class="placeholder">Note not found</div>'; return; }
      currentPreviewData = data;

      let html = '<div class="preview-header">';
      html += '<h2>' + escHtml(data.title || path) + '</h2>';
      html += '<div class="preview-actions">';
      html += '<button class="action-btn" id="preview-send-btn" title="Send to Claude">\\uD83D\\uDCAC Send</button>';
      html += '<button class="action-btn" id="preview-ctx-btn" title="Show Context" style="background:var(--host-surface,var(--fallback-surface));color:var(--host-fg,var(--fallback-fg));border:1px solid var(--host-border,var(--fallback-border));">\\uD83D\\uDD0D Context</button>';
      html += '<button class="action-btn" id="preview-graph-btn" title="Show in Graph" style="background:var(--host-surface,var(--fallback-surface));color:var(--host-fg,var(--fallback-fg));border:1px solid var(--host-border,var(--fallback-border));">\\uD83D\\uDD17 Graph</button>';
      html += '<button class="edit-btn-disabled" title="Coming soon" disabled>\\u270F Edit</button>';
      html += '</div></div>';

      // Frontmatter
      if (data.frontmatter && Object.keys(data.frontmatter).length > 0) {
        html += '<div class="preview-fm"><table class="fm-table">';
        for (const [k, v] of Object.entries(data.frontmatter)) {
          const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
          html += '<tr><td>' + escHtml(k) + '</td><td>' + escHtml(val) + '</td></tr>';
        }
        html += '</table></div>';
      }

      // Rendered markdown
      let rendered = '';
      if (typeof marked !== 'undefined' && data.content) {
        rendered = marked.parse(data.content);
      } else {
        rendered = '<pre>' + escHtml(data.content || '') + '</pre>';
      }
      if (typeof DOMPurify !== 'undefined') {
        rendered = DOMPurify.sanitize(rendered);
      }
      html += '<div class="preview-content">' + rendered + '</div>';

      previewEl.innerHTML = html;

      // Wire action buttons
      document.getElementById('preview-send-btn')?.addEventListener('click', () => {
        window.sendToLLM(data.path, data.content || '');
      });
      document.getElementById('preview-ctx-btn')?.addEventListener('click', () => {
        window.navigateTo('context', { path: data.path });
      });
      document.getElementById('preview-graph-btn')?.addEventListener('click', () => {
        window.navigateTo('graph', { path: data.path });
      });

      window.updateContext('browser', path, data.title);
    } catch (err) {
      const errDiv = document.createElement('div');
      errDiv.className = 'placeholder';
      errDiv.textContent = 'Error: ' + (err.message || err);
      previewEl.innerHTML = '';
      previewEl.appendChild(errDiv);
    }
  }

  // Search
  let searchTimeout = null;
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    const q = searchInput.value.trim();
    if (!q) { exitSearch(); return; }
    searchTimeout = setTimeout(() => doSearch(q), 300);
  });

  async function doSearch(query) {
    isSearchMode = true;
    searchClear.style.display = '';
    try {
      const result = await app.callServerTool({
        name: '_vault_search', arguments: { query, mode: 'keyword', limit: 20 }
      });
      const data = typeof result === 'string' ? JSON.parse(result) : result;
      treeEl.innerHTML = '';
      for (const r of data) {
        const div = document.createElement('div');
        div.className = 'search-result';
        div.innerHTML = '<div class="search-result-title">' + escHtml(r.title || r.path) + '</div>'
          + '<div class="search-result-snippet">' + escHtml(r.snippet || '') + '</div>';
        div.addEventListener('click', () => loadPreview(r.path));
        treeEl.appendChild(div);
      }
      if (data.length === 0) {
        treeEl.innerHTML = '<div class="placeholder" style="padding:12px">No results</div>';
      }
    } catch (err) {
      treeEl.innerHTML = '<div class="placeholder" style="padding:12px">Search error</div>';
    }
  }

  function exitSearch() {
    isSearchMode = false;
    searchClear.style.display = 'none';
    searchInput.value = '';
    loadRootTree();
  }

  searchClear.addEventListener('click', exitSearch);

  // Listen for navigation events
  window.addEventListener('vault-navigate', (e) => {
    if (e.detail.view === 'browse' && e.detail.path) {
      loadPreview(e.detail.path);
    }
  });

  // Auto-load when browse tab is selected
  window.addEventListener('vault-tab-changed', (e) => {
    if (e.detail.tab === 'browse' && treeEl.children.length === 0 && !isSearchMode) {
      loadRootTree();
    }
  });

  window.loadBrowser = loadRootTree;
  window.loadPreview = loadPreview;
})();

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
        try:
            ctx = await asyncio.to_thread(collection.get_context, path)
        except ValueError:
            return {"error": f"Note not found: {path}"}
        return asdict(ctx)

    @mcp.tool(
        icons=_TOOL_ICONS["show_context"],
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
        try:
            ctx = await asyncio.to_thread(collection.get_context, path)
        except ValueError:
            return {
                "path": path,
                "view": "context",
                "summary": f"Note not found: {path}",
            }
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
            ``{nodes: [{id, label, group, folder, backlink_count}], edges: [{from, to, type}]}``
        """
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        visited: set[str] = set()
        queue: collections.deque[tuple[str, int]] = collections.deque([(path, 0)])

        while queue:
            current, d = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            # Add node
            note = await asyncio.to_thread(collection.read, current)
            label = (
                note.title if note else current.rsplit("/", 1)[-1].replace(".md", "")
            )
            folder = note.folder if note else ""

            if d >= depth:
                # Boundary nodes are reachable by definition — skip DB calls
                nodes[current] = {
                    "id": current,
                    "label": label,
                    "group": "note",
                    "folder": folder,
                    "backlink_count": 0,
                }
                continue

            # Fetch backlinks/outlinks for interior nodes (orphan detection + edges)
            try:
                backlinks = await asyncio.to_thread(collection.get_backlinks, current)
            except ValueError:
                backlinks = []
            try:
                outlinks = await asyncio.to_thread(collection.get_outlinks, current)
            except ValueError:
                outlinks = []
            is_orphan = len(backlinks) == 0 and len(outlinks) == 0

            nodes[current] = {
                "id": current,
                "label": label,
                "group": "orphan" if is_orphan else "note",
                "folder": folder,
                "backlink_count": len(backlinks),
            }

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

            # Process outlinks (already fetched above for orphan detection)
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
        seen_edges: set[tuple[str, str]] = set()

        for hub in hubs:
            # TODO: extend get_most_linked to return folder, eliminating this per-hub read
            hub_note = await asyncio.to_thread(collection.read, hub.path)
            hub_folder = hub_note.folder if hub_note else ""
            nodes[hub.path] = {
                "id": hub.path,
                "label": hub.title,
                "group": "hub",
                "backlink_count": hub.backlink_count,
                "folder": hub_folder,
            }

            # Get immediate connections for each hub
            try:
                backlinks = await asyncio.to_thread(collection.get_backlinks, hub.path)
            except ValueError:
                backlinks = []
            for bl in backlinks:
                if bl.source_path not in nodes:
                    note = await asyncio.to_thread(collection.read, bl.source_path)
                    label = (
                        note.title
                        if note
                        else bl.source_path.rsplit("/", 1)[-1].replace(".md", "")
                    )
                    folder = note.folder if note else ""
                    nodes[bl.source_path] = {
                        "id": bl.source_path,
                        "label": label,
                        "group": "note",
                        "folder": folder,
                        "backlink_count": 0,
                    }
                edge_key = (bl.source_path, hub.path)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
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
        try:
            results = await asyncio.to_thread(
                collection.search, query, limit=limit, mode=mode
            )
        except ValueError as exc:
            return [{"error": str(exc)}]
        return [
            {
                "path": r.path,
                "title": r.title,
                "snippet": r.content[:200] if r.content else "",
                "score": r.score,
            }
            for r in results
        ]
