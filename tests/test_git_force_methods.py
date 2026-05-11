"""Unit tests for :meth:`GitWriteStrategy.force_pull` (added in #444).

The bare-remote + local-clone fixture lives in :mod:`tests.fixtures.git`
so the same setup can be reused by future tests for ``force_push`` and
the higher-level ``git_sync`` MCP tool.
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
