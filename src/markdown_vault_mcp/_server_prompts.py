"""MCP prompt registrations for the markdown-vault-mcp server.

Call :func:`register_prompts` after constructing the
:class:`~fastmcp.FastMCP` instance in
:func:`~markdown_vault_mcp.mcp_server.create_server`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path, PurePosixPath
from typing import Any

import frontmatter
from fastmcp import FastMCP

from ._icons import _TOOL_ICONS

logger = logging.getLogger(__name__)


def _load_user_prompt_defs(prompts_folder: str | None) -> dict[str, dict[str, Any]]:
    """Scan *prompts_folder* and return a dict of prompt definitions.

    Args:
        prompts_folder: Relative or absolute path to a directory of ``.md``
            prompt files, or ``None``.

    Returns:
        A mapping of prompt name (file stem) to a dict with keys
        ``description`` (str), ``arguments`` (list[dict]), ``tags``
        (list[str]), and ``content`` (str).  Returns an empty dict when
        *prompts_folder* is ``None`` or the directory does not exist.
    """
    if prompts_folder is None:
        return {}

    folder = Path(prompts_folder)
    if not folder.exists() or not folder.is_dir():
        logger.warning(
            "PROMPTS_FOLDER=%r does not exist or is not a directory — "
            "user-defined prompts will not be loaded",
            str(folder),
        )
        return {}

    defs: dict[str, dict[str, Any]] = {}
    for md_file in sorted(folder.glob("*.md")):
        name = md_file.stem
        try:
            post = frontmatter.loads(md_file.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(
                "Failed to parse user prompt file %r — skipping",
                str(md_file),
                exc_info=True,
            )
            continue

        description: str = post.get("description", "") or ""
        raw_arguments = post.get("arguments") or []
        if not isinstance(raw_arguments, list):
            raw_arguments = []
        arguments: list[dict[str, Any]] = []
        for arg in raw_arguments:
            if isinstance(arg, dict) and "name" in arg:
                arguments.append(
                    {
                        "name": str(arg["name"]),
                        "description": str(arg.get("description", "")),
                        "required": bool(arg.get("required", False)),
                    }
                )

        raw_tags = post.get("tags") or []
        tags: list[str] = (
            [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
        )

        defs[name] = {
            "description": description,
            "arguments": arguments,
            "tags": tags,
            "content": post.content,
        }
        logger.debug("Loaded user prompt definition: %s (from %s)", name, md_file.name)

    return defs


def _register_one_user_prompt(mcp: FastMCP, name: str, defn: dict[str, Any]) -> None:
    """Register a single user-defined prompt on *mcp*.

    Builds a function with the correct signature via :func:`exec` so that
    FastMCP can introspect the arguments.

    Args:
        mcp: The :class:`~fastmcp.FastMCP` instance.
        name: Prompt name (file stem).
        defn: Prompt definition dict with keys ``description``,
            ``arguments``, ``tags``, and ``content``.
    """
    description: str = defn.get("description", "")
    arg_defs: list[dict[str, Any]] = defn.get("arguments", [])
    tags: set[str] = set(defn.get("tags", []))
    content_template: str = defn["content"]

    if not arg_defs:
        # No arguments — simple no-arg function.
        def _make_no_arg(tmpl: str) -> Any:
            def prompt_fn() -> str:
                return tmpl

            return prompt_fn

        fn = _make_no_arg(content_template)
    else:
        # Build a function with the correct typed signature via exec so
        # FastMCP can introspect argument names and required status.
        param_parts: list[str] = []
        for arg in arg_defs:
            if arg.get("required", False):
                param_parts.append(f"{arg['name']}: str")
            else:
                param_parts.append(f'{arg["name"]}: str = ""')
        params_str = ", ".join(param_parts)
        format_args = ", ".join(f"{a['name']}={a['name']}" for a in arg_defs)
        fn_src = (
            f"def prompt_fn({params_str}) -> str:\n"
            f"    return tmpl.format({format_args})\n"
        )
        local_ns: dict[str, Any] = {"tmpl": content_template}
        exec(fn_src, local_ns)
        fn = local_ns["prompt_fn"]

    fn.__name__ = name
    fn.__doc__ = description or f"User-defined prompt: {name}"

    decorator_kwargs: dict[str, Any] = {}
    if tags:
        decorator_kwargs["tags"] = tags

    mcp.prompt(**decorator_kwargs)(fn)
    logger.debug("Registered user-defined prompt: %s", name)


def register_prompts(
    mcp: FastMCP,
    templates_folder: str | None,
    prompts_folder: str | None = None,
) -> None:
    """Register all built-in MCP prompts on *mcp*, with user-defined overrides.

    User-defined prompts from *prompts_folder* take priority.  Any built-in
    whose name matches a user-defined prompt is skipped.  User-defined prompts
    are registered after the built-ins.

    Args:
        mcp: The :class:`~fastmcp.FastMCP` instance to register prompts on.
        templates_folder: The configured templates folder path, or ``None``
            when templates are not configured.  Passed in from
            :func:`~markdown_vault_mcp.mcp_server.create_server` so that
            ``create_from_template`` can close over this value without
            re-reading environment variables.
        prompts_folder: Path to a directory of user-defined ``.md`` prompt
            files.  ``None`` disables user-defined prompt loading.
    """
    # --- Pass 1: collect user-defined prompt names (for override semantics) ---
    user_prompt_defs = _load_user_prompt_defs(prompts_folder)
    if user_prompt_defs:
        logger.info(
            "User-defined prompts found in %r: %s",
            prompts_folder,
            sorted(user_prompt_defs),
        )

    # --- Pass 2: register built-ins, skipping any overridden by user prompts ---

    if "summarize" not in user_prompt_defs:

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

    if "research" not in user_prompt_defs:

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

    if "discuss" not in user_prompt_defs:

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

    if "create_from_template" not in user_prompt_defs:

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
                if template_name_clean and templates_folder is not None
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

    if "related" not in user_prompt_defs:

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

    if "compare" not in user_prompt_defs:

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

    # --- Pass 3: register user-defined prompts ---
    for name, defn in user_prompt_defs.items():
        _register_one_user_prompt(mcp, name, defn)
