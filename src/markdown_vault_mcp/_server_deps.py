"""Shared dependency injection and lifespan for the MCP server.

Provides :func:`get_collection` and :data:`_collection_lifespan` which are
imported by the tool, resource, and prompt registration modules.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context
from fastmcp.server.lifespan import lifespan

from markdown_vault_mcp.collection import Collection
from markdown_vault_mcp.config import load_config

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


@lifespan
async def _collection_lifespan(
    server: FastMCP,  # noqa: ARG001
) -> AsyncIterator[dict[str, Any]]:
    """Build the Collection at server startup, tear down on shutdown."""
    config = load_config()
    logger.info("Initialising collection from %s", config.source_dir)

    # Resolve embedding provider if embeddings_path is configured.
    embedding_provider = None
    if config.embeddings_path is not None:
        try:
            from markdown_vault_mcp.providers import get_embedding_provider

            embedding_provider = get_embedding_provider()
            logger.info("Embedding provider: %s", type(embedding_provider).__name__)
        except Exception:
            logger.warning(
                "Could not load embedding provider; semantic search disabled",
                exc_info=True,
            )

    kwargs = config.to_collection_kwargs()
    if embedding_provider is not None:
        kwargs["embedding_provider"] = embedding_provider
    collection = Collection(**kwargs)

    # If periodic git pull is enabled, sync before building the initial index so
    # build_index() scans the freshest working tree.
    await asyncio.to_thread(collection.sync_from_remote_before_index)

    # Build index eagerly so first tool call is fast.
    stats = await asyncio.to_thread(collection.build_index)
    logger.info(
        "Index built: %d documents, %d chunks",
        stats.documents_indexed,
        stats.chunks_indexed,
    )

    # Build embeddings eagerly when an embedding provider is configured.
    # build_embeddings() skips work if the vector index already exists on disk,
    # so this is safe to call on every startup.
    if embedding_provider is not None:
        chunks_embedded = await asyncio.to_thread(collection.build_embeddings)
        logger.info("Embeddings ready: %d chunks", chunks_embedded)

    # Start background tasks (e.g. git pull loop) after index is built.
    collection.start()

    try:
        yield {"collection": collection, "config": config}
    finally:
        collection.close()
        logger.info("Collection shut down")


def get_collection(ctx: Context = CurrentContext()) -> Collection:
    """Resolve the Collection from lifespan context.

    Used as a ``Depends()`` default in tool/resource/prompt signatures.

    Raises:
        RuntimeError: If the server lifespan has not run.
    """
    collection: Collection | None = ctx.lifespan_context.get("collection")
    if collection is None:
        msg = "Collection not initialised — server lifespan has not run"
        raise RuntimeError(msg)
    return collection
