"""Git worktree management for task isolation."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from git import Repo
from git.exc import GitCommandError

if TYPE_CHECKING:
    from fugu_vibe.config import Config

logger = structlog.get_logger()


class GitWorktreeManager:
    """
    Manages git worktrees for isolated task execution.

    Each task gets its own worktree (branch + directory) allowing
    parallel task execution without conflicts.
    """

    def __init__(self, config: Config):
        self.config = config.tasks
        self._repo: Repo | None = None
        self._repo_root: Path | None = None
        self._worktrees: dict[str, str] = {}  # task_id → path

    def initialize(self) -> None:
        """Find or initialize git repository."""
        try:
            self._repo = Repo(search_parent_directories=True)
            self._repo_root = Path(self._repo.working_dir)
            logger.info("git_repo_found", root=str(self._repo_root))
        except Exception:
            # Create temp repo
            self._repo_root = Path(tempfile.mkdtemp(prefix="fugu-vibe-"))
            self._repo = Repo.init(self._repo_root)
            logger.warning("no_git_repo_found", using_temp=str(self._repo_root))

    def create_worktree(self, task_id: str, task_name: str) -> str:
        """
        Create a new worktree for a task.

        Returns:
            Absolute path to the worktree directory.
        """
        if not self._repo:
            self.initialize()

        branch_name = f"{self.config.worktree_prefix}-{task_id}"

        if self._repo_root and self._repo:
            # Create worktree directory
            worktree_dir = self._repo_root / ".fugu-worktrees" / task_id
            worktree_dir.parent.mkdir(parents=True, exist_ok=True)

            try:
                # Create branch from default branch
                default = self.config.git_default_branch
                if hasattr(self._repo.heads, default):
                    base = getattr(self._repo.heads, default)
                else:
                    base = self._repo.head.commit

                self._repo.create_head(branch_name, base)

                # Create worktree
                self._repo.git.worktree("add", str(worktree_dir), branch_name)
                self._worktrees[task_id] = str(worktree_dir)

                logger.info(
                    "worktree_created",
                    task_id=task_id,
                    branch=branch_name,
                    path=str(worktree_dir),
                )

                return str(worktree_dir)

            except GitCommandError as e:
                logger.error("worktree_creation_failed", error=str(e))

        # Fallback: temp directory
        fallback = tempfile.mkdtemp(prefix=f"fugu-{task_id}-")
        self._worktrees[task_id] = fallback
        return fallback

    def remove_worktree(self, task_id: str) -> bool:
        """Remove a task's worktree."""
        path = self._worktrees.get(task_id)
        if not path:
            return False

        try:
            if self._repo:
                self._repo.git.worktree("remove", path, force=True)

            del self._worktrees[task_id]
            logger.info("worktree_removed", task_id=task_id)
            return True

        except GitCommandError as e:
            logger.error("worktree_removal_failed", error=str(e))
            return False

    def merge_worktree(self, task_id: str) -> bool:
        """Merge a completed task's worktree back to main."""
        if not self._repo or not self.config.auto_merge:
            return False

        path = self._worktrees.get(task_id)
        if not path:
            return False

        branch_name = f"{self.config.worktree_prefix}-{task_id}"

        try:
            # Switch to main and merge
            default = self.config.git_default_branch
            main = getattr(self._repo.heads, default)
            self._repo.head.reference = main

            self._repo.git.merge(
                branch_name,
                no_ff=True,
                m=f"Merge fugu task: {task_id}",
            )

            # Clean up
            self.remove_worktree(task_id)

            logger.info("worktree_merged", task_id=task_id, branch=branch_name)
            return True

        except GitCommandError as e:
            logger.error("worktree_merge_failed", task_id=task_id, error=str(e))
            return False

    def list_worktrees(self) -> dict[str, str]:
        """List all active worktrees."""
        return self._worktrees.copy()
