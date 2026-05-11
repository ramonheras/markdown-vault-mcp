"""Pytest fixtures for tests that need a real git repository.

Provides:
- :class:`GitRepoPair`: a small named tuple bundling the bare-remote and
  local-clone paths produced by :func:`git_repo_pair`.
- :func:`git_repo_pair`: a function-scoped fixture creating a fresh bare
  "remote" + local clone with one initial commit on ``main``.

Both pieces are intentionally minimal so they can be reused for any future
git-tool tests (force-pull, force-push, conflict resolution, etc.).  Every
invocation gets its own ``tmp_path`` so tests do not pollute each other.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, NamedTuple

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class GitRepoPair(NamedTuple):
    """A bare 'remote' repo plus a local clone of it.

    Attributes:
        remote_path: Filesystem path to the bare repository acting as the
            upstream.  Pass this as ``origin`` when constructing additional
            clones in tests.
        local_path: Filesystem path to the local working clone.  Has one
            initial commit on ``main`` already pushed to ``origin``.
    """

    remote_path: Path
    local_path: Path


def _run_git(cwd: Path, *args: str) -> str:
    """Run a git command synchronously and return stdout.

    Args:
        cwd: Working directory for the git command.
        *args: Arguments passed to ``git`` (do not include the ``git``
            executable itself).

    Returns:
        Captured stdout from the git command.

    Raises:
        subprocess.CalledProcessError: If the command exits non-zero.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


@pytest.fixture
def git_repo_pair(tmp_path: Path) -> GitRepoPair:
    """Set up a bare 'remote' + local clone with one initial commit on main.

    The local clone has ``origin`` pointing at the bare remote and an
    upstream tracking branch (``main`` → ``origin/main``) established via
    ``git push -u``.

    Returns:
        :class:`GitRepoPair` with both paths populated.
    """
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    remote.mkdir()
    _run_git(remote, "init", "--bare", "--initial-branch=main")

    local.mkdir()
    _run_git(local, "init", "--initial-branch=main")
    _run_git(local, "config", "user.email", "test@example.com")
    _run_git(local, "config", "user.name", "Test User")
    _run_git(local, "remote", "add", "origin", str(remote))

    # Initial commit so HEAD exists on both sides.
    (local / "README.md").write_text("# Test\n")
    _run_git(local, "add", "README.md")
    _run_git(local, "commit", "-m", "initial")
    _run_git(local, "push", "-u", "origin", "main")

    return GitRepoPair(remote_path=remote, local_path=local)
