# PARA Workflow Pack — Design

**Date:** 2026-04-19
**Status:** Approved design; plan pending
**Audience:** Contributors adding a PARA companion to the existing Zettelkasten pack

## Summary

Add a PARA (Projects, Areas, Resources, Archive) workflow pack as a peer to the existing Zettelkasten pack. Ship it as documentation, templates, and prompts only — **no code changes to `src/`**. The server already supports everything needed via `TEMPLATES_FOLDER`, `PROMPTS_FOLDER`, and `INDEXED_FIELDS`.

PARA is an **alternative** to Zettelkasten, not a complement. The two are presented as parallel, self-contained guides; users pick one. The guide makes clear PARA is one opinionated way to organize a vault, not a server-enforced schema.

## Goals

1. Match the depth and structure of the Zettelkasten pack so users can pick either workflow with equal confidence.
2. Codify the three canonical PARA workflows as MCP prompts: **triage**, **project kickoff**, **weekly review**.
3. Bake the "archive stale" and "resurface related" behaviors into the weekly-review and kickoff prompts respectively, rather than shipping them as standalone prompts.
4. Use frontmatter conventions that enable useful queries (`type=project status=active`, area rollups) via the server's existing `INDEXED_FIELDS` mechanism.

## Non-Goals

- New MCP tools, server code, or env vars.
- Date-range / deadline querying (filed as Future Work).
- Migration tooling from Zettelkasten to PARA.
- Hybrid Zettelkasten + PARA modes in a single vault.

## Design Decision: Archive as State, Not Type

Forte's canonical PARA treats Archive as the fourth top-level category. Mechanically this is awkward: an archived project is still a project; archiving is a lifecycle transition, not a reclassification.

**We model archive as a `status` value, with `type` preserved across the lifecycle.**

Concretely:

- `type ∈ {project, area, resource}` — the kind of thing (stable across lifetime).
- `status ∈ {active, on-hold, completed, archived}` — the lifecycle state.
- The `4-Archive/` folder is a convenience location for at-a-glance browsing; the authoritative "is this archived" signal is `status=archived`.

Why:

- Queries like `type=project status=archived` remain meaningful (past projects are still projects).
- Weekly Review filters cleanly on `status=active` without union queries across types.
- Lifecycle transitions are a single field flip (plus a `rename` to the `4-Archive/` folder); the note's identity as a project/area/resource is preserved.

## Filesystem Layout

### New files under `examples/para/`

```
examples/para/
  README.md
  templates/
    inbox.md
    project.md
    area.md
    resource.md
    weekly-review.md
  prompts/
    para-triage.md
    para-project-kickoff.md
    para-weekly-review.md
```

Mirror of `examples/zettelkasten/`. No shared files.

### Recommended user vault layout (documented in guide, not enforced)

```
vault/
  0-Inbox/        # quick capture, untyped
  1-Projects/     # active projects with outcomes
  2-Areas/        # ongoing responsibilities
  3-Resources/    # reference material
  4-Archive/      # status=archived items (any type)
  _templates/     # pointed at by MARKDOWN_VAULT_MCP_TEMPLATES_FOLDER
```

Numeric prefixes keep the four buckets sorting in Forte's canonical order. `0-Inbox/` is added because triage is a named workflow step and deserves a canonical location.

## Indexed Fields

Recommended in the guide:

```bash
export MARKDOWN_VAULT_MCP_INDEXED_FIELDS=type,status,tags,area
```

- `type` — drives type-based searches (all projects, all areas)
- `status` — drives lifecycle queries (active vs archived)
- `tags` — existing Zettelkasten convention
- `area` — on Project notes, names the parent Area for rollups (e.g., "Health")

`deadline` is **not** indexed. FTS equality filters don't support date ranges. See Future Work.

## Frontmatter Schemas

Each template below is `{{title}}`/`{{date}}` templated — the server's existing template system handles placeholder substitution.

### `inbox.md` — quick capture, untyped
```yaml
---
title: "{{title}}"
tags: []
created: {{date}}
---
```

Triage assigns `type`, `status`, and relocates the note.

### `project.md`
```yaml
---
title: "{{title}}"
type: project
status: active
outcome: "<one-sentence definition of done>"
deadline: YYYY-MM-DD
area: "<parent area name, or empty>"
tags: []
created: {{date}}
---

# {{title}}

## Outcome
<!-- What does done look like? -->

## Next actions
- [ ] ...

## Notes
```

### `area.md`
```yaml
---
title: "{{title}}"
type: area
status: active
standard: "<what 'healthy' looks like for this area>"
review_cadence: weekly | monthly | quarterly
tags: []
created: {{date}}
---
```

### `resource.md`
```yaml
---
title: "{{title}}"
type: resource
status: active
tags: []
created: {{date}}
---
```

### `weekly-review.md` — dated review note
Written to `3-Resources/reviews/YYYY-WW.md` (or user-specified path).
```yaml
---
title: "Weekly Review {{date}}"
type: resource
tags: [review]
created: {{date}}
---

# Weekly Review — {{date}}

## Active projects
## Stale projects (no edits in 14+ days)
## Area audit
## Archive candidates
## New projects / ideas
```

The template seeds the sections that the `para-weekly-review` prompt populates.

## Prompts

Each prompt is a frontmatter-annotated markdown file loaded via `PROMPTS_FOLDER`, same shape as `examples/zettelkasten/prompts/zettelkasten.md`.

**Universal constraint (applies to all three):** never edit or rename without explicit user confirmation. Mirrors the Zettelkasten prompt's safety contract.

### `para-triage.md`

**Purpose:** move Inbox notes (or any untyped note) into the correct P/A/R bucket.

**Argument:** `path` — either a folder (defaults to `0-Inbox/`) or a single note path.

**Steps:**
1. If `path` is a folder: `list_documents(folder=path)` and iterate. If a single note: skip to step 2.
2. `read(path=note)` — extract the central intent.
3. Classify:
   - Concrete outcome + deadline → **Project**
   - Ongoing responsibility, no end-state → **Area**
   - Reference material, not actionable → **Resource**
   - Ambiguous → ask the user; do not guess.
4. Propose a target path (`1-Projects/<slug>.md`, `2-Areas/<slug>.md`, `3-Resources/<slug>.md`) and the proposed frontmatter block.
5. On confirmation: `rename(old, new, update_links=True)` then `edit` to replace the untyped frontmatter with the typed version.

### `para-project-kickoff.md`

**Purpose:** turn a freshly-typed project note into an actionable one by defining outcome/deadline and resurfacing related context.

**Argument:** `path` — a project note.

**Steps:**
1. `read(path)` — check `outcome` and `deadline` are filled. If either is missing or placeholder, prompt the user.
2. **Resurface (bakes in the "just-in-time resurface" workflow):**
   - `get_context(path)` — existing neighborhood.
   - `search(outcome_text, mode='hybrid', limit=15)` — find related Resources and past Archived projects.
   - `get_similar(path, limit=10)` — semantic near-neighbors not yet linked.
3. Present three buckets to the user. Since `get_context.similar` and search results return paths but not frontmatter, classify by either (a) folder prefix (`3-Resources/` → Resource, `4-Archive/` → archived, `2-Areas/` → Area) when the user follows the canonical layout, or (b) a targeted follow-up `search` per bucket using indexed fields (e.g., `filters={"type":"resource"}`). Prefer folder prefix when available — it's one step instead of N reads.
   - Relevant Resources (from `3-Resources/` or `type=resource`)
   - Similar past Projects (`4-Archive/` or `type=project status=archived`)
   - Linkable Areas (from `2-Areas/` or `type=area`)
4. Suggest `[[wikilinks]]` to add under a `## Related` section in the project note.
5. On confirmation: `edit` to add the links.

### `para-weekly-review.md`

**Purpose:** guide the weekly review — surface stale projects, audit areas, identify archive candidates, write a dated review note.

**Argument:** optional `review_path` — where to write the review note. Defaults to `3-Resources/reviews/YYYY-WW.md`.

**Steps:**
1. `create_from_template(template_name='weekly-review')` at the review path (uses the server's existing template tool).
2. **Active projects:** `list_documents(folder="1-Projects/")` then filter by frontmatter `status=active` (alternatively, `search` with a non-empty probe like `"project"` and `filters={"type":"project","status":"active"}`, if empty-query search proves unreliable). List with deadlines.
3. **Stale scan (bakes in the "archive stale" workflow):** for each active project, pull `modified_at` via `get_context`; flag anything un-edited for 14+ days.
4. **Area audit:** enumerate active areas (same pattern as step 2 against `2-Areas/`). For each Area, count projects that reference it via the indexed `area` frontmatter field (e.g., `search(filters={"type":"project","area":"<name>","status":"active"})`). Flag Areas with zero active projects as candidates for archive or reassessment. The `area` frontmatter field is the authoritative signal here; wikilinks from project notes to the area note are not required.
5. **Archive candidates:** projects with `status=completed` still in `1-Projects/`, or stale >30 days.
6. `edit` the review note to populate the seeded sections with the findings.
7. User decides which archive candidates to move. The prompt may suggest batched `edit` + `rename` operations but **must not execute them without explicit per-item or explicit-batch confirmation**.

## Documentation Updates

### New files
- `docs/guides/para.md` — full guide, same structural template as `docs/guides/zettelkasten.md`. Sections:
  1. Intro + "one of many ways" disclaimer
  2. Vault setup (folder layout, frontmatter, indexed fields, filename conventions)
  3. Workflow: Capture → Triage → Project Work → Weekly Review → Archive
  4. Prompt walkthroughs (one subsection per prompt)
  5. Template usage (mirrors Zettelkasten guide's template section)
  6. Tips (status-over-folder, archive-by-flipping-status-then-moving, deadline caveat)
  7. Next steps (cross-links to `docs/design.md`, `docs/tools/index.md`, `examples/para/`)
- `examples/para/README.md` — mirrors `examples/zettelkasten/README.md` structure: templates section, prompts section, env config block, see-also links.

### Updated files
- `mkdocs.yml` — add PARA nav entries in both the hidden block (around line 67–69) and the visible Guides block (around line 132–134), positioned right after Zettelkasten.
- `docs/guides/index.md` — add PARA entry to the guides list.
- `docs/index.md` — add PARA mention in whichever list enumerates Zettelkasten.
- `README.md` — one-line mention alongside the existing Zettelkasten reference.
- `docs/design.md` — note PARA as a companion workflow example alongside Zettelkasten (one sentence in the relevant context).
- `packaging/mcpb/manifest.json.in` — if it references Zettelkasten, add PARA parallel entry.

### Zero changes
- `src/` — no code changes.
- `tests/` — no new tests. Prompts and templates are content, validated by humans reading them.
- Env vars — none added.

## Testing Strategy

Since this is content-only:

1. **Template smoke test:** manually run `create_from_template(template_name='project')` etc. against a scratch vault; verify placeholders substitute and the resulting note parses cleanly (frontmatter valid, indexed fields present).
2. **Prompt walkthrough:** manually exercise each prompt end-to-end on a small seed vault (3–5 notes per bucket). Verify the happy path and one ambiguous-case path for triage.
3. **Docs build:** `mkdocs build --strict` passes — catches broken links.
4. **No new automated tests.** PR reviewers (human + Gemini + claude-review bot) verify the content reads correctly.

## Risks / Tradeoffs

- **Divergence from Forte's canonical PARA:** we treat Archive as a status, not a type. The guide needs to explain this up front or users coming from Forte's book will be confused.
- **Prompts reference `create_from_template`:** the Weekly Review prompt depends on the templates folder being configured. The guide must be explicit that all three env vars (`TEMPLATES_FOLDER`, `PROMPTS_FOLDER`, `INDEXED_FIELDS`) are required for the full workflow.
- **No folder enforcement:** users can skip the folder layout entirely and rely on `type`/`status` filters alone. That's fine — the server doesn't care — but the prompts assume paths like `1-Projects/` when suggesting targets during triage. If the user has a different layout, the prompts need gentle fallback (ask "where should I put it?" rather than hard-coding).
- **Deadline not indexed:** users will want "show me projects due this week" queries. Guide must acknowledge this limit and point at Future Work.

## Future Work

1. **Date range filters in the FTS query layer.** Would enable `filters={"deadline": {"lte": "2026-05-01"}}` or similar. Touches `fts_index.py` filter parsing. File as follow-up issue after this lands.
2. **Triage auto-suggest target folder.** Currently the prompt asks the LLM to pick `1-Projects/` vs `2-Areas/` etc. based on the classification. Could be baked into a `create_from_template` extension that takes a `target_folder` hint.
3. **Bulk archive tool.** After Weekly Review produces archive candidates, a single "archive these 5 projects" action (rename to `4-Archive/` + flip status + set `archived_at`). Today the user confirms each. Worth considering if the workflow proves painful.
4. **Cross-pack migration helpers.** If users want to convert an existing Zettelkasten vault to PARA (or vice versa), a one-shot migration prompt could help. Low priority until someone asks.

## Acceptance Criteria

- `examples/para/` exists with 5 templates + 3 prompts + README, paralleling `examples/zettelkasten/`.
- `docs/guides/para.md` exists and reads at a quality bar comparable to `docs/guides/zettelkasten.md`.
- `mkdocs build --strict` passes with PARA entries wired into nav.
- A user can enable the PARA workflow with three env vars (`TEMPLATES_FOLDER`, `PROMPTS_FOLDER`, `INDEXED_FIELDS`) pointing at the example directories, with no code changes.
- The Zettelkasten pack is unchanged — both packs coexist.
