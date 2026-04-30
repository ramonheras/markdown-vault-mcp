"""Tests for DocumentManager.read(path, section=...) section retrieval."""

from __future__ import annotations

import threading

import pytest

from markdown_vault_mcp.fts_index import FTSIndex
from markdown_vault_mcp.managers.document import DocumentManager
from markdown_vault_mcp.scanner import HeadingChunker, scan_directory


@pytest.fixture()
def doc_mgr(tmp_path):
    a = tmp_path / "a.md"
    # Use multi-line bodies so the doc clears the 30-line short-doc bypass and
    # actually splits into per-section chunks.
    body = (
        "# A\n"
        + "\n".join(["intro"] * 12)
        + "\n## Section One\n"
        + "\n".join(["first body word"] * 12)
        + "\n## Section Two\n"
        + "\n".join(["second body word"] * 12)
        + "\n"
    )
    a.write_text(body, encoding="utf-8")
    fts = FTSIndex(db_path=":memory:")
    chunker = HeadingChunker()
    for note in scan_directory(tmp_path, chunk_strategy=chunker):
        fts.upsert_note(note)
    return DocumentManager(
        fts=fts,
        source_dir=tmp_path,
        write_lock=threading.RLock(),
        chunk_strategy=chunker,
        read_only=False,
    )


def test_read_no_section_returns_full_file(doc_mgr):
    nc = doc_mgr.read("a.md")
    assert nc is not None
    assert "Section One" in nc.content
    assert "Section Two" in nc.content


def test_read_with_section_returns_only_that_chunk(doc_mgr):
    nc = doc_mgr.read("a.md", section="Section One")
    assert nc is not None
    assert "first body word" in nc.content
    assert "second body word" not in nc.content


def test_read_unknown_section_raises(doc_mgr):
    with pytest.raises(ValueError, match="Section"):
        doc_mgr.read("a.md", section="No Such Heading")


def test_read_empty_section_raises(doc_mgr):
    with pytest.raises(ValueError):
        doc_mgr.read("a.md", section="   ")


def test_read_returns_none_when_path_unknown(doc_mgr):
    assert doc_mgr.read("missing.md") is None
    # With section, missing path also raises (cannot resolve section in
    # nonexistent doc).
    with pytest.raises(ValueError):
        doc_mgr.read("missing.md", section="Anything")
