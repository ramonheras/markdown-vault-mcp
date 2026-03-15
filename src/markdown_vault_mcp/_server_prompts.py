"""MCP prompt registrations for the markdown-vault-mcp server.

Call :func:`register_prompts` after constructing the
:class:`~fastmcp.FastMCP` instance in
:func:`~markdown_vault_mcp.mcp_server.create_server`.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from fastmcp import FastMCP

from ._icons import _TOOL_ICONS


def register_prompts(mcp: FastMCP, templates_folder: str | None) -> None:
    """Register all 6 MCP prompts on *mcp*.

    Args:
        mcp: The :class:`~fastmcp.FastMCP` instance to register prompts on.
        templates_folder: The configured templates folder path, or ``None``
            when templates are not configured.  Passed in from
            :func:`~markdown_vault_mcp.mcp_server.create_server` so that
            ``create_from_template`` can close over this value without
            re-reading environment variables.
    """

    @mcp.prompt(icons=_TOOL_ICONS["read"])
    def summarize(path: str) -> str:
        """Summarize a document."""
        return (
            f"Call the `read` tool with path='{path}'. "
            "The result contains a `content` field (the markdown body) and a "
            "`frontmatter` field (metadata). "
            "Write a concise summary covering the document's main topics and "
            "key points. "
            "If `read` returns an error, report it and stop."
        )

    @mcp.prompt(tags={"write"}, icons=_TOOL_ICONS["write"])
    def research(topic: str) -> str:
        """Research a topic and consolidate findings as a new note."""
        slug = re.sub(r"[^\w\-]", "-", topic.lower()).strip("-")
        return (
            f"You are building a research note about: {topic!r}\n\n"
            "1. Call `search` with that query and mode='hybrid'. If the call "
            "fails (semantic search not configured), retry with mode='keyword'. "
            "Examine the top results; call `read` on the 3-5 highest-scoring paths.\n"
            "2. Write a structured markdown summary of what you found. Link "
            "each source as [document title](its/relative/path.md).\n"
            f"3. Choose a path like Research/{slug}.md. "
            "Call `write` with that path, your content, and "
            "frontmatter={'title': ..., 'tags': ['research']}.\n"
            "If no results are found, tell the user and stop — do not write "
            "an empty note."
        )

    @mcp.prompt(tags={"write"}, icons=_TOOL_ICONS["edit"])
    def discuss(path: str) -> str:
        """Analyze a document and suggest improvements."""
        return (
            f"Step 1: Call `read` with path='{path}'. Review the document.\n"
            "Step 2: Identify specific improvements: factual corrections, "
            "clarity, structure, completeness.\n"
            "Step 3: Present your proposed changes to the user before editing. "
            "Then apply each change using `edit`. "
            "`edit` requires an exact `old_text` substring from the document "
            "returned in Step 1 — do not paraphrase. Each `edit` call changes "
            "one location; use multiple calls for multiple changes.\n"
            "Do not use `write` — it overwrites the entire file including "
            "frontmatter.\n"
            "If `read` fails, report the error and stop."
        )

    @mcp.prompt(tags={"write"}, icons=_TOOL_ICONS["write"])
    def create_from_template(template_name: str | None = None) -> str:
        """Create a new note by adapting a template from the templates folder."""
        template_hint = "None" if template_name is None else repr(template_name)
        template_name_clean = (
            (template_name or "").strip().replace("\\", "/").lstrip("/")
        )
        if template_name_clean:
            resolved: list[str] = []
            for part in PurePosixPath(template_name_clean).parts:
                if part in ("", "."):
                    continue
                elif part == "..":
                    if resolved:
                        resolved.pop()
                else:
                    resolved.append(part)
            template_name_clean = str(PurePosixPath(*resolved)) if resolved else ""
        template_path = (
            str(PurePosixPath(templates_folder) / template_name_clean)
            if template_name_clean
            else ""
        )
        return (
            "## Role\n"
            "You are a note assistant that creates new notes from vault templates.\n\n"
            "## Context\n"
            f"- Templates folder: `{templates_folder}`\n"
            f"- Requested template_name: {template_hint}\n"
            "- Templates are normal markdown files. Do not use server-side variable substitution.\n\n"
            "## Task\n"
            "Guide the user through this workflow: discover template -> read template -> gather values -> write the new note.\n\n"
            "## Format\n"
            "Follow these exact steps in order:\n"
            "1. If `template_name` is missing, call `list_documents(folder=<templates folder>)`, "
            "show available templates, and ask the user to pick one.\n"
            "2. Resolve template path and call `read(path=<template path>)`.\n"
            f"   If a name is already provided, start with `read(path='{template_path or '<templates_folder>/<template_name>'}')`.\n"
            "3. Present the template structure and ask the user for missing values.\n"
            "4. Propose a target note path. Prefer frontmatter convention if present; otherwise ask the user.\n"
            "5. Call `write(path=..., content=..., frontmatter=...)` with the filled note.\n\n"
            "## Constraints\n"
            "- Use only vault tools (`list_documents`, `read`, `write`) for this flow.\n"
            "- Never overwrite an existing file without explicit user confirmation.\n"
            "- If the selected template does not exist, return a clear error and ask for another template.\n"
            "- Keep paths relative to the vault root.\n"
            "- Repeat: discover -> read -> fill -> write.\n"
        )

    @mcp.prompt(icons=_TOOL_ICONS["search"])
    def related(path: str) -> str:
        """Find related notes and suggest cross-references."""
        return (
            f"Step 1: Call `read` with path='{path}'. Extract the main topics "
            "and key terms.\n"
            f"Step 2: Call `get_context` with path='{path}' — this returns "
            "backlinks, outlinks, and similar notes in one call. Also call "
            "`search` using the main topic terms to surface additional documents "
            "not captured by direct links or overall document similarity.\n"
            "Step 3: Present a list of the most relevant related documents. "
            "For each, include: the document title, its path, and one sentence "
            "explaining the connection.\n"
            "Format suggested cross-references as: [title](relative/path.md)\n"
            "Do not edit any documents — this prompt is read-only."
        )

    @mcp.prompt(icons=_TOOL_ICONS["read"])
    def compare(path1: str, path2: str) -> str:
        """Compare two documents."""
        return (
            f"Call `read` for both '{path1}' and '{path2}'. "
            "Use the `content` field from each result for comparison. "
            "Present your comparison covering:\n"
            "- What both documents agree on\n"
            "- Where they differ or contradict\n"
            "- Information present in one but absent from the other\n"
            "If either `read` call fails, report which path was not found "
            "and stop."
        )
