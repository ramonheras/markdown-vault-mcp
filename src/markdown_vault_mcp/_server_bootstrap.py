"""Dynamic RHOS-style bootstrap helpers for MCP instructions and skills.

This module keeps the "how should I start using this vault?" logic separate
from the core search/read/write tool registry.  It discovers:

- the operator-maintained system-instructions markdown file (prefer AGENTS.md)
- available skill markdown files under common skill directories
- a lightweight skill index suitable for list_skills / read_skill
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import frontmatter

from .scanner import _resolve_title
from .utils.text import read_text_utf8

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fastmcp.tools.base import Tool

_SYSTEM_INSTRUCTIONS_CANDIDATES = (
    "AGENTS.md",
    "Agent.md",
    "AGENT.md",
    "agent.md",
    "90_System/AGENTS.md",
    "90_System/Agent.md",
    "README.md",
    "90_System/INDEX.md",
)

_SKILLS_DIR_CANDIDATES = (
    "Skills",
    "skills",
    "90_System/skills",
    "90_System/Skills",
)

_SKILL_FILE_EXCLUDE_NAMES = frozenset({"INDEX.md"})
_SKILL_DIR_EXCLUDE_PARTS = frozenset({"_tmp", ".git", ".obsidian", "__pycache__"})


@dataclass(frozen=True)
class SkillSummary:
    """Normalized skill metadata exposed to MCP clients."""

    skill_id: str
    title: str
    path: str
    summary: str
    triggers: list[str] = field(default_factory=list)
    when_to_use: str | None = None


def build_bootstrap_guidance(*, read_only: bool) -> str:
    """Return the short stable root guidance injected at server init."""
    write_guard = (
        " Before modifying the vault, follow the operating instructions."
        if not read_only
        else " Before planning vault changes, follow the operating instructions."
    )
    return (
        "You are connected to a Markdown/Obsidian-style vault used to store notes, "
        "tasks, projects, decisions, and workflows."
        f"{write_guard} "
        "The operating instructions are included below when the client loads "
        "server instructions correctly. In that case, do not call "
        "`get_system_instructions` just to reload them; call `list_skills` only "
        "when you need to refresh the available workflows. If the operating "
        "instructions are missing from context, call `get_system_instructions` "
        "before doing anything else. Before writing, classifying, or injecting "
        "content, inspect the relevant skill with `read_skill` when one applies. "
        "Prefer semantic vault tools over raw file writes."
    )


def load_operator_instructions_markdown(source_dir: Path) -> tuple[str | None, str]:
    """Load the operator-maintained instructions markdown for startup/bootstrap."""
    instructions_path = resolve_system_instructions_path(source_dir)
    if instructions_path is None:
        return (
            None,
            "# Operating Instructions\n\n"
            "No AGENTS-style instructions file was found in the vault root. "
            "Use the dynamic skill index and inspect the relevant skill before "
            "making structured vault changes.",
        )
    return (
        instructions_path.relative_to(source_dir.resolve()).as_posix(),
        read_text_utf8(instructions_path).strip(),
    )


def resolve_system_instructions_path(source_dir: Path) -> Path | None:
    """Return the best available instructions markdown file for the vault."""
    source_dir = source_dir.resolve()
    for rel in _SYSTEM_INSTRUCTIONS_CANDIDATES:
        candidate = source_dir / rel
        if candidate.is_file():
            return candidate
    return None


def resolve_skills_dirs(source_dir: Path) -> list[Path]:
    """Return the existing skill directories in priority order."""
    source_dir = source_dir.resolve()
    found: list[Path] = []
    for rel in _SKILLS_DIR_CANDIDATES:
        candidate = (source_dir / rel).resolve()
        if candidate.is_dir() and not any(candidate.samefile(existing) for existing in found):
            found.append(candidate)
    return found


def _slugify(value: str) -> str:
    """Convert arbitrary title/path-like text into a stable lowercase id."""
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "-", value)
    return value.strip("-").lower() or "skill"


def _normalize_list(value: Any) -> list[str]:
    """Normalize a frontmatter field into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items
    return []


def _first_meaningful_paragraph(content: str) -> str:
    """Extract the first non-heading prose paragraph from markdown text."""
    lines: list[str] = []
    in_code_fence = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("```") or line.startswith("~~~"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if not line:
            if lines:
                break
            continue
        if line.startswith("#") or line.startswith("---"):
            continue
        if line.startswith(("- ", "* ", "> ")):
            if lines:
                break
            continue
        lines.append(line)
    paragraph = " ".join(lines).strip()
    return paragraph or "No summary provided."


def _resolve_skill_id(metadata: dict[str, Any], path: Path) -> str:
    """Resolve a skill id from frontmatter, filename, or parent directory."""
    for key in ("skill_id", "skill", "id", "name"):
        raw = metadata.get(key)
        if isinstance(raw, str) and raw.strip():
            return _slugify(raw)

    if path.stem.lower() == "skill":
        return _slugify(path.parent.name)
    return _slugify(path.stem)


def _is_skill_markdown(md_file: Path, root: Path) -> bool:
    """Return True when *md_file* should be indexed as a skill."""
    if md_file.name in _SKILL_FILE_EXCLUDE_NAMES:
        return False
    rel_parts = md_file.relative_to(root).parts
    return not any(part in _SKILL_DIR_EXCLUDE_PARTS for part in rel_parts)


def _read_markdown_with_frontmatter(md_file: Path) -> tuple[dict[str, Any], str]:
    """Parse markdown frontmatter, falling back gracefully on parse failures."""
    text = read_text_utf8(md_file)
    try:
        post = frontmatter.loads(text)
    except Exception:
        return {}, text
    metadata = dict(post.metadata)
    return metadata, post.content


def _build_one_skill_summary(md_file: Path, source_dir: Path) -> SkillSummary:
    """Return normalized skill metadata for a single markdown file."""
    metadata, content = _read_markdown_with_frontmatter(md_file)
    title = _resolve_title(metadata, content, md_file)
    summary = ""
    for key in ("summary", "description"):
        raw = metadata.get(key)
        if isinstance(raw, str) and raw.strip():
            summary = raw.strip()
            break
    if not summary:
        summary = _first_meaningful_paragraph(content)

    when_to_use = None
    for key in ("when_to_use", "when-to-use", "use_when"):
        raw = metadata.get(key)
        if isinstance(raw, str) and raw.strip():
            when_to_use = raw.strip()
            break

    triggers = _normalize_list(metadata.get("triggers"))
    if not triggers:
        triggers = _normalize_list(metadata.get("aliases"))

    return SkillSummary(
        skill_id=_resolve_skill_id(metadata, md_file),
        title=title,
        path=md_file.relative_to(source_dir).as_posix(),
        summary=summary,
        triggers=triggers,
        when_to_use=when_to_use,
    )


def build_skills_index(source_dir: Path) -> list[SkillSummary]:
    """Scan the vault's skill folders and return normalized skill metadata."""
    source_dir = source_dir.resolve()
    results: list[SkillSummary] = []
    seen_paths: set[str] = set()
    for root in resolve_skills_dirs(source_dir):
        for md_file in sorted(root.rglob("*.md")):
            if not _is_skill_markdown(md_file, root):
                continue
            rel_path = md_file.relative_to(source_dir).as_posix()
            if rel_path in seen_paths:
                continue
            seen_paths.add(rel_path)
            results.append(_build_one_skill_summary(md_file, source_dir))
    return results


def _render_skills_markdown(skills: list[SkillSummary]) -> str:
    """Render the dynamic skill index as markdown."""
    if not skills:
        return "- No skills were discovered in the configured skill folders."

    lines: list[str] = []
    for skill in skills:
        lines.append(f"- `{skill.skill_id}` — **{skill.title}**")
        lines.append(f"  Path: `{skill.path}`")
        lines.append(f"  Summary: {skill.summary}")
        if skill.triggers:
            lines.append(f"  Triggers: {', '.join(f'`{t}`' for t in skill.triggers)}")
        if skill.when_to_use:
            lines.append(f"  When to use: {skill.when_to_use}")
    return "\n".join(lines)


async def build_tool_index(mcp: FastMCP) -> list[dict[str, str]]:
    """Return the currently visible MCP tool index for the active server."""
    tools = await mcp.list_tools()
    seen: set[str] = set()
    index: list[dict[str, str]] = []
    for tool in tools:
        if tool.name in seen:
            continue
        seen.add(tool.name)
        description = (tool.description or "").strip().splitlines()[0]
        index.append({"name": tool.name, "description": description})
    index.sort(key=lambda item: item["name"])
    return index


def _render_tool_index_markdown(tools: list[dict[str, str]]) -> str:
    """Render the visible MCP tool index as markdown."""
    if not tools:
        return "- No model-visible tools are currently registered."
    return "\n".join(
        f"- `{tool['name']}` — {tool['description']}".rstrip(" —")
        for tool in tools
    )


async def build_system_instructions_payload(
    source_dir: Path,
    *,
    mcp: FastMCP,
) -> dict[str, Any]:
    """Build the full dynamic operating context exposed by the bootstrap tool."""
    source_dir = source_dir.resolve()
    instructions_rel, instructions_content = load_operator_instructions_markdown(
        source_dir
    )

    skills = build_skills_index(source_dir)
    tool_index = await build_tool_index(mcp)

    markdown = (
        "# RHOS System Instructions\n\n"
        "These instructions are generated dynamically by the MCP server.\n\n"
        "This response already includes the current operating instructions, "
        "skill index, and visible MCP tools. Do not call `list_skills` "
        "immediately after this just to fetch the same index again; use it "
        "later only when you need a refresh.\n\n"
        "If this document is already in your context, do not call "
        "`get_system_instructions` again just to reload it. Use `list_skills` "
        "to refresh only the skill index.\n\n"
        "## Agent Instructions\n\n"
        f"Source: `{instructions_rel or 'generated fallback'}`\n\n"
        f"{instructions_content.strip()}\n\n"
        "## Available Skills\n\n"
        f"{_render_skills_markdown(skills)}\n\n"
        "## Available MCP Tools\n\n"
        f"{_render_tool_index_markdown(tool_index)}\n\n"
        "## Usage Rules\n\n"
        "- Before writing to the vault, inspect the relevant skill when one applies.\n"
        "- Prefer semantic RHOS tools over raw file writes.\n"
        "- Use `read_skill` to load the full workflow before executing a skill-specific operation.\n"
    )

    return {
        "instructions_path": instructions_rel,
        "instructions_markdown": markdown,
        "skills": [asdict(skill) for skill in skills],
        "tools": tool_index,
    }


def resolve_skill_content(
    source_dir: Path,
    *,
    skill_id: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Resolve one skill by id or path and return its full markdown content."""
    source_dir = source_dir.resolve()
    if bool(skill_id) == bool(path):
        raise ValueError("Provide exactly one of 'skill_id' or 'path'.")

    skills = build_skills_index(source_dir)
    if path is not None:
        wanted = path.strip().replace("\\", "/")
        for skill in skills:
            if skill.path == wanted:
                md_file = source_dir / skill.path
                return {
                    **asdict(skill),
                    "content": read_text_utf8(md_file),
                }
        raise ValueError(f"No skill found at path {wanted!r}.")

    wanted_id = _slugify(skill_id or "")
    matches = [skill for skill in skills if skill.skill_id == wanted_id]
    if not matches:
        raise ValueError(f"No skill found with skill_id {wanted_id!r}.")
    if len(matches) > 1:
        paths = ", ".join(f"`{skill.path}`" for skill in matches)
        raise ValueError(
            f"Skill id {wanted_id!r} is ambiguous. Use 'path' instead. Matches: {paths}"
        )

    skill = matches[0]
    return {
        **asdict(skill),
        "content": read_text_utf8(source_dir / skill.path),
    }
