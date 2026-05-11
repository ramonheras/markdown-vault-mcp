"""Unit tests for :meth:`GitWriteStrategy.force_pull` and
:meth:`GitWriteStrategy.force_push` (added in #444).

The bare-remote + local-clone fixture lives in :mod:`tests.fixtures.git`
so the same setup can be reused by future tests for the higher-level
``git_sync`` MCP tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.fixtures.git import _run_git

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.git import GitRepoPair


def _seed_remote_commit(
    pair: GitRepoPair, *, clone_name: str, file_name: str, body: str
) -> None:
    """Push one new commit to the bare remote from a sibling clone.

    This simulates an out-of-band update to the upstream that the local
    clone in *pair* has not yet seen.
    """
    sibling = pair.remote_path.parent / clone_name
    sibling.mkdir()
    _run_git(sibling, "init", "--initial-branch=main")
    _run_git(sibling, "config", "user.email", "other@example.com")
    _run_git(sibling, "config", "user.name", "Other")
    _run_git(sibling, "remote", "add", "origin", str(pair.remote_path))
    _run_git(sibling, "pull", "origin", "main")
    (sibling / file_name).write_text(body)
    _run_git(sibling, "add", file_name)
    _run_git(sibling, "commit", "-m", f"remote commit: {file_name}")
    _run_git(sibling, "push", "origin", "main")


class TestForcePull:
    """:meth:`GitWriteStrategy.force_pull` pulls from origin synchronously."""

    def test_clean_fast_forward_returns_applied(
        self, git_repo_pair: GitRepoPair
    ) -> None:
        """A simple ff-only pull reports applied=True with the new commit count."""
        from markdown_vault_mcp.git import GitWriteStrategy

        _seed_remote_commit(
            git_repo_pair,
            clone_name="clone2",
            file_name="new.md",
            body="from remote\n",
        )

        strategy = GitWriteStrategy(
            enable_pull=True,
            enable_push=False,
            repo_path=git_repo_pair.local_path,
        )
        result = strategy.force_pull()

        assert result.applied is True
        assert result.fast_forward is True
        assert result.commits_pulled == 1
        assert (git_repo_pair.local_path / "new.md").exists()
        assert result.from_sha != result.to_sha

    def test_already_up_to_date_returns_zero_commits(
        self, git_repo_pair: GitRepoPair
    ) -> None:
        """No upstream changes → applied=True, commits_pulled=0, no SHA move."""
        from markdown_vault_mcp.git import GitWriteStrategy

        strategy = GitWriteStrategy(
            enable_pull=True,
            enable_push=False,
            repo_path=git_repo_pair.local_path,
        )
        result = strategy.force_pull()

        assert result.applied is True
        assert result.commits_pulled == 0
        assert result.from_sha == result.to_sha

    def test_dry_run_does_not_modify_head(self, git_repo_pair: GitRepoPair) -> None:
        """dry_run=True predicts the would-be pull without moving HEAD."""
        from markdown_vault_mcp.git import GitWriteStrategy

        _seed_remote_commit(
            git_repo_pair,
            clone_name="clone2dry",
            file_name="drynew.md",
            body="dry\n",
        )

        strategy = GitWriteStrategy(
            enable_pull=True,
            enable_push=False,
            repo_path=git_repo_pair.local_path,
        )
        head_before = _run_git(git_repo_pair.local_path, "rev-parse", "HEAD").strip()
        result = strategy.force_pull(dry_run=True)
        head_after = _run_git(git_repo_pair.local_path, "rev-parse", "HEAD").strip()

        assert head_before == head_after
        assert result.applied is False  # dry-run reports prediction only
        assert result.commits_pulled == 1  # would pull 1 commit
        assert not (git_repo_pair.local_path / "drynew.md").exists()


class TestForcePush:
    """:meth:`GitWriteStrategy.force_push` pushes to origin synchronously."""

    def test_clean_push_returns_applied(self, git_repo_pair: GitRepoPair) -> None:
        """One local commit ahead → push → applied=True, commits_pushed=1."""
        from markdown_vault_mcp.git import GitWriteStrategy

        # Create a local commit not yet on origin.
        (git_repo_pair.local_path / "local.md").write_text("local change\n")
        _run_git(git_repo_pair.local_path, "add", "local.md")
        _run_git(git_repo_pair.local_path, "commit", "-m", "local commit")

        local_head = _run_git(git_repo_pair.local_path, "rev-parse", "HEAD").strip()
        remote_before = _run_git(
            git_repo_pair.local_path, "rev-parse", "@{upstream}"
        ).strip()
        assert local_head != remote_before

        strategy = GitWriteStrategy(
            enable_pull=False,
            enable_push=True,
            repo_path=git_repo_pair.local_path,
        )
        result = strategy.force_push()

        assert result.applied is True
        assert result.commits_pushed == 1
        assert result.remote_sha_before == remote_before
        assert result.remote_sha_after == local_head

    def test_nothing_to_push_returns_zero(self, git_repo_pair: GitRepoPair) -> None:
        """No local commits ahead → applied=True, commits_pushed=0."""
        from markdown_vault_mcp.git import GitWriteStrategy

        strategy = GitWriteStrategy(
            enable_pull=False,
            enable_push=True,
            repo_path=git_repo_pair.local_path,
        )
        result = strategy.force_push()

        assert result.applied is True
        assert result.commits_pushed == 0
        assert result.remote_sha_before == result.remote_sha_after

    def test_non_fast_forward_returns_hint(self, git_repo_pair: GitRepoPair) -> None:
        """Remote moves ahead + local diverges → push fails non-fast-forward."""
        from markdown_vault_mcp.git import GitWriteStrategy

        # Sibling clone advances the remote so origin/main has a commit
        # the local clone has never seen.
        _seed_remote_commit(
            git_repo_pair,
            clone_name="clone2nff",
            file_name="remote_only.md",
            body="remote\n",
        )

        # Local makes a divergent commit (not based on the new remote tip).
        (git_repo_pair.local_path / "local_only.md").write_text("local\n")
        _run_git(git_repo_pair.local_path, "add", "local_only.md")
        _run_git(git_repo_pair.local_path, "commit", "-m", "local divergent")

        strategy = GitWriteStrategy(
            enable_pull=False,
            enable_push=True,
            repo_path=git_repo_pair.local_path,
        )
        result = strategy.force_push()

        assert result.applied is False
        assert result.reason == "non_fast_forward"
        assert result.hint is not None
        assert "git_sync" in result.hint
        # HEAD on remote did not move.
        assert result.remote_sha_before == result.remote_sha_after

    def test_dry_run_returns_unsupported(self, git_repo_pair: GitRepoPair) -> None:
        """``dry_run=True`` is a no-op — git has no safe remote-acceptance probe."""
        from markdown_vault_mcp.git import GitWriteStrategy

        # Stage a local commit so we know there's something that *would* push.
        (git_repo_pair.local_path / "dryrun.md").write_text("dry-run\n")
        _run_git(git_repo_pair.local_path, "add", "dryrun.md")
        _run_git(git_repo_pair.local_path, "commit", "-m", "dry-run commit")

        strategy = GitWriteStrategy(
            enable_pull=False,
            enable_push=True,
            repo_path=git_repo_pair.local_path,
        )
        result = strategy.force_push(dry_run=True)

        assert result.applied is False
        assert result.commits_pushed == 0
        assert result.reason == "dry_run_unsupported"
        assert result.hint is not None
        # Dry-run must not touch the remote.
        assert result.remote_sha_before == result.remote_sha_after


class TestForceMethodsErrorBranches:
    """Error-path coverage for ``force_pull`` / ``force_push``.

    These tests target the branches the happy-path tests do not exercise:

    * ``_resolve_force_repo`` raising when constructed without ``repo_path``
    * ``force_pull`` ``fetch_failed`` (remote URL unreachable)
    * ``force_pull`` ``no_remote`` (no upstream and no ``origin/HEAD``)
    * ``force_pull`` ``rebased`` (divergent histories on different files)
    * ``force_push`` ``no_remote`` (same upstream-resolution failure)
    * ``force_push`` ``push_failed`` (generic remote rejection, not non-ff)

    Together they take the ``git.py`` diff coverage from ~75% to >=80%.
    """

    def test_force_pull_without_repo_path_raises_runtime_error(self) -> None:
        """``force_pull`` requires ``repo_path`` set at construction time."""
        from markdown_vault_mcp.git import GitWriteStrategy

        strategy = GitWriteStrategy(enable_pull=True, enable_push=False)
        with pytest.raises(RuntimeError, match="repo_path"):
            strategy.force_pull()

    def test_force_push_without_repo_path_raises_runtime_error(self) -> None:
        """``force_push`` requires ``repo_path`` set at construction time."""
        from markdown_vault_mcp.git import GitWriteStrategy

        strategy = GitWriteStrategy(enable_pull=False, enable_push=True)
        with pytest.raises(RuntimeError, match="repo_path"):
            strategy.force_push()

    def test_force_pull_fetch_failed_when_remote_unreachable(
        self, tmp_path: Path
    ) -> None:
        """Unreachable origin URL → ``applied=False`` with ``reason='fetch_failed'``."""
        from markdown_vault_mcp.git import (
            PULL_REASON_FETCH_FAILED,
            GitWriteStrategy,
        )

        repo = tmp_path / "repo"
        repo.mkdir()
        _run_git(repo, "init", "--initial-branch=main")
        _run_git(repo, "config", "user.email", "x@example.com")
        _run_git(repo, "config", "user.name", "X")
        # Point origin at a path that does not exist — ``git fetch`` exits non-zero.
        _run_git(
            repo, "remote", "add", "origin", str(tmp_path / "definitely-not-a-repo")
        )
        (repo / "f.md").write_text("hi\n")
        _run_git(repo, "add", "f.md")
        _run_git(repo, "commit", "-m", "initial")

        strategy = GitWriteStrategy(enable_pull=True, enable_push=False, repo_path=repo)
        head_before = _run_git(repo, "rev-parse", "HEAD").strip()
        result = strategy.force_pull()

        assert result.applied is False
        assert result.reason == PULL_REASON_FETCH_FAILED
        assert result.commits_pulled == 0
        # HEAD did not move on the failed fetch.
        assert result.from_sha == head_before
        assert result.to_sha == head_before

    def test_force_pull_no_remote_when_upstream_and_origin_head_missing(
        self, tmp_path: Path
    ) -> None:
        """No tracking branch and no ``origin/HEAD`` → ``reason='no_remote'``.

        Builds a clone where:

        * ``git fetch origin`` succeeds (the bare remote exists, just has
          no commits to fetch),
        * ``rev-parse @{upstream}`` fails (no upstream set — we never ran
          ``git push -u``),
        * ``rev-parse origin/HEAD`` fails (the empty bare remote has no
          ``HEAD`` symbolic ref to populate ``origin/HEAD``).

        That triple condition exercises the ``no_remote`` return inside
        ``force_pull`` (lines 1029-1042).
        """
        from markdown_vault_mcp.git import (
            PULL_REASON_NO_REMOTE,
            GitWriteStrategy,
        )

        # Empty bare remote — fetch will succeed but produce no refs.
        empty_remote = tmp_path / "empty.git"
        empty_remote.mkdir()
        _run_git(empty_remote, "init", "--bare", "--initial-branch=main")

        repo = tmp_path / "repo"
        repo.mkdir()
        _run_git(repo, "init", "--initial-branch=main")
        _run_git(repo, "config", "user.email", "x@example.com")
        _run_git(repo, "config", "user.name", "X")
        _run_git(repo, "remote", "add", "origin", str(empty_remote))
        (repo / "f.md").write_text("hi\n")
        _run_git(repo, "add", "f.md")
        _run_git(repo, "commit", "-m", "initial")
        # Note: no ``git push -u`` — upstream tracking is intentionally absent.

        strategy = GitWriteStrategy(enable_pull=True, enable_push=False, repo_path=repo)
        result = strategy.force_pull()

        assert result.applied is False
        assert result.reason == PULL_REASON_NO_REMOTE
        assert result.commits_pulled == 0

    def test_force_pull_rebased_when_divergent_on_different_files(
        self, git_repo_pair: GitRepoPair
    ) -> None:
        """Divergent commits touching different files → plain rebase succeeds.

        Covers the ``PULL_REASON_REBASED`` success path (lines 1273-1282)
        which is not exercised by the conflict-resolution test in
        ``test_git_sync.py`` (that path edits the same file on both sides
        and ends up in the sibling-resolution branch).
        """
        from markdown_vault_mcp.git import (
            PULL_REASON_REBASED,
            GitWriteStrategy,
        )

        # Remote advances on file A.
        _seed_remote_commit(
            git_repo_pair,
            clone_name="clone_rebased",
            file_name="remote_only.md",
            body="remote\n",
        )

        # Local commits a different file B — divergent histories, no overlap.
        (git_repo_pair.local_path / "local_only.md").write_text("local\n")
        _run_git(git_repo_pair.local_path, "add", "local_only.md")
        _run_git(git_repo_pair.local_path, "commit", "-m", "local divergent")

        head_before = _run_git(git_repo_pair.local_path, "rev-parse", "HEAD").strip()
        strategy = GitWriteStrategy(
            enable_pull=True,
            enable_push=False,
            repo_path=git_repo_pair.local_path,
        )
        result = strategy.force_pull()

        assert result.applied is True
        assert result.fast_forward is False
        assert result.reason == PULL_REASON_REBASED
        # HEAD has moved past the original local commit (rebase replays on top).
        assert result.from_sha == head_before
        assert result.to_sha != head_before
        # Both files exist after the rebase.
        assert (git_repo_pair.local_path / "remote_only.md").exists()
        assert (git_repo_pair.local_path / "local_only.md").exists()

    def test_force_push_no_remote_when_upstream_and_origin_head_missing(
        self, tmp_path: Path
    ) -> None:
        """No tracking branch and no ``origin/HEAD`` → ``reason='no_remote'``.

        Mirrors the ``force_pull`` ``no_remote`` test for the push side
        (lines 1334-1351).  ``force_push`` does not call ``git fetch``, so
        an empty bare remote is enough to make both upstream lookups fail.
        """
        from markdown_vault_mcp.git import (
            PUSH_REASON_NO_REMOTE,
            GitWriteStrategy,
        )

        empty_remote = tmp_path / "empty.git"
        empty_remote.mkdir()
        _run_git(empty_remote, "init", "--bare", "--initial-branch=main")

        repo = tmp_path / "repo"
        repo.mkdir()
        _run_git(repo, "init", "--initial-branch=main")
        _run_git(repo, "config", "user.email", "x@example.com")
        _run_git(repo, "config", "user.name", "X")
        _run_git(repo, "remote", "add", "origin", str(empty_remote))
        (repo / "f.md").write_text("hi\n")
        _run_git(repo, "add", "f.md")
        _run_git(repo, "commit", "-m", "initial")
        # No ``git push -u`` — upstream tracking is intentionally absent.

        strategy = GitWriteStrategy(enable_pull=False, enable_push=True, repo_path=repo)
        result = strategy.force_push()

        assert result.applied is False
        assert result.reason == PUSH_REASON_NO_REMOTE
        assert result.commits_pushed == 0
        assert result.hint is not None
        assert "git push -u" in result.hint

    def test_force_push_to_unreachable_remote_returns_push_failed(
        self, git_repo_pair: GitRepoPair
    ) -> None:
        """Generic push failure (not non-ff) → ``reason='push_failed'`` + truncated hint.

        Repoint origin at a non-existent path so ``git push`` fails with a
        connection / lookup error rather than the well-known non-fast-forward
        message.  Covers the error-handling tail of ``force_push`` (lines
        1441-1453).
        """
        from markdown_vault_mcp.git import (
            PUSH_REASON_PUSH_FAILED,
            GitWriteStrategy,
        )

        # Stage a local commit so there's actually something to push.
        (git_repo_pair.local_path / "to_push.md").write_text("payload\n")
        _run_git(git_repo_pair.local_path, "add", "to_push.md")
        _run_git(git_repo_pair.local_path, "commit", "-m", "to push")

        # Re-point origin at a bogus path — ``rev-parse @{upstream}`` still
        # works (tracking metadata remains), but ``git push`` fails.
        _run_git(
            git_repo_pair.local_path,
            "remote",
            "set-url",
            "origin",
            str(git_repo_pair.local_path.parent / "definitely-not-a-repo"),
        )

        strategy = GitWriteStrategy(
            enable_pull=False,
            enable_push=True,
            repo_path=git_repo_pair.local_path,
        )
        result = strategy.force_push()

        assert result.applied is False
        assert result.reason == PUSH_REASON_PUSH_FAILED
        assert result.commits_pushed == 0
        # Hint is a (truncated) excerpt of git's stderr — non-empty.
        assert result.hint is not None
        assert len(result.hint) > 0
        # Hint must not contain the full original (non-truncated) marker if stderr
        # was longer than the cap, but we accept a short stderr too.
        assert len(result.hint) <= 200
