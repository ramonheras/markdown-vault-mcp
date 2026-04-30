"""Search, list, and query manager.

Handles all search operations (keyword, semantic, hybrid), document listing,
folder/tag enumeration, recent notes, similar notes, and consolidated
context queries with dependency injection — receives only the FTS index,
source directory, and optional collaborators.
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import logging
import math
import mimetypes
import re as _re
import sqlite3
from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from markdown_vault_mcp.types import (
    AttachmentInfo,
    BacklinkInfo,
    NoteContext,
    NoteInfo,
    OutlinkInfo,
    SearchResult,
    SimilarItem,
)
from markdown_vault_mcp.utils import (
    effective_attachment_extensions,
    fts_row_to_note_info,
    is_path_excluded,
    validate_path,
)

if TYPE_CHECKING:
    import builtins
    from collections.abc import Callable

    from markdown_vault_mcp.fts_index import FTSIndex
    from markdown_vault_mcp.managers.link import LinkManager
    from markdown_vault_mcp.providers import EmbeddingProvider
    from markdown_vault_mcp.types import FTSResult
    from markdown_vault_mcp.vector_index import VectorIndex

logger = logging.getLogger(__name__)

# RRF constant — standard value recommended in the original paper.
_RRF_K = 60

# Regex for extracting query tokens (alphanumeric sequences).
_QUERY_TOKEN_RE = _re.compile(r"[A-Za-z0-9]+")

# Maximum folder peers returned by get_context().
_CONTEXT_FOLDER_PEERS_LIMIT = 20

_RankT = TypeVar("_RankT")


def _apply_length_downweight(rows: list[_RankT], *, alpha: float) -> list[_RankT]:
    """Re-rank ``rows`` by ``score / (1 + alpha * log(chunk_count))``.

    Each element must expose ``score: float`` and ``chunk_count: int``
    attributes.  Works for both :class:`FTSResult` and dataclass adapters
    used by the semantic-channel pipeline.

    Returns a new list sorted by descending adjusted score; input is not
    mutated.
    """
    if alpha <= 0 or not rows:
        return list(rows)

    adjusted: list[tuple[_RankT, float]] = []
    for row in rows:
        chunk_count = max(1, getattr(row, "chunk_count", 1))
        # log(1) = 0 -> factor = 1 -> no change for single-chunk docs.
        factor = 1.0 + alpha * math.log(chunk_count)
        new_score = row.score / factor  # type: ignore[attr-defined]
        try:
            new_row = _dc_replace(row, score=new_score)  # type: ignore[type-var]
        except TypeError:
            # Not a dataclass: fall back to a shallow copy.
            import copy as _copy

            new_row = _copy.copy(row)
            new_row.score = new_score  # type: ignore[attr-defined]
        adjusted.append((new_row, new_score))

    adjusted.sort(key=lambda t: t[1], reverse=True)
    return [r for r, _ in adjusted]


def _apply_chunks_per_doc_cap(
    rows: list[_RankT], *, n: int, limit: int
) -> list[_RankT]:
    """Walk ``rows`` in order; keep at most ``n`` rows per ``path``; stop at ``limit``.

    Each element must expose a ``path`` attribute. Order is preserved.

    Raises:
        ValueError: If ``n`` is less than 1.
    """
    if n < 1:
        raise ValueError(f"chunks_per_doc cap must be >= 1, got {n}")
    out: list[_RankT] = []
    counts: dict[str, int] = {}
    for row in rows:
        path = row.path  # type: ignore[attr-defined]
        if counts.get(path, 0) >= n:
            continue
        counts[path] = counts.get(path, 0) + 1
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _compute_snippet_for_semantic(
    content: str, query: str, *, snippet_words: int
) -> str:
    """Pick a ``snippet_words``-wide window from ``content``.

    Returns the full content when ``snippet_words`` is 0, when the chunk is
    already shorter, or as a fallback when no query tokens overlap (in which
    case the first ``snippet_words`` words are returned with a trailing
    ellipsis).

    Uses simple case-insensitive substring matching on alphanumeric tokens.
    """
    if snippet_words <= 0:
        return content

    words = content.split()
    if len(words) <= snippet_words:
        return content

    query_tokens = {t.lower() for t in _QUERY_TOKEN_RE.findall(query)}
    if not query_tokens:
        return " ".join(words[:snippet_words]) + " …"

    # Normalise each word: keep alphanumeric chars, lower-case, fall back to
    # the lowercased original if the regex strip leaves an empty string.
    lower_words = [_QUERY_TOKEN_RE.sub("", w).lower() or w.lower() for w in words]

    # Sliding window: maintain best_start / best_score, update incrementally.
    best_start = 0
    best_score = sum(1 for w in lower_words[:snippet_words] if w in query_tokens)
    cur_score = best_score
    for i in range(1, len(words) - snippet_words + 1):
        if lower_words[i - 1] in query_tokens:
            cur_score -= 1
        if lower_words[i + snippet_words - 1] in query_tokens:
            cur_score += 1
        if cur_score > best_score:
            best_score = cur_score
            best_start = i

    if best_score == 0:
        # No literal overlap anywhere — fall back to first-N words.
        return " ".join(words[:snippet_words]) + " …"

    snippet = " ".join(words[best_start : best_start + snippet_words])
    if best_start > 0:
        snippet = "… " + snippet
    if best_start + snippet_words < len(words):
        snippet = snippet + " …"
    return snippet


@dataclass
class _SemanticRow:
    """Adapter row for vector search results so they expose .score / .chunk_count."""

    path: str
    title: str
    folder: str
    heading: str | None
    content: str
    score: float
    chunk_count: int


class SearchManager:
    """Manages search, listing, and query operations against the vault.

    Args:
        fts: The FTS index to query.
        source_dir: Absolute path to the vault root directory.
        embeddings_path: Base path for ``.npy`` / ``.json`` sidecar files.
            ``None`` disables semantic search.
        embedding_provider: Provider used to generate embeddings.
        indexed_frontmatter_fields: Frontmatter keys promoted to
            ``document_tags`` for structured filtering.
        exclude_patterns: Glob patterns for paths to exclude from listing.
        attachment_extensions: Allowed non-.md extensions.  ``None`` uses
            the default set.
        link_manager: Optional :class:`LinkManager` for context queries.
        flush_embeddings: Callback to flush deferred embedding updates
            before semantic search.
        rebuild_embeddings: Callback to rebuild all embeddings from scratch
            (used when vector index compatibility fails).
    """

    def __init__(
        self,
        fts: FTSIndex,
        source_dir: Path,
        *,
        embeddings_path: Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        indexed_frontmatter_fields: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        attachment_extensions: list[str] | None = None,
        link_manager: LinkManager | None = None,
        flush_embeddings: Callable[[], None] | None = None,
        rebuild_embeddings: Callable[[], None] | None = None,
        chunks_per_doc: int = 2,
        snippet_words: int = 200,
        length_downweight_alpha: float = 0.25,
    ) -> None:
        self._fts = fts
        self._source_dir = source_dir
        self._embeddings_path = embeddings_path
        self._embedding_provider = embedding_provider
        self._indexed_frontmatter_fields: list[str] = indexed_frontmatter_fields or []
        self._exclude_patterns = exclude_patterns
        self._attachment_extensions = attachment_extensions
        self._link_manager = link_manager
        self._flush_embeddings = flush_embeddings or (lambda: None)
        self._rebuild_embeddings = rebuild_embeddings or (lambda: None)
        self._chunks_per_doc = chunks_per_doc
        self._snippet_words = snippet_words
        self._length_downweight_alpha = length_downweight_alpha

        # Vector index is loaded lazily (only if embeddings_path is set).
        self._vectors: VectorIndex | None = None

    # ------------------------------------------------------------------
    # Vector index property (shared with IndexManager)
    # ------------------------------------------------------------------

    @property
    def vectors(self) -> VectorIndex | None:
        """Return the lazily-loaded vector index, or ``None``."""
        return self._vectors

    @vectors.setter
    def vectors(self, value: VectorIndex | None) -> None:
        self._vectors = value

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_path(self, path: str) -> None:
        """Validate that *path* ends with ``.md`` and stays inside source_dir.

        Args:
            path: Relative vault path to validate.

        Raises:
            ValueError: If the path does not end with ``.md`` or escapes
                the source directory.
        """
        validate_path(path, self._source_dir)

    def _require_vectors(self) -> None:
        """Raise ValueError if semantic search is not configured."""
        if self._embedding_provider is None or self._embeddings_path is None:
            raise ValueError(
                "Semantic search requires both 'embedding_provider' and "
                "'embeddings_path' to be configured."
            )

    def _load_vectors(self) -> VectorIndex:
        """Load or return the cached VectorIndex.

        Returns:
            A :class:`~markdown_vault_mcp.vector_index.VectorIndex` instance.
        """
        if self._vectors is not None:
            return self._vectors

        from markdown_vault_mcp.vector_index import (
            VectorIndex,
            VectorIndexCompatibilityError,
        )

        if self._embeddings_path is None or self._embedding_provider is None:
            raise RuntimeError(
                "_require_vectors() must be called before _load_vectors()"
            )

        npy_path = Path(str(self._embeddings_path) + ".npy")
        if npy_path.exists():
            try:
                self._vectors = VectorIndex.load(
                    self._embeddings_path, self._embedding_provider
                )
                logger.info("Loaded vector index from %s", self._embeddings_path)
            except VectorIndexCompatibilityError as exc:
                logger.warning("%s Rebuilding embeddings.", exc)
                self._rebuild_embeddings()
                if self._vectors is None:
                    raise ValueError(
                        "Failed to rebuild vector index after a compatibility error."
                    ) from exc
        else:
            self._vectors = VectorIndex(self._embedding_provider)
            logger.info("No vector index on disk; created empty VectorIndex")

        return self._vectors

    def _get_frontmatter(self, path: str) -> dict[str, Any]:
        """Return the frontmatter dict for a document from the FTS index.

        Falls back to an empty dict if the document is not found.

        Args:
            path: Relative document path.

        Returns:
            Parsed frontmatter dict.
        """
        row = self._fts.get_note(path)
        if row is None:
            return {}
        raw = row.get("frontmatter_json")
        if not raw:
            return {}
        try:
            result: dict[str, Any] = json.loads(raw)
            return result
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "_get_frontmatter: invalid JSON for %s — %s",
                row.get("path"),
                exc,
            )
            return {}

    def _fts_chunk_count_for(self, path: str) -> int:
        """Look up parent doc chunk_count from the FTS index, default 1.

        Args:
            path: Relative document path.

        Returns:
            The ``chunk_count`` value stored in the documents table, or 1 if
            the document is not found.
        """
        row = self._fts._conn.execute(
            "SELECT chunk_count FROM documents WHERE path = ?", (path,)
        ).fetchone()
        return int(row["chunk_count"]) if row else 1

    def _row_matches_filters(self, path: str, filters: dict[str, str]) -> bool:
        """Return ``True`` if the document at *path* satisfies all *filters*.

        Looks up frontmatter from the FTS index and checks each key/value
        pair.  List-valued frontmatter fields are matched by membership.

        Args:
            path: Relative document path.
            filters: Dict of ``{frontmatter_key: value}`` pairs.

        Returns:
            ``True`` if the document exists and all filter conditions are met.
        """
        note_row = self._fts.get_note(path)
        if note_row is None:
            return False
        fm_raw = note_row.get("frontmatter_json")
        fm: dict[str, Any] = {}
        if fm_raw:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                fm = json.loads(fm_raw)
        for key, value in filters.items():
            fm_val = fm.get(key)
            if fm_val is None:
                return False
            if isinstance(fm_val, list):
                if str(value) not in [str(v) for v in fm_val]:
                    return False
            else:
                if str(fm_val) != str(value):
                    return False
        return True

    def _effective_attachment_extensions(self) -> frozenset[str]:
        """Return the effective set of allowed attachment extensions.

        Returns:
            Frozenset of lower-case extension strings (without leading dot).
            The special value ``frozenset(["*"])`` means all non-.md files.
        """
        return effective_attachment_extensions(self._attachment_extensions)

    def _is_path_excluded(self, path: str) -> bool:
        """Check whether *path* matches any configured exclude pattern.

        Args:
            path: Relative POSIX path string.

        Returns:
            ``True`` if the path matches any pattern in
            ``self._exclude_patterns``.
        """
        return is_path_excluded(path, self._exclude_patterns)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        mode: Literal["keyword", "semantic", "hybrid"] = "keyword",
        filters: dict[str, str] | None = None,
        folder: str | None = None,
        chunks_per_doc: int | None = None,
        snippet_words: int | None = None,
    ) -> list[SearchResult]:
        """Search the collection.

        Args:
            query: Search string.
            limit: Maximum number of results to return.
            mode: ``"keyword"`` for BM25 FTS5, ``"semantic"`` for cosine
                similarity, or ``"hybrid"`` for Reciprocal Rank Fusion of
                both.
            filters: Dict of ``{frontmatter_key: value}`` pairs (AND
                semantics).  Only works for fields in
                ``indexed_frontmatter_fields``.
            folder: If provided, restrict results to documents in this
                folder (and its sub-folders).
            chunks_per_doc: Maximum number of chunks to return per document.
                ``None`` uses the instance default (``self._chunks_per_doc``).
            snippet_words: Width of the FTS5 snippet window in words.
                ``0`` returns full chunk content.  ``None`` uses the instance
                default (``self._snippet_words``).

        Returns:
            List of :class:`~markdown_vault_mcp.types.SearchResult` ordered
            by relevance.

        Raises:
            ValueError: If *mode* is ``"semantic"`` or ``"hybrid"`` but no
                embedding provider or embeddings path is configured.
        """
        eff_cap = chunks_per_doc if chunks_per_doc is not None else self._chunks_per_doc
        eff_snip = snippet_words if snippet_words is not None else self._snippet_words

        if mode == "keyword":
            return self._keyword_search(
                query,
                limit=limit,
                filters=filters,
                folder=folder,
                chunks_per_doc=eff_cap,
                snippet_words=eff_snip,
            )

        if mode == "semantic":
            self._require_vectors()
            return self._semantic_search(
                query,
                limit=limit,
                filters=filters,
                folder=folder,
                chunks_per_doc=eff_cap,
                snippet_words=eff_snip,
            )

        # hybrid
        self._require_vectors()
        return self._hybrid_search(query, limit=limit, filters=filters, folder=folder)

    def _keyword_search(
        self,
        query: str,
        *,
        limit: int,
        filters: dict[str, str] | None,
        folder: str | None,
        chunks_per_doc: int,
        snippet_words: int,
    ) -> list[SearchResult]:
        # Widen candidate pool so the cap doesn't starve us of `limit` rows.
        candidate_limit = max(limit * (chunks_per_doc + 4), 50)

        # Fetch raw content first (no snippet projection yet) so the length-
        # downweight has full chunk_count info. Snippet projection runs only
        # for survivors, via a second FTS query.
        raw = self._fts.search(
            query,
            limit=candidate_limit,
            filters=filters,
            folder=folder,
            snippet_words=None,
        )
        downweighted = _apply_length_downweight(
            raw, alpha=self._length_downweight_alpha
        )
        capped = _apply_chunks_per_doc_cap(downweighted, n=chunks_per_doc, limit=limit)

        if snippet_words > 0:
            snippets_by_key = self._fetch_snippet_map(
                query, capped, snippet_words=snippet_words
            )
        else:
            snippets_by_key = {}

        return [
            SearchResult(
                path=r.path,
                title=r.title,
                folder=r.folder,
                heading=r.heading,
                content=snippets_by_key.get((r.path, r.heading), r.content),
                score=r.score,
                search_type="keyword",
                frontmatter=self._get_frontmatter(r.path),
            )
            for r in capped
        ]

    def _fetch_snippet_map(
        self,
        query: str,
        survivors: list[FTSResult],
        *,
        snippet_words: int,
    ) -> dict[tuple[str, str | None], str]:
        """Re-query FTS with snippet projection, restricted to survivor paths.

        Returns a ``{(path, heading): snippet}`` map. Falls back to the
        survivor's own ``content`` field when an FTS row cannot be located
        for a given key.
        """
        if not survivors:
            return {}
        candidate_n = max(len(survivors) * 4, 20)
        rows = self._fts.search(
            query,
            limit=candidate_n,
            snippet_words=snippet_words,
        )
        wanted = {(s.path, s.heading) for s in survivors}
        return {
            (r.path, r.heading): r.content
            for r in rows
            if (r.path, r.heading) in wanted
        }

    def _semantic_search(
        self,
        query: str,
        *,
        limit: int,
        filters: dict[str, str] | None = None,
        folder: str | None = None,
        chunks_per_doc: int,
        snippet_words: int,
    ) -> list[SearchResult]:
        self._flush_embeddings()
        vectors = self._load_vectors()
        candidate_limit = max(limit * (chunks_per_doc + 4), 50)
        raw = vectors.search(query, limit=candidate_limit)

        rows: list[_SemanticRow] = []
        for r in raw:
            if folder is not None:
                r_folder = r.get("folder", "")
                if r_folder != folder and not r_folder.startswith(folder + "/"):
                    continue
            if filters and not self._row_matches_filters(r["path"], filters):
                continue
            rows.append(
                _SemanticRow(
                    path=r["path"],
                    title=r["title"],
                    folder=r["folder"],
                    heading=r.get("heading"),
                    content=r["content"],
                    score=r["score"],
                    chunk_count=self._fts_chunk_count_for(r["path"]),
                )
            )

        downweighted = _apply_length_downweight(
            rows, alpha=self._length_downweight_alpha
        )
        capped = _apply_chunks_per_doc_cap(downweighted, n=chunks_per_doc, limit=limit)

        return [
            SearchResult(
                path=r.path,
                title=r.title,
                folder=r.folder,
                heading=r.heading,
                content=_compute_snippet_for_semantic(
                    r.content, query, snippet_words=snippet_words
                ),
                score=r.score,
                search_type="semantic",
                frontmatter=self._get_frontmatter(r.path),
            )
            for r in capped
        ]

    def _hybrid_search(
        self,
        query: str,
        *,
        limit: int,
        filters: dict[str, str] | None,
        folder: str | None,
    ) -> list[SearchResult]:
        """RRF merge of keyword and semantic results.

        Each result set is ranked independently.  Merged score:
        ``1 / (k + rank)`` where k=60.  Results appearing in both sets
        have their scores summed.  Returns top *limit* by total RRF score.
        """
        # Fetch more candidates than needed so RRF has enough to rank.
        candidate_limit = max(limit * 2, 20)

        # Flush deferred embedding updates so results are consistent.
        self._flush_embeddings()

        fts_results = self._fts.search(
            query, limit=candidate_limit, filters=filters, folder=folder
        )
        vectors = self._load_vectors()
        vec_results = vectors.search(query, limit=candidate_limit)

        # Build a key for deduplication: (path, heading) identifies a chunk.
        # Use a dict to accumulate RRF scores and store metadata.
        rrf_scores: dict[tuple[str, str | None], float] = {}
        # Store the best metadata dict keyed by (path, heading).
        chunk_meta: dict[tuple[str, str | None], dict[str, Any]] = {}

        for rank, r in enumerate(fts_results, start=1):
            key = (r.path, r.heading)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
            if key not in chunk_meta:
                chunk_meta[key] = {
                    "path": r.path,
                    "title": r.title,
                    "folder": r.folder,
                    "heading": r.heading,
                    "content": r.content,
                    "search_type": "keyword",
                }

        for rank, vr in enumerate(vec_results, start=1):
            # Apply folder prefix filter to semantic results.
            if folder is not None:
                vr_folder = vr.get("folder", "")
                if vr_folder != folder and not vr_folder.startswith(folder + "/"):
                    continue

            # Apply tag filters to semantic results via frontmatter lookup.
            if filters:
                note_row = self._fts.get_note(vr["path"])
                if note_row is None:
                    continue
                fm_raw = note_row.get("frontmatter_json")
                fm: dict[str, Any] = {}
                if fm_raw:
                    with contextlib.suppress(json.JSONDecodeError, TypeError):
                        fm = json.loads(fm_raw)
                skip = False
                for fk, fv in filters.items():
                    fm_val = fm.get(fk)
                    if fm_val is None:
                        skip = True
                        break
                    if isinstance(fm_val, list):
                        if str(fv) not in [str(v) for v in fm_val]:
                            skip = True
                            break
                    else:
                        if str(fm_val) != str(fv):
                            skip = True
                            break
                if skip:
                    continue

            heading = vr.get("heading")
            vkey = (vr["path"], heading)
            rrf_scores[vkey] = rrf_scores.get(vkey, 0.0) + 1.0 / (_RRF_K + rank)
            if vkey not in chunk_meta:
                chunk_meta[vkey] = {
                    "path": vr["path"],
                    "title": vr["title"],
                    "folder": vr["folder"],
                    "heading": heading,
                    "content": vr["content"],
                    "search_type": "semantic",
                }

        # Sort by descending RRF score, take top limit.
        sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)[
            :limit
        ]

        return [
            SearchResult(
                path=chunk_meta[k]["path"],
                title=chunk_meta[k]["title"],
                folder=chunk_meta[k]["folder"],
                heading=chunk_meta[k]["heading"],
                content=chunk_meta[k]["content"],
                score=rrf_scores[k],
                search_type=chunk_meta[k]["search_type"],
                frontmatter=self._get_frontmatter(chunk_meta[k]["path"]),
            )
            for k in sorted_keys
        ]

    # ------------------------------------------------------------------
    # List / enumerate
    # ------------------------------------------------------------------

    def list(
        self,
        *,
        folder: str | None = None,
        pattern: str | None = None,
        include_attachments: bool = False,
    ) -> list[NoteInfo | AttachmentInfo]:
        """List documents (and optionally attachments) in the collection.

        Args:
            folder: If provided, only return documents in this folder (and
                sub-folders).
            pattern: Unix glob matched against the relative path using
                :func:`fnmatch.fnmatch`.  Example: ``"Journal/*.md"``.
            include_attachments: When ``True``, also return non-.md files
                that match the attachment allowlist.  Each
                :class:`~markdown_vault_mcp.types.AttachmentInfo` entry
                includes ``kind="attachment"`` and ``mime_type``.

        Returns:
            List of :class:`~markdown_vault_mcp.types.NoteInfo` (and
            optionally :class:`~markdown_vault_mcp.types.AttachmentInfo`)
            objects.
        """
        rows = self._fts.list_notes(folder=folder)
        notes: list[NoteInfo | AttachmentInfo] = [
            fts_row_to_note_info(row) for row in rows
        ]

        if pattern:
            notes = [n for n in notes if fnmatch.fnmatch(n.path, pattern)]

        if not include_attachments:
            return notes

        exts = self._effective_attachment_extensions()
        source_resolved = self._source_dir.resolve()
        attachments: list[AttachmentInfo] = []

        # Attachment scan runs outside _write_lock — result is a best-effort
        # snapshot and is not atomic with the FTS note listing above.
        for abs_path in self._source_dir.rglob("*"):
            if not abs_path.is_file():
                continue
            if abs_path.suffix.lower() == ".md":
                continue
            suffix = abs_path.suffix.lstrip(".").lower()
            if "*" not in exts and suffix not in exts:
                continue
            try:
                rel = abs_path.relative_to(source_resolved)
            except ValueError as exc:
                logger.warning(
                    "_list_attachments: skipping %s — outside source_dir (%s)",
                    abs_path,
                    exc,
                )
                continue
            rel_path = str(rel)
            # Skip files where any path component starts with ".".
            if any(part.startswith(".") for part in rel.parts):
                continue
            # Apply exclude_patterns — mirrors scan_directory behaviour.
            if self._is_path_excluded(rel.as_posix()):
                continue
            if pattern and not fnmatch.fnmatch(rel_path, pattern):
                continue
            rel_folder = str(Path(rel_path).parent)
            if rel_folder == ".":
                rel_folder = ""
            if (
                folder is not None
                and rel_folder != folder
                and not rel_folder.startswith(folder + "/")
            ):
                continue
            try:
                stat = abs_path.stat()
            except OSError as exc:
                logger.warning(
                    "_list_attachments: skipping %s — stat error (%s)",
                    abs_path,
                    exc,
                )
                continue
            mime_type, _ = mimetypes.guess_type(rel_path)
            attachments.append(
                AttachmentInfo(
                    path=rel_path,
                    folder=rel_folder,
                    mime_type=mime_type,
                    size_bytes=stat.st_size,
                    modified_at=stat.st_mtime,
                )
            )

        return notes + attachments

    def list_folders(self) -> builtins.list[str]:
        """Return all distinct folder values across the indexed collection.

        Returns:
            Sorted list of folder strings (``""`` for the collection root).
        """
        return self._fts.list_folders()

    def list_tags(self, field: str = "tags") -> builtins.list[str]:
        """Return all distinct values indexed for a given frontmatter field.

        If *field* was not in ``indexed_frontmatter_fields``, returns ``[]``.

        Args:
            field: Frontmatter key to query (default: ``"tags"``).

        Returns:
            Sorted list of distinct value strings.
        """
        return self._fts.list_field_values(field)

    # ------------------------------------------------------------------
    # Recent / similar / context
    # ------------------------------------------------------------------

    def get_recent(
        self, *, limit: int = 20, folder: str | None = None
    ) -> builtins.list[NoteInfo]:
        """Return the most recently modified documents.

        Args:
            limit: Maximum number of documents to return.
            folder: If provided, restrict to documents in this folder
                (exact match or sub-folder prefix).

        Returns:
            List of :class:`~markdown_vault_mcp.types.NoteInfo` objects
            ordered by modification time (most recent first).
        """
        rows = self._fts.get_recent(limit=limit, folder=folder)
        return [fts_row_to_note_info(row) for row in rows]

    def get_similar(self, path: str, *, limit: int = 10) -> builtins.list[SearchResult]:
        """Return the most semantically similar chunks from other documents.

        Uses the stored embedding vectors for ``path`` (averaged across
        chunks) to compute cosine similarity against all other documents.
        No re-embedding is needed.  Results are at chunk granularity —
        the same document may appear multiple times if it has many chunks.

        Args:
            path: Relative path of the reference document.
            limit: Maximum number of results to return.

        Returns:
            List of :class:`~markdown_vault_mcp.types.SearchResult` objects
            ordered by descending similarity.  Returns ``[]`` when
            embeddings are not configured or the document has no stored
            vectors.

        Raises:
            ValueError: If no document exists at the given path.
        """
        self._validate_path(path)
        if self._fts.get_note(path) is None:
            raise ValueError(f"Document not found: {path}")

        if self._embedding_provider is None or self._embeddings_path is None:
            return []

        self._load_vectors()
        if self._vectors is None or self._vectors.count == 0:
            return []

        raw_results = self._vectors.search_by_path(path, limit=limit)
        return [
            SearchResult(
                path=r["path"],
                title=r.get("title", ""),
                folder=r.get("folder", ""),
                heading=r.get("heading"),
                content=r.get("content", ""),
                score=r.get("score", 0.0),
                search_type="semantic",
                frontmatter=self._get_frontmatter(r["path"]),
            )
            for r in raw_results
        ]

    def get_context(
        self,
        path: str,
        *,
        similar_limit: int = 5,
        link_limit: int = 10,
    ) -> NoteContext:
        """Return a consolidated context dossier for a document.

        Combines backlinks, outlinks, similar notes, folder peers, and
        indexed frontmatter tags into a single response, saving the caller
        multiple round trips.

        Args:
            path: Relative path of the document (e.g.
                ``"notes/topic.md"``).
            similar_limit: Maximum number of similar notes to include.
            link_limit: Maximum number of backlinks and outlinks to include.

        Returns:
            A :class:`~markdown_vault_mcp.types.NoteContext` object.

        Raises:
            ValueError: If no document exists at the given path.
        """
        self._validate_path(path)
        row = self._fts.get_note(path)
        if row is None:
            raise ValueError(f"Document not found: {path}")

        frontmatter = self._get_frontmatter(path)

        # Backlinks — via LinkManager if available, else direct FTS.
        backlink_objs: list[BacklinkInfo] = []
        if self._link_manager is not None:
            try:
                backlink_objs = self._link_manager.get_backlinks(path, limit=link_limit)
            except (ValueError, sqlite3.OperationalError) as exc:
                logger.warning("get_context: backlinks for %s: %s", path, exc)
        else:
            try:
                backlinks = self._fts.get_backlinks(path, limit=link_limit)
                backlink_objs = [
                    BacklinkInfo(
                        source_path=r["source_path"],
                        source_title=r["source_title"],
                        link_text=r["link_text"],
                        link_type=r["link_type"],
                        fragment=r["fragment"],
                        raw_target=r["raw_target"],
                    )
                    for r in backlinks
                ]
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "get_context: failed to retrieve backlinks for %s: %s",
                    path,
                    exc,
                )

        # Outlinks — via LinkManager if available, else direct FTS.
        outlink_objs: list[OutlinkInfo] = []
        if self._link_manager is not None:
            try:
                outlink_objs = self._link_manager.get_outlinks(path, limit=link_limit)
            except (ValueError, sqlite3.OperationalError) as exc:
                logger.warning("get_context: outlinks for %s: %s", path, exc)
        else:
            try:
                outlinks = self._fts.get_outlinks(path, limit=link_limit)
                outlink_objs = [
                    OutlinkInfo(
                        target_path=r["target_path"],
                        link_text=r["link_text"],
                        link_type=r["link_type"],
                        fragment=r["fragment"],
                        exists=bool(r["target_exists"]),
                        raw_target=r["raw_target"],
                    )
                    for r in outlinks
                ]
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "get_context: failed to retrieve outlinks for %s: %s",
                    path,
                    exc,
                )

        # Similar notes — empty if embeddings not configured or
        # similar_limit is 0.
        similar_dicts: list[SimilarItem] = []
        if (
            similar_limit > 0
            and self._embedding_provider is not None
            and self._embeddings_path is not None
        ):
            self._load_vectors()
            if self._vectors is not None and self._vectors.count > 0:
                raw = self._vectors.search_by_path(path, limit=similar_limit)
                similar_dicts = [
                    SimilarItem(
                        path=r["path"],
                        title=r["title"],
                        score=r["score"],
                    )
                    for r in raw
                ]

        # Folder peers — other notes in the same folder, capped.
        folder = row["folder"]
        folder_rows = self._fts.list_notes(folder=folder)
        folder_notes = [r["path"] for r in folder_rows if r["path"] != path][
            :_CONTEXT_FOLDER_PEERS_LIMIT
        ]

        # Tags — indexed frontmatter fields present on this document.
        tags: dict[str, list[str]] = {}
        for field in self._indexed_frontmatter_fields:
            value = frontmatter.get(field)
            if value is None:
                continue
            if isinstance(value, list):
                tags[field] = [str(v) for v in value]
            else:
                tags[field] = [str(value)]

        return NoteContext(
            path=path,
            title=row["title"],
            folder=folder,
            frontmatter=frontmatter,
            modified_at=row["modified_at"],
            backlinks=backlink_objs,
            outlinks=outlink_objs,
            similar=similar_dicts,
            folder_notes=folder_notes,
            tags=tags,
        )
