"""Git write strategy for auto-commit and push on write operations.

Provides :class:`GitWriteStrategy`, a stateful callback that commits
per-write and defers pushes to a background timer.  Also retains the
legacy :func:`git_write_strategy` factory for backward compatibility.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import os
import stat
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import frontmatter

if TYPE_CHECKING:
    from collections.abc import Callable

from markdown_vault_mcp.exceptions import ConfigurationError
from markdown_vault_mcp.types import CommitDiff, HistoryEntry

logger = logging.getLogger(__name__)


def _is_ssh_remote(url: str) -> bool:
    return url.startswith("git@") or url.startswith("ssh://")


def _normalize_remote(url: str) -> str:
    normalized = url.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[: -len(".git")]
    return normalized


def _build_askpass_env(token: str, username: str) -> dict[str, str]:
    fd, script_path_str = tempfile.mkstemp(suffix=".sh", prefix="git_askpass_")
    script_path = Path(script_path_str)
    os.close(fd)
    script_path.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  *sername*) printf '%s\\n' \"${MVMCP_GIT_USERNAME:-}\" ;;\n"
        "  *) printf '%s\\n' \"${MVMCP_GIT_TOKEN:-}\" ;;\n"
        "esac\n"
    )
    script_path.chmod(stat.S_IRWXU)
    return {
        **os.environ,
        "GIT_ASKPASS": script_path_str,
        "GIT_TERMINAL_PROMPT": "0",
        "MVMCP_GIT_USERNAME": username,
        "MVMCP_GIT_TOKEN": token,
    }


def _find_git_root(path: Path) -> Path | None:
    """Find the git repository root containing *path*.

    Args:
        path: Absolute path to search from.

    Returns:
        The git repository root, or ``None`` if not inside a repo.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path if path.is_dir() else path.parent),
                "rev-parse",
                "--show-toplevel",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


class GitWriteStrategy:
    """Stateful git strategy: commit per write, deferred push.

    On each callback invocation:

    1. Stages the changed file (``git add`` or ``git add -u`` for deletes).
    2. Commits with an auto-generated message (``"operation: path"``).
    3. Resets the push timer — push fires after ``push_delay_s`` of idle.

    Push is deferred to a background ``threading.Timer`` that resets on
    each write.  When the timer fires (no writes for ``push_delay_s``),
    all accumulated local commits are pushed in a single ``git push``.

    On startup, any unpushed local commits (from a previous crash) are
    pushed immediately.

    Args:
        token: PAT for HTTPS push via ``GIT_ASKPASS``.  ``None`` uses
            SSH or pre-configured credentials.
        username: Username used with token auth. Defaults to
            ``"x-access-token"`` (GitHub-compatible).
        repo_url: Remote URL expected in managed mode.
        managed: When ``True``, ensure the repo exists under ``repo_path``:
            clone into an empty directory or validate ``origin`` on existing repos.
        enable_pull: Enable fetch + ff-only sync methods.
        enable_push: Enable deferred push behavior.
        push_delay_s: Seconds of idle before pushing.  ``0`` disables
            the timer (push only on :meth:`close`).
        commit_name: Git committer name; defaults to
            :attr:`DEFAULT_COMMIT_NAME`.
        commit_email: Git committer email; defaults to
            :attr:`DEFAULT_COMMIT_EMAIL`.
        git_lfs: When ``True`` (default), run ``git lfs pull`` during
            lazy initialisation so LFS pointers are resolved before the
            first write is committed.  Requires ``git-lfs`` to be on
            ``PATH``; failures are logged at ERROR and never propagated.
        repo_path: Optional repository path used for startup validation.
            When set together with ``token``, startup raises
            :class:`~markdown_vault_mcp.exceptions.ConfigurationError`
            if ``origin`` uses SSH transport instead of HTTPS.

    Example::

        strategy = GitWriteStrategy(token="ghp_...", push_delay_s=30)
        collection = Collection(on_write=strategy, ...)
        # ... writes happen, push deferred ...
        strategy.close()  # final flush
    """

    #: Default committer name used when none is set in git config or env.
    DEFAULT_COMMIT_NAME = "markdown-vault-mcp"
    #: Default committer email used when none is set in git config or env.
    DEFAULT_COMMIT_EMAIL = "noreply@markdown-vault-mcp"

    def __init__(
        self,
        token: str | None = None,
        username: str = "x-access-token",
        repo_url: str | None = None,
        managed: bool = False,
        enable_pull: bool = True,
        enable_push: bool = True,
        push_delay_s: float = 30.0,
        commit_name: str | None = None,
        commit_email: str | None = None,
        git_lfs: bool = True,
        repo_path: Path | None = None,
    ) -> None:
        # Token is retained for GIT_ASKPASS credential forwarding in subprocesses.
        # This pattern is intentionally accepted and suppressed in CodeQL config.
        self._token = token
        self._username = username
        self._repo_url = repo_url
        self._managed = managed
        self._enable_pull = enable_pull
        self._enable_push = enable_push
        self._push_delay_s = push_delay_s
        self._commit_name = commit_name or self.DEFAULT_COMMIT_NAME
        self._commit_email = commit_email or self.DEFAULT_COMMIT_EMAIL
        self._git_lfs = git_lfs
        self._git_root: Path | None = None
        self._git_root_checked = False
        self._write_init_done = False
        self._push_pending = False
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._pull_stop = threading.Event()
        self._pull_thread: threading.Thread | None = None
        self._pull_interval_s: int = 0
        self._pull_repo_path: Path | None = None
        self._pause_writes: (
            Callable[[], contextlib.AbstractContextManager[None]] | None
        ) = None
        self._on_pull: Callable[[], None] | None = None
        if repo_path is not None:
            if self._managed:
                self._ensure_managed_repo(repo_path)
            else:
                self.validate_startup(repo_path)

    def _git_env(self) -> dict[str, str] | None:
        """Build environment for git subprocess calls.

        When a token is set, reuse the existing GIT_ASKPASS mechanism to avoid
        prompting interactively. This mirrors the push path and keeps the token
        out of command-line arguments.
        """
        if not self._token:
            return None
        return _build_askpass_env(self._token, self._username)

    def _cleanup_git_env(self, env: dict[str, str] | None) -> None:
        if env is None:
            return
        env.pop("MVMCP_GIT_USERNAME", None)
        env.pop("MVMCP_GIT_TOKEN", None)
        script_path_str = env.get("GIT_ASKPASS")
        if not script_path_str:
            return
        with contextlib.suppress(OSError):
            Path(script_path_str).unlink()

    def _ensure_git_root(self, repo_path: Path) -> Path | None:
        if self._git_root_checked:
            return self._git_root
        with self._lock:
            if not self._git_root_checked:
                self._git_root = _find_git_root(repo_path)
                self._git_root_checked = True
        return self._git_root

    def _get_origin_url(self, git_root: Path) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(git_root), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _ensure_managed_repo(self, repo_path: Path) -> None:
        if self._repo_url is None:
            raise ConfigurationError("Managed git mode requires a repo_url.")

        if self._token and _is_ssh_remote(self._repo_url):
            raise ConfigurationError(
                f"Managed mode repo URL {self._repo_url!r} uses SSH transport, but "
                "GIT_TOKEN auth requires HTTPS."
            )

        path = Path(repo_path)
        if path.exists():
            if not path.is_dir():
                raise ConfigurationError(
                    f"Managed mode requires SOURCE_DIR to be a directory: {path}"
                )
            is_empty = not any(path.iterdir())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            is_empty = True

        if is_empty:
            env = self._git_env()
            try:
                subprocess.run(
                    ["git", "clone", self._repo_url, str(path)],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env,
                )
            except FileNotFoundError as exc:
                raise ConfigurationError(
                    "git is not installed or not on PATH."
                ) from exc
            except subprocess.CalledProcessError as exc:
                raise ConfigurationError(
                    f"Failed to clone managed git repo {self._repo_url!r} into {path}: "
                    f"{(exc.stderr or '').strip()}"
                ) from exc
            finally:
                self._cleanup_git_env(env)

        git_root = _find_git_root(path)
        if git_root is None:
            raise ConfigurationError(
                f"Managed mode requires SOURCE_DIR to be empty or a git repository: {path}"
            )
        origin_url = self._get_origin_url(git_root)
        if origin_url is None:
            raise ConfigurationError(
                f"Managed mode requires an 'origin' remote in repository {git_root}."
            )
        if _normalize_remote(origin_url) != _normalize_remote(self._repo_url):
            raise ConfigurationError(
                "Managed mode remote mismatch: existing origin is "
                f"{origin_url!r}, expected {self._repo_url!r}."
            )
        self._git_root = git_root
        self._git_root_checked = True
        self._check_remote_protocol(git_root)

    def _check_remote_protocol(self, git_root: Path) -> None:
        """Raise ConfigurationError if origin uses SSH while token auth is enabled."""
        if not self._token:
            return
        try:
            result = subprocess.run(
                ["git", "-C", str(git_root), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return
        if result.returncode != 0:
            # No remote configured; ignore here.
            return

        url = result.stdout.strip()
        if not _is_ssh_remote(url):
            return

        if url.startswith("ssh://git@"):
            https_url = "https://" + url[len("ssh://git@") :]
        elif url.startswith("ssh://"):
            https_url = "https://" + url[len("ssh://") :]
        else:
            without_prefix = url[len("git@") :]
            https_url = "https://" + without_prefix.replace(":", "/", 1)

        raise ConfigurationError(
            f"Remote URL {url!r} uses SSH transport, but GIT_TOKEN requires HTTPS.\n"
            f"Run: git -C {git_root} remote set-url origin {https_url}"
        )

    def validate_startup(self, repo_path: Path) -> None:
        """Validate startup git settings for token-authenticated workflows."""
        git_root = self._ensure_git_root(repo_path)
        if git_root is None:
            return
        self._check_remote_protocol(git_root)

    def _ensure_write_init(self) -> None:
        """One-time initialisation for the write path (identity/push/LFS)."""
        if self._write_init_done or self._git_root is None:
            return
        with self._lock:
            if self._write_init_done or self._git_root is None:
                return
            self._check_remote_protocol(self._git_root)
            self._check_identity()
            if self._enable_push:
                self._push_if_unpushed()
            # LFS pull runs under the git lock to avoid overlapping git ops.
            # Forward auth credentials so token-protected LFS backends
            # authenticate with the same GIT_ASKPASS mechanism used for push.
            if self._enable_pull or self._enable_push:
                env = self._git_env()
                try:
                    self._lfs_pull(env=env)
                finally:
                    self._cleanup_git_env(env)
            self._write_init_done = True

    def __call__(
        self,
        path: Path,
        content: str,  # noqa: ARG002
        operation: Literal["write", "edit", "delete", "rename"],
    ) -> None:
        """WriteCallback interface: stage + commit, then schedule push."""
        if self._closed:
            return

        self._ensure_git_root(path)
        if self._git_root is None:
            logger.debug(
                "No git repository found for %s; git operations disabled", path
            )
            return

        self._ensure_write_init()

        if self._git_root is None:
            return

        try:
            with self._lock:
                _stage_and_commit(
                    self._git_root,
                    path,
                    operation,
                    commit_name=self._commit_name,
                    commit_email=self._commit_email,
                )
            if self._enable_push:
                self._schedule_push()
        except subprocess.CalledProcessError as exc:
            sanitized_stderr = exc.stderr or ""
            if self._token and self._token in sanitized_stderr:
                sanitized_stderr = sanitized_stderr.replace(self._token, "***")
            logger.error(
                "Git operation failed for %s (%s): command %s returned %d\n%s",
                path,
                operation,
                exc.cmd,
                exc.returncode,
                sanitized_stderr,
            )
        except Exception:
            logger.error(
                "Git operation failed for %s (%s)",
                path,
                operation,
                exc_info=True,
            )

    def _schedule_push(self) -> None:
        """Reset the idle push timer."""
        with self._lock:
            self._push_pending = True
            if self._timer is not None:
                self._timer.cancel()
            if self._push_delay_s > 0:
                self._timer = threading.Timer(self._push_delay_s, self._do_push_safe)
                self._timer.daemon = True
                self._timer.start()

    def _do_push_safe(self) -> None:
        """Push wrapper that catches and logs errors."""
        try:
            self._do_push()
        except subprocess.CalledProcessError as exc:
            sanitized_stderr = exc.stderr or ""
            if self._token and self._token in sanitized_stderr:
                sanitized_stderr = sanitized_stderr.replace(self._token, "***")
            logger.error(
                "Git push failed: command %s returned %d\n%s",
                exc.cmd,
                exc.returncode,
                sanitized_stderr,
            )
        except Exception:
            logger.error("Git push failed", exc_info=True)

    def _do_push(self) -> None:
        """Execute git push and clear pending flag.

        Note: ``_push_pending`` is cleared *before* calling ``_push()``.
        If the push fails, commits are not automatically retried — they
        will be pushed on the next write (which resets ``_push_pending``)
        or on the next startup via ``_push_if_unpushed()``.
        """
        with self._lock:
            if (
                not self._enable_push
                or not self._push_pending
                or self._git_root is None
            ):
                return
            self._push_pending = False

        with self._lock:
            _push(self._git_root, self._token, self._username)
            logger.info("Git: pushed to remote")

    def _check_identity(self) -> None:
        """Warn once at startup if no git committer identity is configured.

        Runs ``git config user.email`` against the repo.  If it returns
        nothing the repo (and global) git config have no identity set, so
        commits will use the identity supplied to this strategy instance.
        """
        if self._git_root is None:
            return
        try:
            result = subprocess.run(
                ["git", "-C", str(self._git_root), "config", "user.email"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return
        if not result.stdout.strip():
            logger.warning(
                "Git: no user.email in git config — commits will use "
                "committer identity '%s <%s>'. Set MARKDOWN_VAULT_MCP_GIT_COMMIT_NAME "
                "and MARKDOWN_VAULT_MCP_GIT_COMMIT_EMAIL to override.",
                self._commit_name,
                self._commit_email,
            )

    def _push_if_unpushed(self) -> None:
        """On startup, push any local commits ahead of the remote."""
        if self._git_root is None or not self._enable_push:
            return

        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self._git_root),
                    "log",
                    "--oneline",
                    "@{upstream}..HEAD",
                ],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            logger.debug("Git: git not found, skipping unpushed check")
            return

        if result.returncode != 0:
            # No upstream or no remote — not an error at startup.
            logger.debug("Git: no upstream to check for unpushed commits")
            return

        if result.stdout.strip():
            logger.info("Git: found unpushed commits on startup, pushing now")
            try:
                _push(self._git_root, self._token, self._username)
            except subprocess.CalledProcessError as exc:
                sanitized_stderr = exc.stderr or ""
                if self._token and self._token in sanitized_stderr:
                    sanitized_stderr = sanitized_stderr.replace(self._token, "***")
                logger.error(
                    "Git startup push failed: command %s returned %d\n%s",
                    exc.cmd,
                    exc.returncode,
                    sanitized_stderr,
                )

    def _lfs_pull(self, env: dict[str, str] | None = None) -> None:
        """Run ``git lfs pull`` to resolve LFS pointers, if LFS is enabled.

        Called during lazy init and after successful ff-only pull ticks
        (:meth:`sync_once`) so LFS pointer files are resolved before reads,
        indexing, and git commits.
        Failures are logged at ERROR and never propagated to the caller.
        """
        if not self._git_lfs or self._git_root is None:
            return
        try:
            result = subprocess.run(
                ["git", "-C", str(self._git_root), "lfs", "pull"],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            logger.info("Git LFS: pulled from remote")
            if result.stdout.strip():
                logger.debug("Git LFS pull output: %s", result.stdout.strip())
        except subprocess.CalledProcessError as exc:
            logger.error(
                "Git LFS pull failed: command %s returned %d\n%s",
                exc.cmd,
                exc.returncode,
                exc.stderr or "",
            )
        except FileNotFoundError:
            logger.error(
                "Git LFS pull failed: git not found on PATH. "
                "Install git or set MARKDOWN_VAULT_MCP_GIT_LFS=false to suppress this error."
            )

    def _resolve_rebase_conflicts(
        self,
        git_root: Path,
        env: dict[str, str] | None,
    ) -> list[tuple[str, str]]:
        """Resolve rebase conflicts by accepting theirs and saving ours.

        Called when ``git rebase @{upstream}`` has stopped at a conflict.
        For each conflicting file, saves the MCP version from
        ``REBASE_HEAD``, then accepts the upstream version via
        ``git checkout --ours``.  Continues the rebase, looping if
        multiple commits conflict.

        Returns:
            A list of ``(relative_path, saved_content)`` tuples for the
            files that had conflicts.  May be partial (not all commits
            resolved) if the iteration limit is hit; the caller is
            responsible for aborting any in-progress rebase before
            writing the conflict files.
        """
        root = str(git_root)
        saved: dict[str, str] = {}
        max_iterations = 50  # safety limit

        for _ in range(max_iterations):
            # Identify conflicting files.
            result = subprocess.run(
                ["git", "-C", root, "diff", "--name-only", "--diff-filter=U"],
                capture_output=True,
                text=True,
                env=env,
            )
            conflicting = [f for f in result.stdout.strip().splitlines() if f]
            if not conflicting:
                # No conflicts — rebase may have stopped for another reason.
                break

            for rel_path in conflicting:
                # Save the MCP version (the commit being rebased).
                show_result = subprocess.run(
                    ["git", "-C", root, "show", f"REBASE_HEAD:{rel_path}"],
                    capture_output=True,
                    text=True,
                    env=env,
                )
                if show_result.returncode == 0:
                    saved[rel_path] = show_result.stdout
                else:
                    logger.warning(
                        "Git pull: could not read MCP version of %s, skipping conflict file",
                        rel_path,
                    )

                # Accept upstream's version.  During rebase, --ours is the
                # branch being rebased onto (upstream), --theirs is the
                # commit being replayed (our local MCP commit).
                subprocess.run(
                    ["git", "-C", root, "checkout", "--ours", "--", rel_path],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", root, "add", "--", rel_path],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=True,
                )

            # Continue the rebase.  If another commit conflicts, the loop
            # iterates again.  ``--no-edit`` avoids opening an editor for
            # any automatically generated merge messages.
            cont = subprocess.run(
                ["git", "-C", root, "rebase", "--continue"],
                capture_output=True,
                text=True,
                env={**(env or {}), "GIT_EDITOR": "true"},
            )
            if cont.returncode == 0:
                # Rebase completed successfully.
                return list(saved.items())
            # returncode != 0 means the next commit also has conflicts —
            # loop around and resolve again.

        # Exhausted iterations or no conflicting files after non-zero continue.
        logger.error(
            "Git pull: conflict resolution loop exceeded %d iterations", max_iterations
        )
        return list(saved.items())

    def _write_conflict_files(
        self,
        git_root: Path,
        saved: list[tuple[str, str]],
        env: dict[str, str] | None,
    ) -> list[str]:
        """Write conflict files and add ``conflict_with`` frontmatter to both sides.

        For each ``(relative_path, content)`` in *saved*:

        1. Write the MCP version as ``<stem>.conflict-mcp-<timestamp><ext>``
           with ``conflict_with`` and ``conflict_date`` frontmatter.
        2. Merge ``conflict_with`` and ``conflict_date`` into the original
           file's existing frontmatter.

        Returns:
            List of conflict file relative paths that were written.
        """
        root = str(git_root)
        now = datetime.datetime.now(tz=datetime.UTC)
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        conflict_date = now.isoformat(timespec="seconds")
        written: list[str] = []

        for rel_path, mcp_content in saved:
            original = Path(rel_path)
            conflict_name = f"{original.stem}.conflict-mcp-{timestamp}{original.suffix}"
            conflict_rel = str(original.parent / conflict_name)

            # --- Write conflict file (MCP version) ---
            try:
                post = frontmatter.loads(mcp_content)
            except Exception:
                # If frontmatter parsing fails, treat as plain content.
                logger.warning(
                    "Git pull: failed to parse frontmatter for conflict file %s; treating as plain content",
                    conflict_rel,
                    exc_info=True,
                )
                post = frontmatter.Post(mcp_content)

            post.metadata["conflict_with"] = rel_path
            post.metadata["conflict_date"] = conflict_date

            conflict_abs = git_root / conflict_rel
            conflict_abs.parent.mkdir(parents=True, exist_ok=True)
            conflict_abs.write_text(frontmatter.dumps(post), encoding="utf-8")

            # --- Update original file with conflict_with frontmatter ---
            original_abs = git_root / rel_path
            if original_abs.exists():
                try:
                    orig_post = frontmatter.loads(
                        original_abs.read_text(encoding="utf-8")
                    )
                except Exception:
                    logger.warning(
                        "Git pull: failed to parse frontmatter for original file %s; treating as plain content",
                        rel_path,
                        exc_info=True,
                    )
                    orig_post = frontmatter.Post(
                        original_abs.read_text(encoding="utf-8")
                    )
                orig_post.metadata["conflict_with"] = conflict_rel
                orig_post.metadata["conflict_date"] = conflict_date
                original_abs.write_text(frontmatter.dumps(orig_post), encoding="utf-8")

            written.append(conflict_rel)

        if not written:
            return written

        # Stage only the files we touched — the original files (updated with
        # conflict_with frontmatter) and the new conflict files.
        paths_to_add = [rel_path for rel_path, _ in saved] + written
        subprocess.run(
            ["git", "-C", root, "add", "--", *paths_to_add],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )

        n = len(written)
        file_list = ", ".join(written)
        commit_result = subprocess.run(
            [
                "git",
                "-C",
                root,
                "-c",
                f"user.name={self._commit_name}",
                "-c",
                f"user.email={self._commit_email}",
                "commit",
                "-m",
                f"conflict: saved {n} MCP version(s) for manual reconciliation\n\n{file_list}",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        if commit_result.returncode != 0:
            logger.error(
                "Git pull: conflict commit failed (rc=%d): %s",
                commit_result.returncode,
                (commit_result.stderr or commit_result.stdout or "").strip(),
            )

        return written

    def sync_once(self, repo_path: Path) -> bool:
        """Fetch and update once, returning True if HEAD advanced.

        Tries fast-forward first; falls back to rebase when the local
        and upstream branches have diverged (e.g. Obsidian and MCP both
        committed on different files).  Aborts on true conflicts.
        """
        if self._closed or not self._enable_pull:
            return False

        git_root = self._ensure_git_root(repo_path)
        if git_root is None:
            return False

        env = None
        try:
            env = self._git_env()
            with self._lock:
                upstream_check = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(git_root),
                        "rev-parse",
                        "--verify",
                        "@{upstream}",
                    ],
                    capture_output=True,
                    text=True,
                    env=env,
                )
                if upstream_check.returncode != 0:
                    logger.info("Git pull: no upstream configured; skipping fetch")
                    return False

                old_head = subprocess.run(
                    ["git", "-C", str(git_root), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env,
                ).stdout.strip()

                subprocess.run(
                    ["git", "-C", str(git_root), "fetch"],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env,
                )

                try:
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(git_root),
                            "merge",
                            "--ff-only",
                            "@{upstream}",
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                        env=env,
                    )
                except subprocess.CalledProcessError as ff_exc:
                    # ff-only failed — the branches have diverged.  Attempt
                    # rebase to replay local MCP commits on top of upstream.
                    # This handles the common case where Obsidian and the MCP
                    # server both committed independently on different files.
                    logger.debug(
                        "Git pull: ff-only failed, attempting rebase: %s",
                        (ff_exc.stderr or "").strip(),
                    )
                    try:
                        subprocess.run(
                            [
                                "git",
                                "-C",
                                str(git_root),
                                "rebase",
                                "@{upstream}",
                            ],
                            capture_output=True,
                            text=True,
                            check=True,
                            env=env,
                        )
                        logger.info(
                            "Git pull: ff-only not possible, rebased local commits onto upstream"
                        )
                    except subprocess.CalledProcessError:
                        # True conflict — resolve by accepting theirs and
                        # saving the MCP version as a conflict file.
                        saved = self._resolve_rebase_conflicts(git_root, env)

                        # Check if a rebase is still in progress (e.g. the
                        # loop exited via break because no conflicting files
                        # were found but rebase --continue had returned
                        # non-zero, or the iteration limit was hit).
                        rebase_head = subprocess.run(
                            [
                                "git",
                                "-C",
                                str(git_root),
                                "rev-parse",
                                "--verify",
                                "REBASE_HEAD",
                            ],
                            capture_output=True,
                            text=True,
                            env=env,
                        )
                        rebase_in_progress = rebase_head.returncode == 0

                        if rebase_in_progress:
                            # Abort the incomplete rebase before committing
                            # conflict files so the working tree is clean.
                            abort_proc = subprocess.run(
                                ["git", "-C", str(git_root), "rebase", "--abort"],
                                capture_output=True,
                                text=True,
                                env=env,
                            )
                            if abort_proc.returncode != 0:
                                logger.error(
                                    "Git pull: failed to abort rebase: %s",
                                    (abort_proc.stderr or "").strip(),
                                )
                            # After abort, the working tree reverts to the
                            # pre-rebase state (MCP commits), so the original
                            # files contain MCP content, not upstream content.
                            # Restore the upstream version for each conflicting
                            # file so _write_conflict_files reads the right side.
                            for rel_path, _ in saved:
                                subprocess.run(
                                    [
                                        "git",
                                        "-C",
                                        str(git_root),
                                        "checkout",
                                        "@{upstream}",
                                        "--",
                                        rel_path,
                                    ],
                                    capture_output=True,
                                    text=True,
                                    env=env,
                                )

                        if saved:
                            written = self._write_conflict_files(git_root, saved, env)
                            for cf in written:
                                logger.warning(
                                    "Git pull: conflict resolved, saved MCP version as %s",
                                    cf,
                                )
                            logger.info(
                                "Git pull: rebase completed with %d conflict file(s)",
                                len(written),
                            )
                        else:
                            # Resolution failed entirely — stay put.
                            logger.warning(
                                "Git pull: conflict resolution failed, skipping"
                            )
                            return False

                new_head = subprocess.run(
                    ["git", "-C", str(git_root), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env,
                ).stdout.strip()

                # Always attempt LFS pull after a successful fetch+ff-only step.
                self._lfs_pull(env=env)

            return old_head != new_head
        except FileNotFoundError:
            logger.info("Git pull: git not found on PATH; pull loop disabled")
            return False
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Git pull: git command failed, skipping: %s",
                (exc.stderr or "").strip(),
            )
            return False
        finally:
            self._cleanup_git_env(env)

    def start(
        self,
        *,
        repo_path: Path,
        pull_interval_s: int,
        pause_writes: Callable[[], contextlib.AbstractContextManager[None]]
        | None = None,
        on_pull: Callable[[], None] | None = None,
    ) -> None:
        """Start a periodic fetch + ff-only update loop in a daemon thread."""
        if self._closed or not self._enable_pull or pull_interval_s <= 0:
            return

        git_root = self._ensure_git_root(repo_path)
        if git_root is None:
            return

        # Guard: do not start the loop if there is no upstream configured.
        # This check is intentionally independent of the sync_once() call in
        # sync_from_remote_before_index() — start() may be called even when
        # the startup sync was skipped (pull_interval_s changed at runtime,
        # or Collection.start() called directly by library users).  The double
        # upstream check is harmless (costs one git subprocess) and avoids
        # noisy "no upstream" logs on every tick.
        env = None
        try:
            env = self._git_env()
            upstream_check = subprocess.run(
                ["git", "-C", str(git_root), "rev-parse", "--verify", "@{upstream}"],
                capture_output=True,
                text=True,
                env=env,
            )
            if upstream_check.returncode != 0:
                logger.info("Git pull: no upstream configured; pull loop disabled")
                return
        except FileNotFoundError:
            logger.info("Git pull: git not found on PATH; pull loop disabled")
            return
        finally:
            self._cleanup_git_env(env)

        with self._lock:
            if self._pull_thread is not None and self._pull_thread.is_alive():
                return
            self._pull_repo_path = repo_path
            self._pull_interval_s = pull_interval_s
            self._pause_writes = pause_writes
            self._on_pull = on_pull
            self._pull_stop.clear()
            self._pull_thread = threading.Thread(
                target=self._pull_loop, name="GitPullLoop", daemon=True
            )
            self._pull_thread.start()

    def _pull_loop(self) -> None:
        repo_path = self._pull_repo_path
        if repo_path is None:
            return

        while not self._pull_stop.is_set():
            try:
                did_advance = self.sync_once(repo_path)
                if did_advance and self._on_pull is not None:
                    pause = self._pause_writes
                    if pause is None:
                        self._on_pull()
                    else:
                        with pause():
                            self._on_pull()
            except Exception:
                logger.exception("Git pull loop tick failed")
            # Wait until the next interval, or stop early.
            if self._pull_stop.wait(timeout=self._pull_interval_s):
                break

    def stop(self) -> None:
        """Stop the pull loop thread if it is running."""
        with self._lock:
            thread = self._pull_thread
            if thread is None:
                return
            self._pull_stop.set()
        # Do not block indefinitely on shutdown.
        thread.join(timeout=5.0)
        with self._lock:
            if self._pull_thread is thread:
                self._pull_thread = None

    def flush(self) -> None:
        """Block until any pending push completes.

        Cancels the idle timer and pushes immediately if there are
        pending local commits.
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            pending = self._push_pending

        if pending and self._git_root is not None:
            self._do_push_safe()

    def close(self) -> None:
        """Cancel timer, flush pending push, mark strategy as closed."""
        self._closed = True
        self.stop()
        self.flush()

    # ------------------------------------------------------------------
    # Read-only git history query methods
    # ------------------------------------------------------------------

    def get_file_history(
        self,
        repo_path: Path,
        path: Path | None,
        since: str | None,
        limit: int,
    ) -> list[HistoryEntry]:
        """Return commits that touched *path* (or the whole vault).

        Args:
            repo_path: Path inside the git repository (used to locate the root).
            path: Absolute path of the file to filter on, or ``None`` for the
                entire vault.
            since: Passed as ``--since`` to ``git log`` (ISO 8601 or git date
                expression such as ``"1 week ago"``).  ``None`` disables the
                filter.
            limit: Maximum number of commits to return (capped at 100).

        Returns:
            List of :class:`HistoryEntry` ordered from newest to oldest.

        Raises:
            subprocess.CalledProcessError: Propagated from git subprocess
                failures (caller should translate to ``ValueError``).
        """
        git_root = self._ensure_git_root(repo_path)
        if git_root is None:
            return []

        limit = min(max(1, limit), 100)

        # \x1e (ASCII Record Separator) is the sentinel used to split commit
        # blocks in the output — it cannot appear in filenames or commit messages.
        _SENTINEL = "\x1e"
        cmd = [
            "git",
            "-C",
            str(git_root),
            "log",
            f"--format={_SENTINEL}%H%x00%h%x00%aI%x00%aN <%aE>%x00%s",
            f"-n{limit}",
        ]
        if since:
            cmd.append(f"--since={since}")
        if path is None:
            # vault-wide: include changed file names in each block
            cmd.append("--name-only")
        else:
            cmd += ["--", str(path)]

        env = self._git_env()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
        finally:
            self._cleanup_git_env(env)

        entries: list[HistoryEntry] = []
        raw = result.stdout
        if not raw.strip():
            return []
        # Split on the sentinel we embedded at the start of each format line.
        # The first element will be empty (output starts with sentinel), so we
        # skip it.  Each remaining block is: header_line\nfile1\nfile2\n
        blocks = raw.split(_SENTINEL)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            if not lines:
                continue
            header = lines[0]
            parts = header.split("\x00")
            if len(parts) < 5:
                continue
            sha, short_sha, timestamp, author, message = parts[:5]
            paths_changed: list[str] = []
            if path is None and len(lines) > 1:
                # vault-wide query: lines[1:] are the changed file paths
                paths_changed = [ln for ln in lines[1:] if ln.strip()]
            entries.append(
                HistoryEntry(
                    sha=sha,
                    short_sha=short_sha,
                    timestamp=timestamp,
                    author=author,
                    message=message,
                    paths_changed=paths_changed,
                )
            )
        return entries

    def get_file_diff(
        self,
        repo_path: Path,
        path: Path,
        ref: str,
        per_commit: bool,
    ) -> str | list[CommitDiff]:
        """Return a unified diff of *path* from *ref* to HEAD.

        Args:
            repo_path: Path inside the git repository.
            path: Absolute path of the file to diff.
            ref: The git ref (SHA or expression) to diff from.
            per_commit: When ``False``, return a single unified diff string.
                When ``True``, return one :class:`CommitDiff` per intervening
                commit.

        Returns:
            A unified diff string when *per_commit* is ``False``, or a list of
            :class:`CommitDiff` when *per_commit* is ``True``.

        Raises:
            ValueError: If *ref* is not found in history.
            subprocess.CalledProcessError: Propagated from git subprocess
                failures (caller should translate to ``ValueError``).
        """
        _DIFF_MAX_BYTES = 50 * 1024  # 50 KB

        git_root = self._ensure_git_root(repo_path)
        if git_root is None:
            if per_commit:
                return []
            return ""

        path_str = str(path)
        env = self._git_env()
        try:
            if not per_commit:
                try:
                    result = subprocess.run(
                        [
                            "git",
                            "-C",
                            str(git_root),
                            "diff",
                            f"{ref}..HEAD",
                            "--",
                            path_str,
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                        env=env,
                    )
                except subprocess.CalledProcessError as exc:
                    raise ValueError(f"Commit {ref!r} not found in history") from exc
                diff = result.stdout
                if len(diff.encode()) > _DIFF_MAX_BYTES:
                    omitted = len(diff.encode()) - _DIFF_MAX_BYTES
                    diff = diff.encode()[:_DIFF_MAX_BYTES].decode(errors="replace")
                    diff += f"\n[diff truncated: {omitted} bytes omitted]"
                return diff

            # per_commit=True: enumerate commits in range then show each
            try:
                log_result = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(git_root),
                        "log",
                        "--format=%H%x00%h%x00%aI%x00%s",
                        f"{ref}..HEAD",
                        "--",
                        path_str,
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env,
                )
            except subprocess.CalledProcessError as exc:
                raise ValueError(f"Commit {ref!r} not found in history") from exc

            diffs: list[CommitDiff] = []
            for line in log_result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                parts = line.split("\x00")
                if len(parts) < 4:
                    continue
                sha, short_sha, timestamp, message = parts[:4]
                show_result = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(git_root),
                        "show",
                        "--format=",
                        "-p",
                        sha,
                        "--",
                        path_str,
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env,
                )
                commit_diff = show_result.stdout
                if len(commit_diff.encode()) > _DIFF_MAX_BYTES:
                    omitted = len(commit_diff.encode()) - _DIFF_MAX_BYTES
                    commit_diff = commit_diff.encode()[:_DIFF_MAX_BYTES].decode(
                        errors="replace"
                    )
                    commit_diff += f"\n[diff truncated: {omitted} bytes omitted]"
                diffs.append(
                    CommitDiff(
                        sha=sha,
                        short_sha=short_sha,
                        timestamp=timestamp,
                        message=message,
                        diff=commit_diff,
                    )
                )
            return diffs
        finally:
            self._cleanup_git_env(env)


def git_write_strategy(
    token: str | None = None,
    push_delay_s: float = 0,
    git_lfs: bool = True,
) -> GitWriteStrategy:
    """Create a :class:`GitWriteStrategy` callback.

    Convenience wrapper around :class:`GitWriteStrategy`.  With the
    default ``push_delay_s=0``, commits happen per-write but push only
    fires when :meth:`~GitWriteStrategy.close` or
    :meth:`~GitWriteStrategy.flush` is called.

    When used via :class:`~markdown_vault_mcp.collection.Collection`,
    ``Collection.close()`` automatically calls the strategy's
    ``close()``, so pushes flush on shutdown.  Callers using this
    as a bare ``WriteCallback`` must retain a reference and call
    ``close()`` explicitly.

    .. deprecated::
        Prefer :class:`GitWriteStrategy` directly for access to
        :meth:`~GitWriteStrategy.flush` and :meth:`~GitWriteStrategy.close`.

    .. note::
        The default ``push_delay_s=0`` here differs from
        :class:`GitWriteStrategy`'s default of ``30.0``.  This preserves
        backward compatibility (push on close/flush only).

    Args:
        token: PAT for HTTPS push.
        push_delay_s: Push delay in seconds (default 0 = push on close only).
        git_lfs: When ``True`` (default), run ``git lfs pull`` during init.

    Returns:
        A :class:`GitWriteStrategy` instance (also satisfies
        :data:`~markdown_vault_mcp.types.WriteCallback`).
    """
    return GitWriteStrategy(token=token, push_delay_s=push_delay_s, git_lfs=git_lfs)


def _stage_and_commit(
    git_root: Path,
    path: Path,
    operation: Literal["write", "edit", "delete", "rename"],
    commit_name: str = GitWriteStrategy.DEFAULT_COMMIT_NAME,
    commit_email: str = GitWriteStrategy.DEFAULT_COMMIT_EMAIL,
) -> None:
    """Stage and commit a single file change (no push).

    Args:
        git_root: Git repository root.
        path: Absolute path to the changed file.
        operation: The write operation type.
        commit_name: Git committer name (overrides git config).
        commit_email: Git committer email (overrides git config).
    """
    root = str(git_root)

    # Stage the change.
    if operation == "delete":
        # File already removed from disk; stage the deletion.
        subprocess.run(
            ["git", "-C", root, "add", "-u", "--", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
    elif operation == "rename":
        # For rename, the old file has been moved on disk.  Stage tracked
        # deletions (-u) to capture the old path removal, then add the new
        # file explicitly.
        # NOTE: ``git add -u`` without a pathspec stages ALL tracked
        # modifications/deletions repo-wide.  In a vault with other
        # uncommitted edits, this may sweep unrelated changes into the
        # auto-commit.  Additionally, if the old file was never committed
        # to git (e.g. written directly by Obsidian and not via this
        # callback), ``git add -u`` will not record its deletion at all —
        # the commit will only add the new path.
        # A future improvement would extend the callback signature to
        # pass both old and new paths, enabling scoped staging.
        subprocess.run(
            ["git", "-C", root, "add", "-u"],
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", root, "add", "--", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
    else:
        subprocess.run(
            ["git", "-C", root, "add", "--", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )

    # Generate commit message from operation and relative path.
    try:
        rel_path = path.relative_to(git_root)
    except ValueError:
        rel_path = path

    # Skip commit if staging produced no diff (e.g. writing identical content).
    check_result = subprocess.run(
        ["git", "-C", root, "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if check_result.returncode == 0:
        logger.debug(
            "Git: nothing staged for %s (%s), skipping commit", rel_path, operation
        )
        return

    commit_msg = f"{operation}: {rel_path}"

    subprocess.run(
        [
            "git",
            "-C",
            root,
            "-c",
            f"user.name={commit_name}",
            "-c",
            f"user.email={commit_email}",
            "commit",
            "-m",
            commit_msg,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    logger.info("Git: committed %s (%s)", rel_path, operation)


def _push(git_root: Path, token: str | None, username: str = "x-access-token") -> None:
    """Push to the default remote, using GIT_ASKPASS for token auth.

    When a token is supplied a temporary helper script is written to a
    private temporary file (mode 0o700).  Git reads credentials from this
    script via ``GIT_ASKPASS`` so the token is never present in any
    process's command-line arguments and is therefore not visible in
    ``/proc/<pid>/cmdline``.  The script is deleted in a ``finally`` block
    regardless of push outcome.

    Args:
        git_root: Git repository root.
        token: Optional PAT for HTTPS push.  If ``None``, relies on SSH
            keys or pre-configured git credentials.
        username: Username used for HTTPS auth prompts when *token* is set.
    """
    root = str(git_root)

    # Always push to "origin".  If the remote is named differently,
    # configure a git remote alias or adjust this constant.
    if not token:
        subprocess.run(
            ["git", "-C", root, "push", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        return

    env = _build_askpass_env(token, username)
    script_path_str = env["GIT_ASKPASS"]
    script_path = Path(script_path_str)
    try:
        subprocess.run(
            ["git", "-C", root, "push", "origin"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    finally:
        with contextlib.suppress(OSError):
            script_path.unlink()
