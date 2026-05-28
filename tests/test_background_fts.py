"""Tests for issue #513 PR1 (attempt 7) — tool-layer wait for cold-start background FTS."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from fastmcp import Client

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


# ---------------------------------------------------------------------------
# get_index_status tests
# ---------------------------------------------------------------------------


def test_get_index_status_ready(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _seed(vault)
    col = Collection(source_dir=vault)
    col.build_index()
    status = col.get_index_status()
    assert status["status"] == "ready"
    assert status["documents_indexed"] == 1
    assert status["error"] is None
    col.close()


def test_get_index_status_building_in_flight(tmp_path: Path) -> None:
    col = Collection(source_dir=_vault(tmp_path))
    col._background_build_done.clear()
    col._background_started = True
    status = col.get_index_status()
    assert status["status"] == "building"
    assert status["error"] is None
    col._background_build_done.set()
    col.close()


def test_get_index_status_building_never_started(tmp_path: Path) -> None:
    """Fresh Collection: event pre-set, no error, _index_built=False.
    Reports 'building' (not 'ready' — the attempt-6 lie is fixed)."""
    col = Collection(source_dir=_vault(tmp_path))
    status = col.get_index_status()
    assert status["status"] == "building"
    assert status["error"] is None
    col.close()


def test_get_index_status_failed(tmp_path: Path) -> None:
    col = Collection(source_dir=_vault(tmp_path))
    col._background_build_error = RuntimeError("scan failed for X")
    status = col.get_index_status()
    assert status["status"] == "failed"
    assert "scan failed for X" in status["error"]
    col.close()


# ---------------------------------------------------------------------------
# MCP integration test for get_index_status
# ---------------------------------------------------------------------------


def test_mcp_tool_get_index_status_reports_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "n.md").write_text("# N\n\nbody\n", encoding="utf-8")
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_INDEX_PATH", str(tmp_path / "fts.db"))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_STATE_PATH", str(tmp_path / "s.json"))

    from markdown_vault_mcp.server import make_server

    server = make_server()

    async def _call() -> dict[str, Any]:
        async with Client(server) as client:
            res = await client.call_tool("get_index_status", {})
            return res.structured_content or {}

    status = asyncio.run(_call())
    assert status["status"] in ("ready", "building")  # depends on lifespan timing
    assert status["error"] is None


# ---------------------------------------------------------------------------
# close() joins background thread (Task 7)
# ---------------------------------------------------------------------------


def test_close_joins_background_thread(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    for i in range(3):
        _seed(vault, f"n_{i}.md", f"# N{i}\n\nbody {i}\n")
    col = Collection(source_dir=vault, index_path=tmp_path / "fts.db")
    col.start_background_build_index()
    col.close()
    thread = col._background_build_thread
    assert thread is not None
    assert not thread.is_alive()


def test_close_before_start_is_safe(tmp_path: Path) -> None:
    """A Collection that never had a background build can still close cleanly."""
    col = Collection(source_dir=_vault(tmp_path))
    col.close()  # must not raise


def test_close_twice_is_safe(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _seed(vault)
    col = Collection(source_dir=vault)
    col.build_index()
    col.close()
    col.close()  # idempotent


# ---------------------------------------------------------------------------
# Task 8: Lifespan rewire tests
# ---------------------------------------------------------------------------


def test_lifespan_cold_start_handshake_under_1s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time as time_mod

    from markdown_vault_mcp.server import make_server

    vault = tmp_path / "vault"
    vault.mkdir()
    for i in range(20):
        (vault / f"n_{i}.md").write_text(
            f"# N{i}\n\n" + ("body " * 200) + "\n", encoding="utf-8"
        )

    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_INDEX_PATH", str(tmp_path / "fts.db"))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_STATE_PATH", str(tmp_path / "s.json"))

    server = make_server()

    async def _run() -> tuple[float, dict[str, Any]]:
        start = time_mod.perf_counter()
        async with Client(server) as client:
            handshake_elapsed = time_mod.perf_counter() - start
            res: Any = None
            for _ in range(50):
                res = await client.call_tool("get_index_status", {})
                if (res.structured_content or {}).get("status") == "ready":
                    break
                await asyncio.sleep(0.1)
            final = res.structured_content or {}
        return handshake_elapsed, final

    handshake_elapsed, final = asyncio.run(_run())
    assert handshake_elapsed < 1.0, (
        f"cold-start handshake took {handshake_elapsed:.3f}s, expected < 1.0s"
    )
    assert final["status"] == "ready"
    assert final["documents_indexed"] == 20


def test_lifespan_warm_start_skips_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from markdown_vault_mcp.server import make_server

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "n.md").write_text("# N\n\nbody\n", encoding="utf-8")
    index_path = tmp_path / "fts.db"

    pre = Collection(source_dir=vault, index_path=index_path)
    pre.build_index()
    pre.close()

    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_INDEX_PATH", str(index_path))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_STATE_PATH", str(tmp_path / "s.json"))

    server = make_server()

    async def _run() -> dict[str, Any]:
        async with Client(server) as client:
            res = await client.call_tool("get_index_status", {})
            return res.structured_content or {}

    status = asyncio.run(_run())
    assert status["status"] == "ready"
    assert status["documents_indexed"] == 1


def test_lifespan_cold_start_with_embeddings_skips_embeddings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Provider configured + cold start: lifespan must log the skip and not block.

    Must inject a slow _index_mgr.build_index mock so the background thread is
    reliably still running when the lifespan checks is_index_ready() — otherwise
    on a tiny vault the background completes between spawn and check, embeddings
    runs, and the test asserts the wrong thing.
    """
    import logging
    import time as time_mod

    from markdown_vault_mcp.server import make_server
    from tests.conftest import MockEmbeddingProvider

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "n.md").write_text("# N\n\nbody\n", encoding="utf-8")

    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_INDEX_PATH", str(tmp_path / "fts.db"))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_STATE_PATH", str(tmp_path / "s.json"))

    # Patch IndexManager.build_index globally to sleep before returning,
    # ensuring the background thread is still running when the lifespan
    # makes the is_index_ready() decision.
    from markdown_vault_mcp.managers import index as index_mod

    original_build_index = index_mod.IndexManager.build_index

    def slow_build_index(self, *, force: bool = False):  # type: ignore[no-untyped-def]
        time_mod.sleep(0.5)
        return original_build_index(self, force=force)

    monkeypatch.setattr(index_mod.IndexManager, "build_index", slow_build_index)

    # Inject a MockEmbeddingProvider into to_collection_kwargs so that
    # kwargs["embedding_provider"] is non-None without needing a real provider.
    # "mock" is not a registered provider name in get_embedding_provider(), so
    # we patch at the config level instead.
    from markdown_vault_mcp import config as config_mod

    original_to_kwargs = config_mod.CollectionConfig.to_collection_kwargs

    def patched_to_kwargs(self):  # type: ignore[no-untyped-def]
        kw = original_to_kwargs(self)
        kw["embedding_provider"] = MockEmbeddingProvider()
        # embeddings_path is required when embedding_provider is set.
        if kw.get("embeddings_path") is None:
            kw["embeddings_path"] = tmp_path / "vectors"
        return kw

    monkeypatch.setattr(
        config_mod.CollectionConfig, "to_collection_kwargs", patched_to_kwargs
    )

    server = make_server()
    caplog.set_level(logging.INFO)

    async def _run() -> None:
        async with Client(server):
            pass  # lifespan runs

    asyncio.run(_run())
    assert any(
        "embeddings deferred" in record.message.lower()
        or "skipping embeddings" in record.message.lower()
        for record in caplog.records
    ), f"expected 'embeddings deferred' log; got: {[r.message for r in caplog.records]}"


def test_decorator_preflight_one_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """COMMIT-A gate: decorator + applied to get_backlinks only.
    The tool must be callable end-to-end via Client — proves FastMCP
    accepted the wrapped handler and injected `collection` correctly."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("# A\n\nbody\n", encoding="utf-8")
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_INDEX_PATH", str(tmp_path / "fts.db"))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_STATE_PATH", str(tmp_path / "s.json"))

    from markdown_vault_mcp.server import make_server

    server = make_server()

    async def _call() -> list[Any]:
        async with Client(server) as client:
            res = await client.call_tool("get_backlinks", {"path": "a.md"})
            return res.structured_content or []

    result = asyncio.run(_call())
    assert isinstance(result, (list, dict))  # may be wrapped; just must not raise


def test_decorator_cold_path_blocks_until_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An MCP-client call to get_backlinks during in-flight background
    blocks on the decorator's wait, then succeeds when the build finishes.
    """
    import time as time_mod

    from markdown_vault_mcp.managers import index as index_mod
    from markdown_vault_mcp.server import make_server

    vault = tmp_path / "vault"
    vault.mkdir()
    for i in range(3):
        (vault / f"n_{i}.md").write_text(f"# N{i}\n\nbody\n", encoding="utf-8")

    monkeypatch.setenv("MARKDOWN_VAULT_MCP_SOURCE_DIR", str(vault))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_INDEX_PATH", str(tmp_path / "fts.db"))
    monkeypatch.setenv("MARKDOWN_VAULT_MCP_STATE_PATH", str(tmp_path / "s.json"))

    original_build_index = index_mod.IndexManager.build_index

    def slow_build_index(self, *, force: bool = False):  # type: ignore[no-untyped-def]
        time_mod.sleep(0.3)
        return original_build_index(self, force=force)

    monkeypatch.setattr(index_mod.IndexManager, "build_index", slow_build_index)

    server = make_server()

    async def _call() -> Any:
        async with Client(server) as client:
            return await client.call_tool("get_backlinks", {"path": "n_0.md"})

    result = asyncio.run(_call())
    assert result is not None  # call succeeded after blocking ~0.3s
