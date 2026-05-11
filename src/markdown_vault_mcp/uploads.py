"""MV-side wiring for fastmcp-pvl-core's file-exchange upload helper.

Provides the ``receiver`` callable passed to
:func:`fastmcp_pvl_core.register_file_exchange_upload` in
:mod:`markdown_vault_mcp.server`.  The receiver commits uploaded
bytes to the vault via the existing :class:`~markdown_vault_mcp.collection.Collection`
write APIs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from markdown_vault_mcp._server_deps import get_collection_singleton

if TYPE_CHECKING:
    from fastmcp_pvl_core import UploadRecord


def _vault_upload_receiver(record: UploadRecord, body: bytes) -> dict[str, Any]:
    """Commit uploaded bytes to the vault.

    Dispatches to :meth:`~markdown_vault_mcp.collection.Collection.write`
    for ``.md`` filenames or
    :meth:`~markdown_vault_mcp.collection.Collection.write_attachment`
    for binaries based on the ``target_id``'s extension.  pvl-core's
    ``ExchangeURI.validate_segment`` already enforces that ``target_id``
    is a single safe filename (no slashes, no ``..``, no control bytes),
    and the MV-side pre-link validator runs additional checks at link
    creation time, so this function trusts the value.

    Args:
        record: pvl-core's :class:`~fastmcp_pvl_core.UploadRecord` —
            ``target_id`` is the vault-relative filename the agent passed
            to ``create_upload_link``.
        body: Raw bytes streamed from the POST request, already validated
            against ``record.max_bytes`` by the HTTP route.

    Returns:
        Dict serialised as the HTTP 200 response body.  Conventional keys:
        ``path``, ``size_bytes``.
    """
    collection = get_collection_singleton()
    if record.target_id.endswith(".md"):
        collection.write(record.target_id, content=body.decode("utf-8"))
    else:
        collection.write_attachment(record.target_id, body)
    return {"path": record.target_id, "size_bytes": len(body)}
