"""Tests for the MV-side file-exchange upload receiver.

Covers :mod:`markdown_vault_mcp.uploads`, which provides the callable
passed to pvl-core's ``register_file_exchange_upload(receiver=...)``.
The receiver dispatches by extension to ``Collection.write`` (for
``.md`` paths) or ``Collection.write_attachment`` (for binaries).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp_pvl_core import UploadRecord

from markdown_vault_mcp import _server_deps, uploads
from markdown_vault_mcp.collection import Collection

if TYPE_CHECKING:
    from pathlib import Path


def _make_record(target_id: str) -> UploadRecord:
    """Build an UploadRecord with arbitrary-but-valid runtime guards.

    The receiver only consumes ``target_id`` — ``max_bytes`` and
    ``expires_at`` are enforced by the HTTP route before dispatch.
    """
    return UploadRecord(
        target_id=target_id,
        max_bytes=1024 * 1024,
        extra={},
        expires_at=1e12,
    )


class TestVaultUploadReceiver:
    """``_vault_upload_receiver`` dispatches by extension to write or write_attachment."""

    def test_md_path_dispatches_to_write(self, tmp_path: Path) -> None:
        """A ``.md`` target is decoded as utf-8 and committed via ``Collection.write``."""
        col = Collection(source_dir=tmp_path, read_only=False)
        col.build_index()
        saved = _server_deps._collection_singleton
        _server_deps.set_collection_singleton(col)
        try:
            payload = b"# Note\n\nbody\n"
            record = _make_record("note.md")
            result = uploads._vault_upload_receiver(record, payload)
            assert result == {"path": "note.md", "size_bytes": len(payload)}
            assert (tmp_path / "note.md").read_text() == "# Note\n\nbody\n"
        finally:
            col.close()
            _server_deps._collection_singleton = saved

    def test_binary_path_dispatches_to_write_attachment(self, tmp_path: Path) -> None:
        """A non-``.md`` target is committed verbatim via ``Collection.write_attachment``."""
        col = Collection(
            source_dir=tmp_path,
            read_only=False,
            attachment_extensions=["pdf"],
        )
        col.build_index()
        saved = _server_deps._collection_singleton
        _server_deps.set_collection_singleton(col)
        try:
            payload = b"%PDF-1.4 fake bytes \x00\x01\x02"
            record = _make_record("doc.pdf")
            result = uploads._vault_upload_receiver(record, payload)
            assert result == {"path": "doc.pdf", "size_bytes": len(payload)}
            assert (tmp_path / "doc.pdf").read_bytes() == payload
        finally:
            col.close()
            _server_deps._collection_singleton = saved
