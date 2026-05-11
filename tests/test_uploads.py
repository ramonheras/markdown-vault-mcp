"""Tests for the MV-side file-exchange upload receiver.

Covers :mod:`markdown_vault_mcp.uploads`, which provides the callables
passed to pvl-core's ``register_file_exchange_upload(receiver=..., pre_link_validator=...)``.
The receiver dispatches by extension to ``Collection.write`` (for
``.md`` paths) or ``Collection.write_attachment`` (for binaries).  The
pre-link validator rejects bad ``target_id``s at link-creation time so
the agent gets ``ValueError`` in-band instead of after a wasted HTTP POST.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
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


class TestValidateUploadTarget:
    """``_validate_upload_target`` rejects bad paths at link-creation time."""

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """A ``..``-bearing target_id raises ``ValueError`` defensively.

        pvl-core's ``ExchangeURI.validate_segment`` would already block
        this upstream, but the validator must defend in depth in case the
        pre-link validator ever runs against an unvalidated source.
        """
        col = Collection(source_dir=tmp_path, read_only=False)
        col.build_index()
        saved = _server_deps._collection_singleton
        _server_deps.set_collection_singleton(col)
        try:
            with pytest.raises(ValueError):
                uploads._validate_upload_target("../etc/passwd", None)
        finally:
            col.close()
            _server_deps._collection_singleton = saved

    def test_disallowed_extension_rejected(self, tmp_path: Path) -> None:
        """An attachment whose extension is not in the allowlist is rejected."""
        col = Collection(
            source_dir=tmp_path,
            read_only=False,
            attachment_extensions=["pdf"],
        )
        col.build_index()
        saved = _server_deps._collection_singleton
        _server_deps.set_collection_singleton(col)
        try:
            with pytest.raises(ValueError):
                uploads._validate_upload_target("malware.exe", None)
        finally:
            col.close()
            _server_deps._collection_singleton = saved

    def test_md_path_accepted(self, tmp_path: Path) -> None:
        """A bare ``.md`` filename passes validation without raising."""
        col = Collection(source_dir=tmp_path, read_only=False)
        col.build_index()
        saved = _server_deps._collection_singleton
        _server_deps.set_collection_singleton(col)
        try:
            uploads._validate_upload_target("note.md", None)
        finally:
            col.close()
            _server_deps._collection_singleton = saved

    def test_allowed_attachment_accepted(self, tmp_path: Path) -> None:
        """An attachment whose extension is in the allowlist passes validation."""
        col = Collection(
            source_dir=tmp_path,
            read_only=False,
            attachment_extensions=["pdf"],
        )
        col.build_index()
        saved = _server_deps._collection_singleton
        _server_deps.set_collection_singleton(col)
        try:
            uploads._validate_upload_target("file.pdf", None)
        finally:
            col.close()
            _server_deps._collection_singleton = saved
