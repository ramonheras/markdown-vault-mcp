"""Unit tests for :meth:`GitWriteStrategy.force_pull` and
:meth:`GitWriteStrategy.force_push` (added in #444).

The bare-remote + local-clone fixture lives in :mod:`tests.fixtures.git`
so the same setup can be reused by future tests for the higher-level
``git_sync`` MCP tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.fixtures.git import _run_git

if TYPE_CHECKING:
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
