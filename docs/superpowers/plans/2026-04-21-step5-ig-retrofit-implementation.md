# Step 5: IG Retrofit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt `fastmcp-pvl-core` AND `fastmcp-server-template` v1.0.0 into `image-generation-mcp` (IG) in a single rebuild PR; ship `v1.6.0` stable on all six publish targets.

**Architecture:** Single-PR rebuild. Render template into IG via `copier copy --overwrite`, then rewrite `mcp_server.py` / `config.py` / `cli.py` to compose `fastmcp-pvl-core` primitives, restore IG's domain layer (providers, processing, service, transforms) verbatim. The 400+ lines of auth/instructions/event-store boilerplate vanish (→ core); the remaining `mcp_server.py` is ~150 lines of `make_server()` + IG's `ResourcesAsTools` wiring.

**Tech Stack:** copier ≥9, uv, fastmcp-pvl-core ≥1.0,<2, fastmcp[tasks] ≥3,<4, python-semantic-release, GitHub Actions.

**Working repos:**
- `/mnt/code/image-gen-mcp` — target (retrofit lands here on branch `chore/adopt-fastmcp-template`)
- `/mnt/code/fastmcp-server-template` — template source (at tag v1.0.0; no patches expected)
- `/mnt/code/fastmcp-pvl-core` — library reference (read-only)
- `/tmp/ig-replay` — scratch replay destination

**Spec:** `docs/superpowers/specs/2026-04-21-step5-ig-retrofit-design.md`

---

## Phase A — Setup

### Task A1: Create IG's copier answers file

**Files:**
- Create: `/tmp/ig-answers.yml`

- [ ] **Step 1: Write answers**

```bash
cat > /tmp/ig-answers.yml <<'EOF'
project_name: image-generation-mcp
pypi_name: image-generation-mcp
python_module: image_generation_mcp
env_prefix: IMAGE_GENERATION_MCP
human_name: Image Generation MCP
domain_description: MCP server for AI image generation via OpenAI, Google GenAI, or Stable Diffusion WebUI
github_org: pvliesdonk
docker_registry: ghcr.io/pvliesdonk
EOF
```

- [ ] **Step 2: Verify YAML parse**

```bash
python -c "import yaml; d = yaml.safe_load(open('/tmp/ig-answers.yml')); print(list(d.keys())); assert len(d) == 8"
```

Expected: 8 keys printed.

### Task A2: Ensure template is at v1.0.0

- [ ] **Step 1: Checkout v1.0.0**

```bash
git -C /mnt/code/fastmcp-server-template fetch --tags origin
git -C /mnt/code/fastmcp-server-template checkout v1.0.0
git -C /mnt/code/fastmcp-server-template status
```

Expected: `HEAD detached at v1.0.0`, clean.

### Task A3: Initialize scratch dir + IG branch + pre-retrofit tag

- [ ] **Step 1: Wipe + init scratch**

```bash
rm -rf /tmp/ig-replay
mkdir -p /tmp/ig-replay
git -C /tmp/ig-replay init -q
```

- [ ] **Step 2: Sync IG main and create retrofit branch**

```bash
cd /mnt/code/image-gen-mcp
git checkout main && git pull --ff-only
git status
```

Expected: clean tree, `On branch main`.

- [ ] **Step 3: Branch + pre-retrofit tag**

```bash
cd /mnt/code/image-gen-mcp
git checkout -b chore/adopt-fastmcp-template
git tag --force step5-pre-retrofit HEAD
```

The `step5-pre-retrofit` tag is the reference for `git show step5-pre-retrofit:<path>` restorations during Phase C.

---

## Phase B — Replay + diff triage

### Task B1: Render template into scratch

- [ ] **Step 1: Run copier copy**

```bash
copier copy --trust \
  --data-file /tmp/ig-answers.yml \
  --vcs-ref v1.0.0 \
  /mnt/code/fastmcp-server-template \
  /tmp/ig-replay
```

Expected: copier writes files non-interactively.

- [ ] **Step 2: Verify answers file landed**

```bash
test -f /tmp/ig-replay/.copier-answers.yml && cat /tmp/ig-replay/.copier-answers.yml
```

Expected: yaml with `_commit: v1.0.0`, the 8 answer keys, and `_src_path: /mnt/code/fastmcp-server-template` (will be rewritten to a github URL during Task C2).

### Task B2: Capture diff against IG

- [ ] **Step 1: Write diff helper**

```bash
cat > /tmp/ig-replay-diff.sh <<'SHELL'
#!/usr/bin/env bash
set -u
REPLAY="${1:-/tmp/ig-replay}"
IG="${2:-/mnt/code/image-gen-mcp}"
EXCLUDES=(
  --exclude=.git --exclude=.venv --exclude=node_modules
  --exclude=__pycache__ --exclude='.copier-answers.yml'
  --exclude='.ruff_cache' --exclude='.mypy_cache' --exclude='.pytest_cache'
  --exclude=htmlcov --exclude=coverage.xml --exclude='.coverage'
  --exclude=uv.lock --exclude=dist --exclude=build --exclude='*.egg-info'
  --exclude=.claude --exclude=site
)
diff -r "${EXCLUDES[@]}" "$REPLAY" "$IG"
SHELL
chmod +x /tmp/ig-replay-diff.sh
```

- [ ] **Step 2: Run diff**

```bash
/tmp/ig-replay-diff.sh | tee /tmp/ig-replay-diff.txt | head -200
wc -l /tmp/ig-replay-diff.txt
grep -c '^Only in /tmp/ig-replay:' /tmp/ig-replay-diff.txt
grep -c '^Only in /mnt/code/image-gen-mcp:' /tmp/ig-replay-diff.txt
grep -c '^diff -r' /tmp/ig-replay-diff.txt
```

Expected: large diff (IG is far behind on infra). Counts let you size the triage workload.

### Task B3: Triage every diff entry

**Files:**
- Create: `/tmp/ig-replay-triage.md`

- [ ] **Step 1: Scaffold triage log**

```bash
cat > /tmp/ig-replay-triage.md <<'EOF'
# IG replay triage (Step 5 Phase B)

Generated: 2026-04-21
Template: `/mnt/code/fastmcp-server-template` @ v1.0.0
Render target: `/tmp/ig-replay`
IG source: `/mnt/code/image-gen-mcp` @ main (v1.5.0)
Raw diff: `/tmp/ig-replay-diff.txt`

## Phase 1 outcome

- Class A (domain content, no action): 0 (TBD after triage)
- Class B (infra bug in IG, fix during retrofit): 0
- Class C (hybrid/sentinel + full-replacement hybrid): 0
- Class D (template bug — cut v1.0.x patch): 0
- Class E (acceptable divergence, document): 0

⚠️ NEEDS HUMAN CALL items:
- (none yet)

## Class A — Domain content (no action)

## Class B — Infra bug in IG (adopt template version)

## Class C — Hybrid (preserve IG content via sentinels or full restore)

## Class D — Infra bug in template (cut v1.0.x patch)

## Class E — Acceptable divergence (document + move on)

EOF
```

- [ ] **Step 2: Classify every entry**

This is the substantive judgment work. For EVERY entry in `/tmp/ig-replay-diff.txt`, file it into one class with a one-line rationale. Use this decision rule:

- `Only in /mnt/code/image-gen-mcp: <X>`:
  - File is image-gen domain (`providers/*.py`, `_vendored_sdk.py`, `processing.py`, `service.py`, `styles.py`, `_http_logging.py`, domain tests, asset pipeline like `node_modules/`, `package.json`, `package-lock.json`, `site/`) → **Class A**.
  - Template should produce it but didn't → **Class D**.
  - IG-specific infra template intentionally omits (e.g., `TEMPLATE.md`) → **Class E**.

- `Only in /tmp/ig-replay: <X>`:
  - Template is right and IG needs it (`.github/dependabot.yml`, `.env.example`, `_server_apps.py` scaffold) → **Class B**.
  - Template adds something IG doesn't need → **Class E**.

- `diff -r <template> <ig>`:
  - Diff inside known sentinel blocks (`PROJECT-DEPS-START/END`, `PROJECT-EXTRAS-START/END`, `CONFIG-FIELDS-START/END`, `CONFIG-FROM-ENV-START/END`, `DOMAIN-START/END`) → **Class C**.
  - Full-replacement hybrid where IG's is full domain (`mcp_server.py`, `config.py`, `cli.py`, `tools.py`, `resources.py`, `prompts.py`, `_server_*.py`, `README.md`, `server.json`, `__init__.py`, `Dockerfile`, `compose.yml`, `mkdocs.yml`, `tests/conftest.py`, workflows) → **Class C** (will be restored from `step5-pre-retrofit` OR rewritten).
  - Template version is wrong, IG's is right → **Class D**.

- [ ] **Step 3: Fill in Phase 1 outcome counts**

After triage, update the counts at the top of `/tmp/ig-replay-triage.md` and list any `⚠️ NEEDS HUMAN CALL` items.

- [ ] **Step 4: Archive triage log into IG repo**

```bash
mkdir -p /mnt/code/image-gen-mcp/docs/superpowers/notes
cp /tmp/ig-replay-triage.md \
   /mnt/code/image-gen-mcp/docs/superpowers/notes/2026-04-21-step5-replay-triage.md
```

(Will be committed as part of the Phase C retrofit.)

- [ ] **Step 5: Stop and report if Class D > 0**

If Class D ≥ 1, STOP. Patch the template per Step 4 plan §"Task B5" pattern (cut v1.0.x patch release), then re-render and re-triage. Do not proceed to Phase C until Class D = 0.

If Class D = 0, proceed to Phase C.

---

## Phase C — Retrofit IG

### Task C1: Run `copier copy --overwrite` against IG

- [ ] **Step 1: Run copier**

```bash
cd /mnt/code/image-gen-mcp
copier copy --overwrite --trust \
  --data-file /tmp/ig-answers.yml \
  --vcs-ref v1.0.0 \
  /mnt/code/fastmcp-server-template \
  .
```

Expected: copier reports files written. `.copier-answers.yml` appears at root.

- [ ] **Step 2: Inspect overall scope of changes**

```bash
git status
git diff --stat | tail -40
```

Expected: many `Modified`/`Added`/`Deleted` files. Don't commit yet.

### Task C2: Fix `.copier-answers.yml` `_src_path` and verify

- [ ] **Step 1: Replace local fs path with github URL**

(Same fix MV needed in Step 4 PR #407 round 1 — claude-review caught local paths break `copier update` from any other checkout.)

```bash
sed -i 's|^_src_path: /mnt/code/fastmcp-server-template$|_src_path: https://github.com/pvliesdonk/fastmcp-server-template|' \
  /mnt/code/image-gen-mcp/.copier-answers.yml
cat /mnt/code/image-gen-mcp/.copier-answers.yml
```

Expected: `_src_path: https://github.com/pvliesdonk/fastmcp-server-template` and `_commit: v1.0.0`.

### Task C3: Restore `pyproject.toml` (full restore + add core dep)

**Files:**
- Modify: `/mnt/code/image-gen-mcp/pyproject.toml`

- [ ] **Step 1: Restore IG's pre-retrofit pyproject**

```bash
cd /mnt/code/image-gen-mcp
git show step5-pre-retrofit:pyproject.toml > pyproject.toml
```

- [ ] **Step 2: Add fastmcp-pvl-core to dependencies**

Find the `dependencies = [` line and add `"fastmcp-pvl-core>=1.0,<2",` to the list. Also fix the placeholder description and authors.

```python
# Before:
dependencies = ["httpx>=0.27", "Pillow>=10.0"]
description = "FastMCP server template — replace this with your description"
authors = [{ name = "Your Name" }]

# After:
dependencies = [
    "fastmcp-pvl-core>=1.0,<2",
    "httpx>=0.27",
    "Pillow>=10.0",
]
description = "MCP server for AI image generation via OpenAI, Google GenAI, or Stable Diffusion WebUI"
authors = [{ name = "Peter van Liesdonk" }]
```

Apply via `Edit` tool. Verify:

```bash
grep -E '^dependencies|fastmcp-pvl-core|^description|^authors' pyproject.toml | head -10
```

### Task C4: Restore other Class C hybrids (full-restore)

**Files:**
- `CLAUDE.md`, `README.md`, `server.json`, `mkdocs.yml`, `compose.yml`, `Dockerfile`, `docker-entrypoint.sh`, `tests/conftest.py`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `packaging/nfpm.yaml`, `packaging/scripts/postinstall.sh`, `LICENSE`, `examples/*` (if changed)

- [ ] **Step 1: Restore each file from pre-retrofit**

```bash
cd /mnt/code/image-gen-mcp
for f in CLAUDE.md README.md server.json mkdocs.yml compose.yml Dockerfile \
         docker-entrypoint.sh tests/conftest.py .pre-commit-config.yaml \
         packaging/nfpm.yaml packaging/scripts/postinstall.sh LICENSE; do
  if git cat-file -e step5-pre-retrofit:"$f" 2>/dev/null; then
    git show step5-pre-retrofit:"$f" > "$f"
  fi
done
```

- [ ] **Step 2: Decide on workflows individually**

Workflows are the infra refresh — IG is far behind. For each workflow:

```bash
git diff step5-pre-retrofit -- .github/workflows/release.yml | head -40
```

Look for: `prerelease` input, `prerelease_token: rc`, `actions/checkout@v6`, `astral-sh/setup-uv@v8.0.0`. Template version should win for these (Class B adoption). Keep IG-specific bits (image labels, environment URLs, IG's `IMAGE_GENERATION_MCP` references) — copier already templated them.

Inspect `release.yml`, `ci.yml`, `claude-code-review.yml`, `claude.yml`, `codeql.yml`, `docs.yml`. **Keep template versions for all of them**. Verify by re-running diff:

```bash
git diff step5-pre-retrofit -- .github/workflows/ | head -60
```

Expected: many lines changed. If anything looks IG-domain (e.g., GitHub Pages site path, codecov flags), surgically restore that line from pre-retrofit; otherwise keep template version.

### Task C5: Rewrite `config.py` — compose ServerConfig, drop hand-rolled helpers

**Files:**
- Modify: `/mnt/code/image-gen-mcp/src/image_generation_mcp/config.py`

- [ ] **Step 1: Inspect template's rendered `config.py`**

```bash
cat /mnt/code/image-gen-mcp/src/image_generation_mcp/config.py
```

The template should have produced a skeleton with `ProjectConfig` + sentinel blocks. Confirm it's there.

- [ ] **Step 2: Write the new config.py**

Replace the file contents with:

```python
"""Project configuration for image-generation-mcp.

Composes ``fastmcp_pvl_core.ServerConfig`` for transport/auth/event-store
fields; adds image-generation domain fields below.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from fastmcp_pvl_core import ServerConfig, env, parse_bool, parse_list

logger = logging.getLogger(__name__)

_ENV_PREFIX = "IMAGE_GENERATION_MCP"


_DEFAULT_SCRATCH_DIR = Path.home() / ".image-generation-mcp" / "images"
_DEFAULT_STYLES_DIR = Path.home() / ".image-generation-mcp" / "styles"


@dataclass
class ProjectConfig:
    """Image-generation-mcp configuration loaded from environment variables.

    The ``server`` field carries generic FastMCP server config (transport,
    auth, event store). Domain fields (provider keys, scratch dir, etc.)
    live directly on this dataclass.
    """

    # CONFIG-FIELDS-START — image-generation domain fields; kept across copier update
    server: ServerConfig = field(default_factory=ServerConfig)
    read_only: bool = True
    scratch_dir: Path = field(default_factory=lambda: _DEFAULT_SCRATCH_DIR)
    openai_api_key: str | None = None
    google_api_key: str | None = None
    sd_webui_host: str | None = None
    sd_webui_model: str | None = None
    default_provider: str = "auto"
    transform_cache_size: int = 64
    paid_providers: frozenset[str] = frozenset({"openai"})
    styles_dir: Path = field(default_factory=lambda: _DEFAULT_STYLES_DIR)
    # CONFIG-FIELDS-END


def load_config() -> ProjectConfig:
    """Load configuration from environment variables.

    Reads:

    - ``IMAGE_GENERATION_MCP_READ_ONLY``: disable write tools; default ``true``.
    - ``IMAGE_GENERATION_MCP_SCRATCH_DIR``: image save directory.
    - ``IMAGE_GENERATION_MCP_OPENAI_API_KEY``: OpenAI API key.
    - ``IMAGE_GENERATION_MCP_GOOGLE_API_KEY``: Google API key (Gemini).
    - ``IMAGE_GENERATION_MCP_SD_WEBUI_HOST``: SD WebUI URL (also accepts deprecated ``A1111_HOST``).
    - ``IMAGE_GENERATION_MCP_SD_WEBUI_MODEL``: SD WebUI checkpoint name (also accepts deprecated ``A1111_MODEL``).
    - ``IMAGE_GENERATION_MCP_DEFAULT_PROVIDER``: default provider; default ``"auto"``.
    - ``IMAGE_GENERATION_MCP_TRANSFORM_CACHE_SIZE``: transform LRU cache size; default ``64``.
    - ``IMAGE_GENERATION_MCP_PAID_PROVIDERS``: comma-separated list; default ``"openai"``.
    - ``IMAGE_GENERATION_MCP_STYLES_DIR``: style preset dir; default ``~/.image-generation-mcp/styles/``.

    Plus all generic ``ServerConfig`` env vars (BASE_URL, BEARER_TOKEN,
    OIDC_*, EVENT_STORE_URL, SERVER_NAME, INSTRUCTIONS) — see
    ``fastmcp_pvl_core.ServerConfig.from_env``.

    Returns:
        A populated :class:`ProjectConfig` instance.
    """
    server = ServerConfig.from_env(env_prefix=_ENV_PREFIX)

    # CONFIG-FROM-ENV-START — image-generation domain reads; kept across copier update
    read_only = parse_bool(env(f"{_ENV_PREFIX}_READ_ONLY", "true"))

    scratch_dir = Path(env(f"{_ENV_PREFIX}_SCRATCH_DIR") or _DEFAULT_SCRATCH_DIR)

    openai_api_key = env(f"{_ENV_PREFIX}_OPENAI_API_KEY")
    google_api_key = env(f"{_ENV_PREFIX}_GOOGLE_API_KEY")

    sd_webui_host = env(f"{_ENV_PREFIX}_SD_WEBUI_HOST")
    if not sd_webui_host:
        if legacy := env(f"{_ENV_PREFIX}_A1111_HOST"):
            logger.warning(
                "IMAGE_GENERATION_MCP_A1111_HOST is deprecated — "
                "use IMAGE_GENERATION_MCP_SD_WEBUI_HOST instead"
            )
            sd_webui_host = legacy

    sd_webui_model = env(f"{_ENV_PREFIX}_SD_WEBUI_MODEL")
    if not sd_webui_model:
        if legacy := env(f"{_ENV_PREFIX}_A1111_MODEL"):
            logger.warning(
                "IMAGE_GENERATION_MCP_A1111_MODEL is deprecated — "
                "use IMAGE_GENERATION_MCP_SD_WEBUI_MODEL instead"
            )
            sd_webui_model = legacy

    default_provider = env(f"{_ENV_PREFIX}_DEFAULT_PROVIDER") or "auto"
    if default_provider == "a1111":
        logger.warning(
            "DEFAULT_PROVIDER='a1111' is deprecated — use 'sd_webui' instead"
        )
        default_provider = "sd_webui"

    raw_cache = env(f"{_ENV_PREFIX}_TRANSFORM_CACHE_SIZE")
    transform_cache_size = 64
    if raw_cache:
        try:
            transform_cache_size = int(raw_cache)
        except ValueError:
            logger.warning(
                "Invalid TRANSFORM_CACHE_SIZE=%r — using default 64", raw_cache
            )

    raw_paid = env(f"{_ENV_PREFIX}_PAID_PROVIDERS")
    paid_providers = (
        frozenset(p.lower() for p in parse_list(raw_paid))
        if raw_paid is not None
        else frozenset({"openai"})
    )

    styles_dir = Path(env(f"{_ENV_PREFIX}_STYLES_DIR") or _DEFAULT_STYLES_DIR)

    config = ProjectConfig(
        server=server,
        read_only=read_only,
        scratch_dir=scratch_dir,
        openai_api_key=openai_api_key,
        google_api_key=google_api_key,
        sd_webui_host=sd_webui_host,
        sd_webui_model=sd_webui_model,
        default_provider=default_provider,
        transform_cache_size=transform_cache_size,
        paid_providers=paid_providers,
        styles_dir=styles_dir,
    )
    # CONFIG-FROM-ENV-END

    logger.debug("load_config: read_only=%s", config.read_only)
    return config
```

Use `Write` to overwrite the file.

**Note on rename:** IG previously had a class named `ServerConfig`. We rename it to `ProjectConfig` to avoid collision with `fastmcp_pvl_core.ServerConfig`. All consumers (mcp_server.py, _server_deps.py, tests) need their imports updated — handled in subsequent tasks.

### Task C6: Update IG modules that import `ServerConfig` from config

**Files:**
- `src/image_generation_mcp/_server_deps.py`
- `src/image_generation_mcp/mcp_server.py` (handled in Task C7)
- `tests/test_config.py` and others (handled in Task C12)

- [ ] **Step 1: Update `_server_deps.py`**

Find the import:

```python
from image_generation_mcp.config import ServerConfig
```

Replace with:

```python
from image_generation_mcp.config import ProjectConfig
```

And rename the type annotation in `make_service_lifespan`:

```python
def make_service_lifespan(config: ServerConfig) -> Callable[..., AsyncIterator[Any]]:
```

becomes

```python
def make_service_lifespan(config: ProjectConfig) -> Callable[..., AsyncIterator[Any]]:
```

Apply via `Edit` tool. Run a sanity grep:

```bash
cd /mnt/code/image-gen-mcp
grep -rn 'config\.ServerConfig\|config import ServerConfig' src/ tests/ 2>&1 | head -20
```

Expected after fix: zero hits in `src/` (only `fastmcp_pvl_core.ServerConfig` imports remain).

### Task C7: Rewrite `mcp_server.py` as `make_server()`

**Files:**
- Modify: `/mnt/code/image-gen-mcp/src/image_generation_mcp/mcp_server.py`

- [ ] **Step 1: Inspect the current 533-line file**

```bash
wc -l /mnt/code/image-gen-mcp/src/image_generation_mcp/mcp_server.py
```

Expected: 533 lines.

- [ ] **Step 2: Replace contents with the new `make_server()` shape**

Use `Write` tool to replace the file with:

```python
"""Image Generation MCP — FastMCP server entry point.

Composes the primitives from ``fastmcp-pvl-core`` into IG's
``make_server()``.  See https://gofastmcp.com/servers for the FastMCP
server surface and the fastmcp-pvl-core README for the helpers used here.
"""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from fastmcp import FastMCP
from fastmcp.server.transforms import ResourcesAsTools
from fastmcp_pvl_core import (
    build_auth,
    build_event_store,  # noqa: F401  — re-exported for downstream tests/scripts
    build_instructions,
    configure_logging_from_env,
    resolve_auth_mode,
    wire_middleware_stack,
)
from mcp.types import Icon

from image_generation_mcp._server_deps import make_service_lifespan
from image_generation_mcp._server_prompts import register_prompts
from image_generation_mcp._server_resources import register_resources
from image_generation_mcp._server_tools import register_tools
from image_generation_mcp.config import ProjectConfig

logger = logging.getLogger(__name__)

_ENV_PREFIX = "IMAGE_GENERATION_MCP"
_LUCIDE = "https://unpkg.com/lucide-static/icons/{}.svg"


def make_server(
    *,
    transport: str = "stdio",
    config: ProjectConfig | None = None,
) -> FastMCP:
    """Construct the Image Generation MCP FastMCP server.

    Args:
        transport: ``"stdio"`` / ``"http"`` / ``"sse"``.  HTTP-only
            features (artifact downloads) are wired only when transport
            != ``"stdio"``.
        config: Optional pre-loaded config; defaults to env-based load.

    Returns:
        A configured :class:`fastmcp.FastMCP` instance.
    """
    if config is None:
        from image_generation_mcp.config import load_config

        config = load_config()
    configure_logging_from_env()

    auth = build_auth(config.server)
    auth_mode = resolve_auth_mode(config.server) if auth is not None else "none"
    if auth_mode == "none":
        logger.warning(
            "No auth configured — server accepts unauthenticated connections"
        )
    else:
        logger.info("Auth enabled: mode=%s", auth_mode)

    try:
        pkg_ver = _pkg_version("image-generation-mcp")
    except PackageNotFoundError:
        pkg_ver = "unknown"

    logger.info(
        "Server config: name=image-generation-mcp version=%s auth=%s mode=%s",
        pkg_ver,
        auth_mode,
        "read-only" if config.read_only else "read-write",
    )

    mcp = FastMCP(
        name="image-generation-mcp",
        instructions=build_instructions(
            read_only=config.read_only,
            env_prefix=_ENV_PREFIX,
            domain_line=(
                "AI image generation server supporting multiple providers "
                "(OpenAI gpt-image-1/dall-e-3, Google Gemini image, "
                "Stable Diffusion via SD WebUI, and a zero-cost placeholder). "
                "Start by calling list_providers to see configured providers."
            ),
        ),
        icons=[Icon(src=_LUCIDE.format("palette"), mimeType="image/svg+xml")],
        lifespan=make_service_lifespan(config),
        auth=auth,
    )

    wire_middleware_stack(mcp)

    register_tools(mcp, transport=transport)
    register_resources(mcp)
    register_prompts(mcp)

    if transport != "stdio":
        from image_generation_mcp.artifacts import make_artifact_handler

        artifact_handler = make_artifact_handler()

        from starlette.requests import Request
        from starlette.responses import Response

        @mcp.custom_route("/artifacts/{token}", methods=["GET"])
        async def _artifact_route(request: Request) -> Response:
            return await artifact_handler(request)

    # IG-specific: expose resources as tools for clients without resource support.
    # Apply AFTER all registrations so the transform sees every resource.
    mcp.add_transform(ResourcesAsTools(mcp))

    if config.read_only:
        mcp.disable(tags={"write"})

    return mcp


# Backward-compat alias: existing callers import `create_server` from this module.
create_server = make_server
```

**Note on the `create_server = make_server` alias:** IG's tests likely import `create_server`. The alias keeps existing tests working while the new `make_server` name matches the template convention. Remove the alias in a follow-up PR after verifying nothing relies on the old name.

- [ ] **Step 3: Verify the rewrite compiles**

```bash
cd /mnt/code/image-gen-mcp
uv run python -c "from image_generation_mcp.mcp_server import make_server, create_server; print('OK')"
```

Expected: `OK` printed (will fail if imports don't resolve — that's a sign Task C5/C6 missed something, fix and re-run).

### Task C8: Rewrite `cli.py` to use core helpers

**Files:**
- Modify: `/mnt/code/image-gen-mcp/src/image_generation_mcp/cli.py`

- [ ] **Step 1: Inspect current cli.py**

```bash
cat /mnt/code/image-gen-mcp/src/image_generation_mcp/cli.py
```

It has its own `_normalise_http_path` (lines 22-39) and uses `fastmcp.utilities.logging.configure_logging` directly.

- [ ] **Step 2: Replace `_normalise_http_path` with core helper**

In `cli.py`:

Find the imports block and add:

```python
from fastmcp_pvl_core import configure_logging_from_env, normalise_http_path
```

Delete the entire `_normalise_http_path` function (lines ~22-39) and `_DEFAULT_HTTP_PATH` constant (line ~21) since core's `normalise_http_path` handles both.

Find every call site of `_normalise_http_path(...)` and change to `normalise_http_path(...)`.

- [ ] **Step 3: Replace `configure_logging` with `configure_logging_from_env`**

Find this pattern:

```python
from fastmcp.utilities.logging import configure_logging
...
configure_logging(level)  # or similar
```

Replace with:

```python
from fastmcp_pvl_core import configure_logging_from_env
...
configure_logging_from_env(verbose=args.verbose)
```

- [ ] **Step 4: Verify cli.py compiles + parses args**

```bash
cd /mnt/code/image-gen-mcp
uv run python -m image_generation_mcp.cli --help
```

Expected: help text printed; no ImportError.

### Task C9: Verify Class A domain modules untouched

**Files:**
- All under `src/image_generation_mcp/providers/`, plus `_vendored_sdk.py`, `processing.py`, `service.py`, `styles.py`, `_http_logging.py`, `artifacts.py`

- [ ] **Step 1: Diff each Class A module against pre-retrofit**

```bash
cd /mnt/code/image-gen-mcp
for f in \
  src/image_generation_mcp/providers/capabilities.py \
  src/image_generation_mcp/providers/gemini.py \
  src/image_generation_mcp/providers/openai.py \
  src/image_generation_mcp/providers/placeholder.py \
  src/image_generation_mcp/providers/sd_webui.py \
  src/image_generation_mcp/providers/selector.py \
  src/image_generation_mcp/providers/types.py \
  src/image_generation_mcp/_vendored_sdk.py \
  src/image_generation_mcp/processing.py \
  src/image_generation_mcp/service.py \
  src/image_generation_mcp/styles.py \
  src/image_generation_mcp/_http_logging.py \
  src/image_generation_mcp/artifacts.py; do
  diff_count=$(git diff step5-pre-retrofit -- "$f" | wc -l)
  echo "$diff_count	$f"
done
```

Expected: every line shows `0`. If any non-zero, restore from pre-retrofit:

```bash
git show step5-pre-retrofit:<path> > <path>
```

These files are pure domain — copier should not have touched them (they don't exist as templates), but verify.

### Task C10: Restore `_server_*.py` registration modules

**Files:**
- `src/image_generation_mcp/_server_deps.py`
- `src/image_generation_mcp/_server_tools.py`
- `src/image_generation_mcp/_server_resources.py`
- `src/image_generation_mcp/_server_prompts.py`

- [ ] **Step 1: Check current state**

```bash
cd /mnt/code/image-gen-mcp
for f in _server_deps _server_tools _server_resources _server_prompts; do
  diff_count=$(git diff step5-pre-retrofit -- "src/image_generation_mcp/$f.py" | wc -l)
  echo "$diff_count	$f.py"
done
```

The template ships starter `tools.py`/`resources.py`/`prompts.py` (no underscore prefix); IG uses `_server_*` with underscore. Copier shouldn't have touched IG's `_server_*` files. Verify.

- [ ] **Step 2: If any changed, restore — except for `_server_deps.py` which got the ServerConfig→ProjectConfig rename in Task C6**

```bash
cd /mnt/code/image-gen-mcp
for f in _server_tools _server_resources _server_prompts; do
  if git diff --quiet step5-pre-retrofit -- "src/image_generation_mcp/$f.py"; then
    echo "$f: clean"
  else
    git show step5-pre-retrofit:"src/image_generation_mcp/$f.py" > "src/image_generation_mcp/$f.py"
    echo "$f: restored"
  fi
done
```

### Task C11: Delete template scaffold files that shadow IG modules

**Files:**
- Delete: `src/image_generation_mcp/{server,domain,tools,resources,prompts}.py` (if copier created them)
- Delete: `tests/test_smoke.py`, `tests/test_tools.py` (if copier created them and IG already has equivalent tests)

- [ ] **Step 1: Identify template scaffolds copier created**

```bash
cd /mnt/code/image-gen-mcp
git diff --diff-filter=A --name-only step5-pre-retrofit -- src/image_generation_mcp/ tests/ | head -20
```

Expected: includes some of `server.py`, `domain.py`, `tools.py`, `resources.py`, `prompts.py`, `tests/test_smoke.py`, `tests/test_tools.py` — files copier added because IG didn't have them.

- [ ] **Step 2: Delete the conflicting template scaffolds**

```bash
cd /mnt/code/image-gen-mcp
for f in \
  src/image_generation_mcp/server.py \
  src/image_generation_mcp/domain.py \
  src/image_generation_mcp/tools.py \
  src/image_generation_mcp/resources.py \
  src/image_generation_mcp/prompts.py \
  tests/test_smoke.py \
  tests/test_tools.py; do
  if [ -f "$f" ]; then
    rm "$f"
    echo "deleted: $f"
  fi
done
```

These are template scaffolds for projects that don't have the `_server_*.py` split. IG uses the underscore-prefixed convention so the bare scaffolds are dead code that would shadow real modules.

### Task C12: Update test imports for `ProjectConfig` rename

**Files:**
- `tests/test_config.py`, `tests/test_*.py` that import `ServerConfig` from `image_generation_mcp.config`

- [ ] **Step 1: Find all references**

```bash
cd /mnt/code/image-gen-mcp
grep -rn 'image_generation_mcp.config.*ServerConfig\|from image_generation_mcp.config import.*ServerConfig\|config\.ServerConfig' tests/ src/ | head -20
```

- [ ] **Step 2: Rename in tests**

For every match, change `ServerConfig` to `ProjectConfig`. Use sed:

```bash
cd /mnt/code/image-gen-mcp
grep -rl 'from image_generation_mcp.config import.*ServerConfig\|image_generation_mcp\.config\.ServerConfig\|config\.ServerConfig' tests/ | while read f; do
  sed -i 's/\(from image_generation_mcp\.config import.*\)ServerConfig/\1ProjectConfig/g' "$f"
  sed -i 's/image_generation_mcp\.config\.ServerConfig/image_generation_mcp.config.ProjectConfig/g' "$f"
  sed -i 's/\bconfig\.ServerConfig\b/config.ProjectConfig/g' "$f"
  echo "updated: $f"
done
```

- [ ] **Step 3: Verify**

```bash
cd /mnt/code/image-gen-mcp
grep -rn 'config\.ServerConfig\|from image_generation_mcp\.config import.*ServerConfig' tests/ src/ | grep -v 'fastmcp_pvl_core'
```

Expected: zero output (only `fastmcp_pvl_core.ServerConfig` references remain, which is correct).

### Task C13: Restore `__init__.py` if needed

- [ ] **Step 1: Diff against pre-retrofit**

```bash
git diff step5-pre-retrofit -- src/image_generation_mcp/__init__.py
```

- [ ] **Step 2: Restore IG's exports**

```bash
git show step5-pre-retrofit:src/image_generation_mcp/__init__.py \
  > src/image_generation_mcp/__init__.py
```

(IG's `__init__.py` exports public API surface; template has minimal version line. IG version wins.)

### Task C14: Restore IG-specific extras (docs/, examples/, scripts/, packaging/)

- [ ] **Step 1: Restore docs/**

```bash
cd /mnt/code/image-gen-mcp
git diff --name-only step5-pre-retrofit HEAD -- docs/ | while read f; do
  if git cat-file -e step5-pre-retrofit:"$f" 2>/dev/null; then
    git show step5-pre-retrofit:"$f" > "$f"
  fi
done
```

- [ ] **Step 2: Restore examples/, scripts/, packaging/**

```bash
cd /mnt/code/image-gen-mcp
for d in examples scripts packaging; do
  git diff --name-only step5-pre-retrofit HEAD -- $d/ | while read f; do
    if git cat-file -e step5-pre-retrofit:"$f" 2>/dev/null; then
      git show step5-pre-retrofit:"$f" > "$f"
    fi
  done
done
```

- [ ] **Step 3: Decide on TEMPLATE.md**

```bash
ls /mnt/code/image-gen-mcp/TEMPLATE.md 2>&1
```

If present and Class E (acceptable divergence — historical artifact from when IG was bootstrapped from the old fastmcp-server-template), keep it. Or delete if cruft:

```bash
# Optional cleanup:
rm /mnt/code/image-gen-mcp/TEMPLATE.md  # only if you decide it's cruft
```

### Task C15: Cleanup pass — verify no domain code missing

- [ ] **Step 1: Check for accidental domain deletions**

```bash
cd /mnt/code/image-gen-mcp
git status --porcelain | grep '^ D' | head -20
```

For every `D` line, decide:
- Class A domain (providers, processing, service, etc.) → restore: `git checkout step5-pre-retrofit -- <path>`
- Template scaffold deleted in Task C11 → leave deleted
- Truly removed by template (rare) → leave deleted

- [ ] **Step 2: Inspect overall scope**

```bash
git status
git diff --stat HEAD | tail -30
```

Expected: many files staged. Domain modules unchanged. Infra files reflect template.

### Task C16: Run the gate — iteration loop

- [ ] **Step 1: uv sync**

```bash
cd /mnt/code/image-gen-mcp
uv sync --all-extras --dev
```

Expected: clean sync. If resolver fails on `fastmcp-pvl-core`, double-check Task C3 added it correctly.

- [ ] **Step 2: ruff check --fix**

```bash
uv run ruff check --fix .
```

Expected: exit 0 or auto-fixed items.

- [ ] **Step 3: ruff format**

```bash
uv run ruff format .
uv run ruff format --check .
```

Expected: `--check` reports `All done!`.

- [ ] **Step 4: mypy**

```bash
uv run mypy src/
```

Expected: `Success: no issues found`. Common failures:
- `ProjectConfig` missing field referenced somewhere → add to dataclass.
- `_load()` shadowing — rename if conflict.
- Missing import — add it.

- [ ] **Step 5: pytest**

```bash
uv run pytest -x -q
```

Expected: all IG tests pass. If failures:
- Test imports `ServerConfig` from `image_generation_mcp.config` → fix in Task C12 (re-run sed).
- Test imports `create_server` → already aliased in Task C7.
- Test references old `_build_*_auth` helpers → those are gone; tests need updates to use core's `build_auth` / `resolve_auth_mode`.

- [ ] **Step 6: Iterate**

If gate fails, fix the specific issue (don't skip), then rerun from Step 2. Iterate until all five steps green.

### Task C17: Audit — confirm no duplicate infra code

- [ ] **Step 1: Grep for hand-rolled auth/middleware/logging**

```bash
cd /mnt/code/image-gen-mcp
grep -rn '_build_bearer_auth\|_build_oidc_auth\|_build_remote_auth\|_resolve_auth_mode\|_build_default_instructions' src/
```

Expected: zero hits in `src/` (all moved to core).

- [ ] **Step 2: Grep for hand-rolled `_normalise_http_path`**

```bash
grep -rn '_normalise_http_path\|_DEFAULT_HTTP_PATH' src/
```

Expected: zero hits.

- [ ] **Step 3: Grep for hand-rolled `build_event_store`**

```bash
grep -rn '^def build_event_store\|_DEFAULT_EVENT_STORE_DIR' src/
```

Expected: zero local definitions (only imports from `fastmcp_pvl_core`).

- [ ] **Step 4: Confirm mcp_server.py size**

```bash
wc -l src/image_generation_mcp/mcp_server.py
```

Expected: ~150 lines (down from 533).

### Task C18: Commit the retrofit

- [ ] **Step 1: Stage everything**

```bash
cd /mnt/code/image-gen-mcp
git add -A
git status
```

Verify nothing unexpected (no `.venv`, no `__pycache__`).

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore: adopt fastmcp-server-template v1.0.0 + fastmcp-pvl-core

Rebuild IG onto the copier template + fastmcp-pvl-core in a single PR.

Adopted (template):
- .copier-answers.yml pinning template v1.0.0
- .github/dependabot.yml, .env.example, CHANGELOG preamble
- Refreshed CI/release workflows (checkout@v6, setup-uv@v8.0.0,
  prerelease+prerelease_token: rc inputs)
- Refreshed Dockerfile/entrypoint/packaging (where IG was stale)

Adopted (fastmcp-pvl-core):
- config.py: ProjectConfig composes ServerConfig (rename from local
  ServerConfig); load_config() uses core's env/parse_bool/parse_list.
- mcp_server.py: 533 → ~150 lines.  make_server() composes build_auth,
  wire_middleware_stack, build_instructions, configure_logging_from_env,
  resolve_auth_mode from fastmcp-pvl-core.  Local _build_bearer_auth /
  _build_oidc_auth / _build_remote_auth / _resolve_auth_mode /
  _build_default_instructions / build_event_store all deleted.
  create_server kept as alias for backward compat with existing tests.
- cli.py: adopt configure_logging_from_env + normalise_http_path from
  core; drop hand-rolled _normalise_http_path.

Preserved (domain):
- providers/* (openai, gemini, sd_webui, placeholder, capabilities,
  selector, types)
- _vendored_sdk.py, processing.py, service.py, styles.py, _http_logging.py
- artifacts.py (IG-specific transform-on-fetch shape, not eager bytes)
- _server_deps.py, _server_tools.py, _server_resources.py, _server_prompts.py
- ResourcesAsTools transform applied in make_server()
- All domain tests, examples, docs, asset pipeline (node_modules, site)

Phase B replay triage archived at
docs/superpowers/notes/2026-04-21-step5-replay-triage.md.
Spec: docs/superpowers/specs/2026-04-21-step5-ig-retrofit-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; pre-commit hooks pass.

### Task C19: Push branch and open PR

- [ ] **Step 1: Push**

```bash
cd /mnt/code/image-gen-mcp
git push -u origin chore/adopt-fastmcp-template
```

- [ ] **Step 2: Open PR**

```bash
cd /mnt/code/image-gen-mcp
gh pr create \
  --title "chore: adopt fastmcp-server-template v1.0.0 + fastmcp-pvl-core" \
  --body "$(cat <<'EOF'
## Summary

Step 5 of the fastmcp-pvl-core extraction: IG adopts both the copier
template **and** fastmcp-pvl-core in a single rebuild PR.

This is the first time the platform has been adopted by a project that
wasn't already on fastmcp-pvl-core (MV had core via PRs #396-#403 before
its Step 4 retrofit).  So Step 5 combines:

- Template adoption (workflows, Dockerfile, packaging — Class B refresh)
- Code adoption (`mcp_server.py` 533 → ~150 lines, `config.py` restructured,
  `cli.py` uses core helpers)
- Domain preservation (`providers/`, `_vendored_sdk`, `processing`,
  `service`, `styles`, `_http_logging`, `artifacts`, all domain tests)

## Test plan

- [x] `uv run pytest -x -q` — all tests pass
- [x] `uv run ruff check .` — clean
- [x] `uv run ruff format --check .` — clean
- [x] `uv run mypy src/` — clean
- [x] Grep audit: no duplicate auth/middleware/logging/event-store code
      left in `image_generation_mcp/`
- [ ] CI green on PR
- [ ] Post-merge: `v1.6.0-rc.1` smoke release (Step 5 Phase D)
- [ ] Post-merge: `v1.6.0` stable release (Step 5 Phase E)

## Spec

`docs/superpowers/specs/2026-04-21-step5-ig-retrofit-design.md` (in MV repo).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch CI**

```bash
gh pr checks --watch
```

Expected: all required checks pass (Lint, Type Check, Tests for each Python version, codecov/patch via diff-cover, claude-review). If checks fail:
- Test failure → revisit gate iteration in Task C16.
- claude-review finds issues → fix per claude-review feedback (mirror the Step 4 PR #407 round 1 / round 2 pattern).

### Task C20: Merge the retrofit PR

- [ ] **Step 1: Merge (after explicit user go-ahead)**

```bash
gh pr merge --merge
```

(Note: not `--squash`; the repo prefers merge commits to preserve PSR-readable conventional commits.)

- [ ] **Step 2: Sync local main**

```bash
cd /mnt/code/image-gen-mcp
git checkout main
git pull --ff-only
git branch -D chore/adopt-fastmcp-template
git tag --delete step5-pre-retrofit
```

---

## Phase D — Release pipeline validation 3a (`v1.6.0-rc.1`)

### Task D1: Trigger prerelease workflow

- [ ] **Step 1: Confirm main is green**

```bash
cd /mnt/code/image-gen-mcp
git checkout main && git pull --ff-only
gh run list --branch main --limit 3
```

- [ ] **Step 2: Trigger prerelease**

```bash
gh workflow run release.yml -f force=minor -f prerelease=true
sleep 5
RUN_ID=$(gh run list --workflow release.yml --limit 1 --json databaseId -q '.[0].databaseId')
echo "Run: $RUN_ID"
gh run watch "$RUN_ID"
```

Expected: workflow completes successfully. PSR cuts `v1.6.0-rc.1`. PyPI / Linux packages / MCP Registry / Claude Plugin PR all skipped (rc-gated).

### Task D2: Verify rc.1 artifacts + smoke test

- [ ] **Step 1: Verify tag and release**

```bash
git -C /mnt/code/image-gen-mcp fetch --tags origin
git -C /mnt/code/image-gen-mcp tag --sort=-v:refname | head -3
gh release view v1.6.0-rc.1 --json tagName,isPrerelease,assets \
  -q '{tag: .tagName, isPrerelease, assets: [.assets[].name]}'
```

Expected: tag `v1.6.0-rc.1` present, `isPrerelease: true`, assets include `.mcpb` + sbom + plugin.json + server.json + wheel + sdist.

- [ ] **Step 2: Verify Docker multi-arch**

```bash
docker manifest inspect ghcr.io/pvliesdonk/image-generation-mcp:v1.6.0-rc.1 \
  | jq '.manifests[].platform' | head -10
```

Expected: `linux/amd64` and `linux/arm64` entries.

- [ ] **Step 3: Verify PyPI was NOT published**

```bash
curl -sS https://pypi.org/pypi/image-generation-mcp/json | jq -r '.releases | keys[]' | grep '1.6' \
  && echo "UNEXPECTED: rc on PyPI" || echo "OK: rc not on PyPI"
```

Expected: `OK: rc not on PyPI`.

- [ ] **Step 4: Smoke test the rc image**

```bash
docker pull ghcr.io/pvliesdonk/image-generation-mcp:v1.6.0-rc.1
docker rm -f ig-rc-smoke 2>/dev/null
docker run -d --name ig-rc-smoke \
  -p 18001:8000 \
  ghcr.io/pvliesdonk/image-generation-mcp:v1.6.0-rc.1 \
  image-generation-mcp serve --transport http --host 0.0.0.0 --port 8000
sleep 8
docker logs ig-rc-smoke 2>&1 | grep -E '(version|listening|Server|started|FAIL|Error)' | head -10
curl -sS -o /dev/null -w 'status=%{http_code}\n' http://localhost:18001/mcp
docker rm -f ig-rc-smoke
```

Expected: log line `Server config: name=image-generation-mcp version=1.6.0rc1 ...`, then `Uvicorn running on http://0.0.0.0:8000`. `curl` may return non-200 (MCP endpoint expects MCP handshake) — that's OK, server is up.

- [ ] **Step 5: Decide go/no-go**

- All checks green → STOP and report to user; await go-ahead for Phase E (PyPI publish is irreversible).
- Any failure → file follow-up issue, decide whether to cut rc.2 with the fix or accept and proceed to stable.

---

## Phase E — Release pipeline validation 3b (`v1.6.0` stable)

### Task E1: Trigger stable release workflow

- [ ] **Step 1: Confirm rc smoke was green** (Task D2 fully complete).

- [ ] **Step 2: Trigger stable release with NO `force` flag**

```bash
cd /mnt/code/image-gen-mcp
gh workflow run release.yml -f prerelease=false
sleep 5
RUN_ID=$(gh run list --workflow release.yml --limit 1 --json databaseId -q '.[0].databaseId')
echo "Run: $RUN_ID"
gh run watch "$RUN_ID"
```

**Critical: do NOT pass `force=minor` here.** The rc is already at the target version — passing `force=minor` causes PSR to bump again from 1.6.0-rc.1 → 1.7.0, skipping 1.6.0 entirely (per `feedback_psr_promote_rc_no_force.md` lesson learned during MV Step 4 → cut v1.27.0 instead of v1.26.0). Letting PSR auto-detect will drop the rc suffix to land on 1.6.0.

Expected: all 8 publish jobs succeed (release, build-mcpb, publish-docker, publish-pypi, publish-linux-packages, publish-claude-plugin-pr, publish-mcpb, publish-registry).

### Task E2: Verify all six publish targets

- [ ] **Step 1: PyPI**

```bash
curl -sS https://pypi.org/pypi/image-generation-mcp/json | jq -r '.info.version'
```

Expected: `1.6.0`.

- [ ] **Step 2: GHCR multi-arch**

```bash
docker manifest inspect ghcr.io/pvliesdonk/image-generation-mcp:v1.6.0 \
  | jq -c '.manifests[].platform' | head -5
```

Expected: `{"architecture":"amd64",...}` and `{"architecture":"arm64",...}`.

- [ ] **Step 3: MCP Registry**

```bash
curl -sS "https://registry.modelcontextprotocol.io/v0/servers?search=image-generation-mcp" \
  | jq '.servers[] | .server | select(.name=="io.github.pvliesdonk/image-generation-mcp") | .version'
```

Expected: list including `"1.6.0"`.

- [ ] **Step 4: Linux packages**

```bash
gh release view v1.6.0 --json assets -q '.assets[].name' | grep -E '\.(deb|rpm)$'
```

Expected: at least one `.deb` and one `.rpm` (architecture-tagged).

- [ ] **Step 5: GitHub release**

```bash
gh release view v1.6.0 --json tagName,isPrerelease,assets \
  -q '{tag: .tagName, isPrerelease, asset_count: (.assets | length), assets: [.assets[].name]}'
```

Expected: `tag: v1.6.0`, `isPrerelease: false`, ≥6 assets.

- [ ] **Step 6: MCPB**

```bash
gh release view v1.6.0 --json assets -q '.assets[].name' | grep -i '\.mcpb$'
```

Expected: one `.mcpb` asset.

---

## Phase F — Closeout

### Task F1: Update fastmcp-pvl-core extraction handoff memory

**Files:**
- Modify: `/home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/fastmcp_pvl_core_extraction_handoff.md`

- [ ] **Step 1: Read current handoff memory**

```bash
cat /home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/fastmcp_pvl_core_extraction_handoff.md
```

- [ ] **Step 2: Mark Step 5 DONE**

In the "Remaining work" section, replace the existing Step 5 placeholder line with:

```markdown
- **Step 5 — DONE 2026-04-21.** IG retrofitted onto fastmcp-server-template v1.0.0 AND fastmcp-pvl-core in a single rebuild PR (chore/adopt-fastmcp-template). 533-line `mcp_server.py` → ~150-line `make_server()` composing core. `ServerConfig` renamed to `ProjectConfig` to avoid clash with core's `ServerConfig`. ResourcesAsTools, long-op keepalives, HTTP_PATH, transform-on-fetch artifacts.py kept in IG domain layer per design. **v1.6.0 stable** shipped to all six targets. Triage archived at `docs/superpowers/notes/2026-04-21-step5-replay-triage.md` in IG repo. Spec: `docs/superpowers/specs/2026-04-21-step5-ig-retrofit-design.md` in MV repo.
```

Apply via `Edit` tool.

- [ ] **Step 3: Update MEMORY.md index line**

Find this line in `/home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/MEMORY.md`:

```markdown
- [fastmcp-pvl-core Extraction Handoff](fastmcp_pvl_core_extraction_handoff.md) — Steps 1-4 **DONE** ...
```

Replace with:

```markdown
- [fastmcp-pvl-core Extraction Handoff](fastmcp_pvl_core_extraction_handoff.md) — Steps 1-5 **DONE** 2026-04-21 (core v1.0.0 + template v1.0.0 + MV v1.27.0 + IG v1.6.0). Steps 6-8 (scholar/kroki copier-retrofit + SYNC.md retire) remain.
```

- [ ] **Step 4: Verify size budget**

```bash
wc -c /home/peter/.claude/projects/-mnt-code-markdown-mcp/memory/MEMORY.md
```

Expected: < 25000 bytes. If over, prune older PR entries per Step 4 Phase F precedent.

### Task F2: Confirm Step 5 success criteria

- [ ] **Step 1: Walk the spec's Success criteria**

For each of the 8 criteria in `docs/superpowers/specs/2026-04-21-step5-ig-retrofit-design.md` §"Success criteria":

1. Replay diff Class A/C/E only — check triage log Phase 1 outcome.
2. `.copier-answers.yml` pinned, on main — `git -C /mnt/code/image-gen-mcp log --all -- .copier-answers.yml`.
3. Gate green on retrofit commit — CI run on retrofit PR.
4. fastmcp-pvl-core used in make_server() — Task C17 grep audit.
5. mcp_server.py ≤ ~200 lines — `wc -l`.
6. rc.1 smoke passed — Task D2.
7. Stable v1.6.0 on all six targets — Task E2.
8. Memory updated — Task F1.

- [ ] **Step 2: Announce Step 5 complete**

Post a one-line summary describing IG v1.6.0 release and naming Step 6 (scholar-mcp).

---

## Notes on iteration

The big risk areas are Tasks C5 (config.py rewrite), C7 (mcp_server.py rewrite), and C16 (gate). Expect 2–4 iterations of C16 before all green.

If C7 reveals that IG's `_server_tools.py` / `_server_resources.py` / `_server_prompts.py` import something the rewritten `mcp_server.py` no longer exports (e.g., a helper that was at module scope before), surface it — that's a Class C boundary mistake; fix by either (a) re-adding the helper to mcp_server.py, or (b) moving the helper to a new domain module.

If C16 reveals tests that depend on the old `_build_*_auth` helpers (likely some `tests/test_config.py` or `tests/test_mcp_server.py`), update those tests to construct `ProjectConfig(server=ServerConfig(bearer_token=..., oidc_*=...))` directly and call `build_auth(config.server)` from `fastmcp_pvl_core`. The same tests for MV in PR #396 are a reference template.

## Cross-cutting

- **Do NOT use `--admin` on `gh pr merge`.**
- **Do NOT use `force=minor` on the stable promotion in Task E1** — the lesson from Step 4 v1.27.0.
- **Do not delete `_vendored_sdk.py`** — it's domain (vendored partial of an SDK IG depends on for backward compat).
- **Asset pipeline (`node_modules/`, `package.json`, `package-lock.json`, `site/`) must survive the retrofit** — verify in Task B2 / C1 inspection. If copier somehow touches them, restore aggressively from `step5-pre-retrofit`.
