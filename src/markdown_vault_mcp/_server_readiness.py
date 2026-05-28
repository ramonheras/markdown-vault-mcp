"""MCP-layer `needs_index_ready` decorator (#513 PR1).

Boundary: the library raises ``IndexNotReadyError`` immediately on
not-ready (PR #525 contract). Blocking semantics live here at the MCP
layer, where the caller's intent — "an MCP client is waiting and
wants to wait" — is unambiguous. Internal callers (lifespan, git
pull loop, CLI, direct library users) do NOT go through this
decorator; they handle "not ready" with their own caller-appropriate
logic (skip, log, retry on next interval).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _resolve_ready_timeout() -> float:
    """Read env var at call time so tests can monkeypatch.setenv it."""
    return float(os.environ.get("MARKDOWN_VAULT_MCP_READY_TIMEOUT_S", "60"))


def needs_index_ready(
    timeout: float | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for bucket-3/4 MCP tool and resource handlers.

    Before invoking the wrapped handler, blocks on
    ``Collection.wait_for_index_ready(timeout)``. On the warm path
    (``is_index_ready`` already True) the wait is skipped — no
    thread-pool overhead.

    The wrapper does NOT redeclare ``collection`` in its own
    signature. ``functools.wraps`` preserves the wrapped handler's
    signature so FastMCP's introspection sees the original
    ``collection: Collection = Depends(get_collection)`` parameter
    and injects it via kwargs. The wrapper reads ``collection`` from
    kwargs and passes args/kwargs through unchanged.

    Stacking order: place ``@needs_index_ready(...)`` BELOW
    ``@mcp.tool(...)`` (or ``@mcp.resource(...)``) — that is,
    closer to ``def``. Python applies decorators bottom-up, so
    ``@needs_index_ready`` wraps the handler first; then
    ``@mcp.tool`` runs on the result and FastMCP registers the
    already-wrapped function.

    Raises (propagated to MCP client via FastMCP error middleware):
        IndexNotReadyError: timeout exceeded; or never scheduled.
        IndexBuildFailedError: a prior background build raised.
    """

    def deco(handler: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(handler)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            collection = kwargs.get("collection")
            if collection is None:
                raise RuntimeError(
                    "needs_index_ready: collection was not injected; "
                    "handler must declare "
                    "`collection: Collection = Depends(get_collection)`."
                )
            if not collection.is_index_ready():
                effective = timeout if timeout is not None else _resolve_ready_timeout()
                await asyncio.to_thread(collection.wait_for_index_ready, effective)
            return await handler(*args, **kwargs)

        return wrapper

    return deco
