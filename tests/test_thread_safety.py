"""Thread-safety contract tests for FTSIndex (issue #519).

Each test exercises one failure mode that the per-thread connection model
must address. Run individually with ``uv run pytest tests/test_thread_safety.py``.

The carryover design (per ``project_issue_519_attempt_1_abandon.md``) is:
per-thread ``sqlite3.Connection`` via ``threading.local``, strong-ref
registry guarded by ``_reg_lock``, ``_closed`` flag with double-checked
locking, ``BaseException`` cleanup on slow-path open, ``_primary_conn``
strong attribute, shared-cache URI translation for ``:memory:`` with
startup probe, and pragmas applied BEFORE schema/migrations.
"""

from __future__ import annotations

import gc
import sqlite3
import threading
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from markdown_vault_mcp.collection import Collection
from markdown_vault_mcp.fts_index import FTSIndex


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Filesystem-backed SQLite DB path for tests."""
    return tmp_path / "fts.sqlite"


@pytest.fixture
def fts(tmp_db: Path):
    """Tempfile-backed FTSIndex. Closed at teardown."""
    idx = FTSIndex(db_path=tmp_db)
    try:
        yield idx
    finally:
        idx.close()


@pytest.fixture
def fts_memory():
    """`:memory:` FTSIndex. Closed at teardown.

    Safe for multi-threaded tests under the new design because
    ``:memory:`` is translated to a shared-cache URI so every per-thread
    open joins the same in-memory DB.
    """
    idx = FTSIndex(db_path=":memory:")
    try:
        yield idx
    finally:
        idx.close()


def _make_collection(tmp_path: Path) -> Collection:
    """Build a writeable file-backed Collection."""
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    return Collection(
        source_dir=vault,
        index_path=tmp_path / "fts.sqlite",
        read_only=False,
    )


# ---------------------------------------------------------------------------
# Per-thread connection mechanics
# ---------------------------------------------------------------------------


def test_conn_is_per_thread(fts: FTSIndex) -> None:
    """`_conn()` returns the same object per thread, distinct objects across threads."""
    main = fts._conn()
    assert fts._conn() is main, "second call from same thread must return same conn"

    seen: dict[str, sqlite3.Connection] = {}

    def grab() -> None:
        seen["worker"] = fts._conn()
        seen["worker2"] = fts._conn()

    t = threading.Thread(target=grab)
    t.start()
    t.join()
    assert seen["worker"] is seen["worker2"], "worker thread reuses its TLS slot"
    assert seen["worker"] is not main, "worker conn must be distinct from main"


def test_pragmas_applied_per_connection(fts: FTSIndex) -> None:
    """Every per-thread conn has foreign_keys, busy_timeout, synchronous applied;
    WAL persists in the DB header for file-backed DBs."""

    def check(out: dict[str, object]) -> None:
        conn = fts._conn()
        out["foreign_keys"] = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        out["busy_timeout"] = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        out["synchronous"] = conn.execute("PRAGMA synchronous").fetchone()[0]
        out["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]

    out: dict[str, object] = {}
    t = threading.Thread(target=check, args=(out,))
    t.start()
    t.join()

    assert out["foreign_keys"] == 1
    assert out["busy_timeout"] == 5000
    assert out["synchronous"] == 1  # NORMAL
    assert str(out["journal_mode"]).lower() == "wal"


def test_pragmas_applied_before_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_db: Path
) -> None:
    """`_apply_pragmas` must run BEFORE `_init_schema` so busy_timeout is active
    during ALTER TABLE migrations.

    Capture the call order by patching both methods on the class.
    """
    order: list[str] = []
    real_apply = FTSIndex._apply_pragmas  # type: ignore[attr-defined]
    real_init = FTSIndex._init_schema  # type: ignore[attr-defined]

    def spy_apply(self, conn):  # type: ignore[no-untyped-def]
        order.append("pragmas")
        return real_apply(self, conn)

    def spy_init(self, conn):  # type: ignore[no-untyped-def]
        order.append("schema")
        return real_init(self, conn)

    monkeypatch.setattr(FTSIndex, "_apply_pragmas", spy_apply)
    monkeypatch.setattr(FTSIndex, "_init_schema", spy_init)

    idx = FTSIndex(db_path=tmp_db)
    try:
        assert order[:2] == ["pragmas", "schema"], (
            f"pragmas must precede schema; got {order}"
        )
    finally:
        idx.close()


def test_init_schema_runs_once_across_all_threads(
    monkeypatch: pytest.MonkeyPatch, tmp_db: Path
) -> None:
    """Schema/migrations run exactly once on the constructing thread; per-thread
    opens only apply pragmas."""
    call_count = {"n": 0}
    real = FTSIndex._init_schema  # type: ignore[attr-defined]

    def spy(self, conn):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        return real(self, conn)

    monkeypatch.setattr(FTSIndex, "_init_schema", spy)

    idx = FTSIndex(db_path=tmp_db)
    try:
        # Touch from 5 worker threads.
        def touch() -> None:
            idx._conn().execute("SELECT 1").fetchone()

        threads = [threading.Thread(target=touch) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert call_count["n"] == 1, (
            f"_init_schema must run exactly once; got {call_count['n']}"
        )
    finally:
        idx.close()


def test_close_closes_all_per_thread_connections(fts: FTSIndex) -> None:
    """After close(), every registered connection raises on use."""
    captured: list[sqlite3.Connection] = [fts._conn()]

    def grab() -> None:
        captured.append(fts._conn())

    t = threading.Thread(target=grab)
    t.start()
    t.join()
    assert len(captured) == 2

    fts.close()
    for conn in captured:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_close_is_idempotent(fts: FTSIndex) -> None:
    """Second close() is a no-op, not an error."""
    fts._conn()
    fts.close()
    fts.close()  # must not raise


def test_closed_index_rejects_new_thread_access(fts: FTSIndex) -> None:
    """After close(), a never-before-seen thread calling _conn() gets
    ProgrammingError — not a half-registered new connection."""
    fts._conn()
    fts.close()

    errors: list[BaseException] = []

    def attempt() -> None:
        try:
            fts._conn()
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=attempt)
    t.start()
    t.join()

    assert len(errors) == 1
    assert isinstance(errors[0], sqlite3.ProgrammingError)


def test_concurrent_close_and_new_thread_conn_open_is_safe(fts: FTSIndex) -> None:
    """A new thread calling _conn() racing with close() must end in either:
    (a) a usable conn that is then closed by close(), OR
    (b) ProgrammingError from the slow-path re-check.

    Neither outcome leaks a connection past close() or crashes the close()."""
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def opener() -> None:
        barrier.wait()
        try:
            c = fts._conn()
            c.execute("SELECT 1").fetchone()
            outcomes.append("opened")
        except sqlite3.ProgrammingError:
            outcomes.append("rejected")

    def closer() -> None:
        barrier.wait()
        fts.close()

    t_open = threading.Thread(target=opener)
    t_close = threading.Thread(target=closer)
    t_open.start()
    t_close.start()
    t_open.join()
    t_close.join()

    assert outcomes and outcomes[0] in {"opened", "rejected"}


def test_registry_uses_strong_refs(fts: FTSIndex) -> None:
    """Registry must hold strong refs so close() can close worker conns even
    after the worker thread has exited and gc has run.

    Weakrefs are explicitly REJECTED per ``feedback_519_weakref_whackamole.md``.
    """
    fts._conn()  # primary
    worker_id: list[int] = []

    def worker() -> None:
        worker_id.append(id(fts._conn()))

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    del t
    gc.collect()

    # Registry still holds the worker conn.
    assert any(id(c) == worker_id[0] for c in fts._all_conns), (
        "worker conn must survive thread exit + gc in strong-ref registry"
    )


def test_memory_db_is_shared_across_threads(fts_memory: FTSIndex) -> None:
    """:memory: must be shared across threads via shared-cache URI translation.

    Pre-PR-#520, each thread's _conn() against ":memory:" got a separate
    empty DB and the schema was invisible. The translation must fix this.
    """

    def query(out: dict[str, object]) -> None:
        conn = fts_memory._conn()
        # If the per-thread conn sees an empty DB, this raises OperationalError.
        out["count"] = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    out: dict[str, object] = {}
    t = threading.Thread(target=query, args=(out,))
    t.start()
    t.join()
    assert out.get("count") == 0


def test_concurrent_writers_serialize_via_collection_write_lock(
    tmp_path: Path,
) -> None:
    """Two writer threads each writing 20 distinct paths through Collection
    produce 40 docs with no SQLITE_BUSY / lost writes."""
    coll = _make_collection(tmp_path)
    coll.build_index()

    errors: list[BaseException] = []

    def writer(prefix: str) -> None:
        for i in range(20):
            try:
                coll.write(f"{prefix}-{i}.md", f"# {prefix}{i}\n\nbody\n")
            except BaseException as exc:
                errors.append(exc)

    t1 = threading.Thread(target=writer, args=("a",))
    t2 = threading.Thread(target=writer, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    try:
        assert not errors, f"writer errors: {errors!r}"
        docs = coll.list()
        assert len(docs) == 40
    finally:
        coll.close()


def test_concurrent_build_and_reads_pr518_pattern(tmp_path: Path) -> None:
    """The acceptance test for #519 (and prerequisite for #513).

    Background thread loops build_index(); main thread runs mixed read /
    search / write / edit concurrently. None of the cross-thread sqlite3
    errors that killed PRs #510/#515/#516/#518 must surface.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    # Seed a few notes so build_index has something to scan.
    for i in range(10):
        (vault / f"seed-{i}.md").write_text(f"# Seed {i}\n\ncontent {i}\n")

    coll = Collection(
        source_dir=vault,
        index_path=tmp_path / "fts.sqlite",
        read_only=False,
    )
    coll.build_index()

    errors: list[BaseException] = []
    stop = threading.Event()

    def background_build() -> None:
        for _ in range(5):
            if stop.is_set():
                return
            try:
                coll.build_index(force=True)
            except BaseException as exc:
                errors.append(exc)
                return

    def foreground_mix() -> None:
        try:
            for i in range(50):
                coll.list()
                coll.search("content", limit=5)
                coll.write(f"new-{i}.md", f"# New {i}\n\nbody\n")
                coll.read(f"new-{i}.md")
                if i % 5 == 0:
                    coll.edit(
                        f"new-{i}.md", f"# New {i}\n\nbody\n", f"# New {i}\n\nEDITED\n"
                    )
        except BaseException as exc:
            errors.append(exc)
        finally:
            stop.set()

    bg = threading.Thread(target=background_build)
    fg = threading.Thread(target=foreground_mix)
    bg.start()
    fg.start()
    fg.join(timeout=60)
    bg.join(timeout=10)

    try:
        for exc in errors:
            assert not isinstance(
                exc,
                (
                    sqlite3.OperationalError,
                    sqlite3.InterfaceError,
                    sqlite3.ProgrammingError,
                ),
            ), f"cross-thread sqlite3 error: {exc!r}"
        assert not errors, f"unexpected errors: {errors!r}"
    finally:
        coll.close()
