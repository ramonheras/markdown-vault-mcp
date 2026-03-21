"""One-time artifact download endpoint for inter-MCP file transfer.

Implements an in-memory token store and a Starlette route handler that
serves vault file bytes once and then invalidates the token.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request

    from markdown_vault_mcp.collection import Collection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token store
# ---------------------------------------------------------------------------


@dataclass
class TokenRecord:
    """A one-time download token record.

    Attributes:
        path: The vault-relative path this token grants access to.
        created_at: Unix timestamp of when the token was created.
        ttl_seconds: Time-to-live in seconds.
    """

    path: str
    created_at: float
    ttl_seconds: int


class ArtifactStore:
    """In-memory one-time token store for artifact downloads.

    Tokens are UUIDs (hex) that grant a single download of a vault file.
    Expired tokens are cleaned up lazily on each operation.

    Note:
        The store is in-memory only — tokens do not survive a server
        restart.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, TokenRecord] = {}

    def create_token(self, path: str, ttl_seconds: int = 300) -> str:
        """Create a one-time download token.

        Args:
            path: The vault-relative path to grant access to.
            ttl_seconds: Token lifetime in seconds (default 300).

        Returns:
            A hex UUID token string.
        """
        self._cleanup_expired()
        token = uuid.uuid4().hex
        self._tokens[token] = TokenRecord(
            path=path,
            created_at=time.time(),
            ttl_seconds=ttl_seconds,
        )
        logger.debug("Created artifact token for path=%r ttl=%ds", path, ttl_seconds)
        return token

    def consume_token(self, token: str) -> TokenRecord | None:
        """Consume a token, returning the record or None if invalid/expired.

        The token is always removed from the store (one-time use), even
        if it has expired.

        Args:
            token: The hex UUID token string.

        Returns:
            The :class:`TokenRecord`, or ``None`` if unknown or expired.
        """
        record = self._tokens.pop(token, None)
        if record is None:
            return None
        if time.time() - record.created_at > record.ttl_seconds:
            logger.debug("Artifact token expired: %s", token)
            return None
        return record

    def _cleanup_expired(self) -> None:
        """Remove expired tokens (lazy cleanup on each operation)."""
        now = time.time()
        expired = [
            k for k, v in self._tokens.items() if now - v.created_at > v.ttl_seconds
        ]
        for k in expired:
            del self._tokens[k]
        if expired:
            logger.debug("Cleaned up %d expired artifact token(s)", len(expired))


# ---------------------------------------------------------------------------
# Module-level store singleton (set by lifespan)
# ---------------------------------------------------------------------------

_artifact_store: ArtifactStore | None = None


def set_artifact_store(store: ArtifactStore | None) -> None:
    """Set the module-level artifact store (called from lifespan).

    Args:
        store: The :class:`ArtifactStore` instance, or ``None`` on shutdown.
    """
    global _artifact_store
    _artifact_store = store


def get_artifact_store() -> ArtifactStore:
    """Return the module-level artifact store.

    Returns:
        The active :class:`ArtifactStore`.

    Raises:
        RuntimeError: If the store has not been initialised via lifespan.
    """
    if _artifact_store is None:
        msg = "ArtifactStore not initialised — server lifespan has not run"
        raise RuntimeError(msg)
    return _artifact_store


# ---------------------------------------------------------------------------
# Module-level collection accessor (set by lifespan)
# ---------------------------------------------------------------------------

_collection_store: Collection | None = None


def set_collection_store(collection: Collection | None) -> None:
    """Set the module-level collection reference (called from lifespan).

    The artifact HTTP handler runs outside FastMCP's request-context
    dependency injection, so it needs a module-level accessor.

    Args:
        collection: The :class:`~markdown_vault_mcp.collection.Collection`
            instance, or ``None`` on shutdown.
    """
    global _collection_store
    _collection_store = collection


def _get_collection_from_store() -> Collection:
    """Return the module-level Collection reference.

    Used by the artifact HTTP handler, which runs outside FastMCP's
    request-context dependency injection.

    Returns:
        The active :class:`~markdown_vault_mcp.collection.Collection`.

    Raises:
        RuntimeError: If the server lifespan has not yet run.
    """
    if _collection_store is None:
        msg = "Collection not initialised — server lifespan has not run"
        raise RuntimeError(msg)
    return _collection_store


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


def make_artifact_handler() -> Callable[[Request], Awaitable[Response]]:
    """Build the Starlette route handler for ``GET /artifacts/{token}``.

    The returned handler accesses the :class:`Collection` via the
    module-level store, which is populated during server lifespan.

    Returns:
        An async Starlette request handler.
    """

    async def artifact_handler(request: Request) -> Response:
        """Serve a one-time file download and invalidate the token.

        Args:
            request: Starlette request with ``token`` path param.

        Returns:
            File bytes response with correct ``Content-Type``, or HTTP 404.
        """
        token = request.path_params.get("token", "")
        store = get_artifact_store()
        record = store.consume_token(token)

        if record is None:
            logger.debug("Artifact token not found or expired: %s", token)
            return Response(content="Not Found", status_code=404)

        collection = _get_collection_from_store()
        vault_path = record.path

        try:
            # Read the file bytes directly from disk via the collection's
            # source directory, after validation.
            if vault_path.endswith(".md"):
                abs_path = await asyncio.to_thread(
                    collection._validate_path, vault_path
                )
                content_type = "text/markdown; charset=utf-8"
            else:
                abs_path = await asyncio.to_thread(
                    collection._validate_attachment_path, vault_path
                )
                mime, _ = mimetypes.guess_type(vault_path)
                content_type = mime or "application/octet-stream"
        except ValueError:
            logger.warning("Artifact: path validation failed for %r", vault_path)
            return Response(content="Not Found", status_code=404)

        try:
            data = await asyncio.to_thread(abs_path.read_bytes)
        except OSError:
            logger.warning(
                "Artifact: file missing for path=%r abs=%s",
                vault_path,
                abs_path,
            )
            return Response(content="Not Found", status_code=404)

        logger.info(
            "Artifact served: token=%s path=%r content_type=%s size=%d",
            token,
            vault_path,
            content_type,
            len(data),
        )
        filename = vault_path.rsplit("/", 1)[-1]
        return Response(
            content=data,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return artifact_handler
