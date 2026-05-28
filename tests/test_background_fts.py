"""Tests for issue #513 PR1 (attempt 7) — tool-layer wait for cold-start background FTS."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest

from markdown_vault_mcp.collection import Collection
from markdown_vault_mcp.exceptions import (
    IndexBuildFailedError,
    IndexNotReadyError,
    MarkdownMCPError,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_index_build_failed_error_subclasses_base() -> None:
    err = IndexBuildFailedError("scan failed")
    assert isinstance(err, MarkdownMCPError)
    assert str(err) == "scan failed"


def test_index_build_failed_error_carries_cause() -> None:
    original = RuntimeError("scan exploded")
    try:
        raise IndexBuildFailedError("background build failed") from original
    except IndexBuildFailedError as err:
        assert err.__cause__ is original


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


def _seed(vault: Path, name: str = "n.md", body: str = "# N\n\nbody\n") -> None:
    (vault / name).write_text(body, encoding="utf-8")


def test_is_index_ready_false_after_construction(tmp_path: Path) -> None:
    col = Collection(source_dir=_vault(tmp_path))
    assert col.is_index_ready() is False
    col.close()


def test_is_index_ready_true_after_synchronous_build(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _seed(vault)
    col = Collection(source_dir=vault)
    col.build_index()
    assert col.is_index_ready() is True
    col.close()


def test_is_index_ready_false_after_captured_background_error(tmp_path: Path) -> None:
    """Direct state poke: simulate a finished-but-failed background by setting
    the error and the event, leaving _index_built False."""
    col = Collection(source_dir=_vault(tmp_path))
    col._background_build_error = RuntimeError("simulated")
    col._background_build_done.set()
    assert col.is_index_ready() is False
    col.close()


def test_wait_for_index_ready_returns_when_already_built(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _seed(vault)
    col = Collection(source_dir=vault)
    col.build_index()
    col.wait_for_index_ready(timeout=0.1)  # must not raise
    col.close()


def test_wait_for_index_ready_blocks_until_event_set(tmp_path: Path) -> None:
    col = Collection(source_dir=_vault(tmp_path))
    col._background_build_done.clear()
    col._index_built = False

    def setter() -> None:
        time.sleep(0.05)
        col._index_built = True
        col._background_build_done.set()

    threading.Thread(target=setter).start()
    col.wait_for_index_ready(timeout=1.0)  # returns when event fires
    col.close()


def test_wait_for_index_ready_raises_on_timeout(tmp_path: Path) -> None:
    col = Collection(source_dir=_vault(tmp_path))
    col._background_build_done.clear()
    col._index_built = False
    with pytest.raises(IndexNotReadyError, match=r"timed out"):
        col.wait_for_index_ready(timeout=0.05)
    col.close()


def test_wait_for_index_ready_raises_build_failed_when_error_set(
    tmp_path: Path,
) -> None:
    col = Collection(source_dir=_vault(tmp_path))
    col._background_build_error = RuntimeError("scan exploded")
    with pytest.raises(IndexBuildFailedError) as excinfo:
        col.wait_for_index_ready(timeout=0.1)
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    col.close()


def test_wait_for_index_ready_raises_when_never_scheduled(tmp_path: Path) -> None:
    """Pre-set event + no error + _index_built=False + _background_started=False.
    This is the case the spec calls 'never scheduled' — the pre-set event would
    let wait() return success without the explicit guard."""
    col = Collection(source_dir=_vault(tmp_path))
    # All defaults: event pre-set, no error, _index_built=False, no spawn.
    with pytest.raises(IndexNotReadyError, match=r"never scheduled|not built"):
        col.wait_for_index_ready(timeout=0.1)
    col.close()


def test_start_background_build_index_eventually_ready(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    for i in range(5):
        _seed(vault, f"n_{i}.md", f"# N{i}\n\nbody {i}\n")
    col = Collection(source_dir=vault)
    col.start_background_build_index()
    col.wait_for_index_ready(timeout=5.0)
    assert col.is_index_ready()
    col.get_backlinks("n_0.md")  # smoke: bucket-3 returns (empty list OK)
    col.close()


def test_start_background_build_index_captures_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    col = Collection(source_dir=_vault(tmp_path))

    def boom(*_a: object, **_kw: object) -> None:
        raise RuntimeError("simulated scan failure")

    monkeypatch.setattr(col._index_mgr, "build_index", boom)
    col.start_background_build_index()

    with pytest.raises(IndexBuildFailedError):
        col.wait_for_index_ready(timeout=5.0)
    assert col.is_index_ready() is False
    col.close()


def test_start_background_build_index_idempotent(tmp_path: Path) -> None:
    col = Collection(source_dir=_vault(tmp_path))
    col.start_background_build_index()
    first = col._background_build_thread
    assert first is not None
    col.start_background_build_index()
    assert col._background_build_thread is first
    col.wait_for_index_ready(timeout=5.0)
    col.start_background_build_index()
    assert col._background_build_thread is first
    col.close()


def test_start_background_build_index_one_shot_after_thread_start_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If thread.start() itself raises, the captured-error path runs
    synchronously: event set, error recorded, _background_started True.
    A retry call is a no-op (one-shot)."""
    col = Collection(source_dir=_vault(tmp_path))

    def boom_start(_self: threading.Thread) -> None:
        raise RuntimeError("system thread exhaustion (simulated)")

    monkeypatch.setattr(threading.Thread, "start", boom_start)

    with pytest.raises(RuntimeError, match=r"thread exhaustion"):
        col.start_background_build_index()

    # Event must be set; error recorded.
    assert col._background_build_done.is_set()
    assert isinstance(col._background_build_error, RuntimeError)

    # wait_for_index_ready surfaces it as IndexBuildFailedError.
    with pytest.raises(IndexBuildFailedError):
        col.wait_for_index_ready(timeout=0.1)

    # Retry is a no-op (one-shot semantics).
    monkeypatch.undo()
    col.start_background_build_index()  # no-op; does NOT spawn a new thread
    col.close()


def test_should_use_background_build_in_memory_false(tmp_path: Path) -> None:
    col = Collection(source_dir=_vault(tmp_path))  # no index_path → in-memory
    assert col.should_use_background_build() is False
    col.close()


def test_should_use_background_build_cold_on_disk_true(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _seed(vault)
    col = Collection(source_dir=vault, index_path=tmp_path / "fts.db")
    # No prior build → sentinel absent → background build required.
    assert col.should_use_background_build() is True
    col.close()


def test_should_use_background_build_warm_on_disk_false(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _seed(vault)
    index_path = tmp_path / "fts.db"
    # Phase 1: pre-build sets the sentinel.
    pre = Collection(source_dir=vault, index_path=index_path)
    pre.build_index()
    pre.close()
    # Phase 2: fresh Collection sees the warm sentinel.
    col = Collection(source_dir=vault, index_path=index_path)
    assert col.should_use_background_build() is False
    col.close()
