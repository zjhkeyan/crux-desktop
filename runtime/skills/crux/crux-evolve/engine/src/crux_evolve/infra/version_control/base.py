"""Abstract base class for version control systems."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from crux_evolve.utils.registry import Registrable


class WorktreeInfo(BaseModel):
    """Information about a worktree.

    Attributes:
        name: Unique name of the worktree
        path: Filesystem path to the worktree directory
        branch: Name of the associated git branch
        commit_hash: Current HEAD commit hash
        is_locked: Whether the worktree is locked from automatic cleanup
        created_at: Creation timestamp (Unix time)
        last_used_at: Last used timestamp (Unix time)
    """

    name: str
    path: str
    branch: str
    commit_hash: str
    is_locked: bool = False
    created_at: float
    last_used_at: float


class VersionControlResult(BaseModel):
    """Result of a version control operation.

    Attributes:
        success: Whether the operation succeeded
        message: Human-readable status message
        data: Additional operation-specific data
        error: Error message if operation failed
    """

    success: bool
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class BaseVersionControl(Registrable, ABC):
    """Abstract base class for version control systems.

    Provides interface for managing isolated workspaces for algorithm evolution,
    tracking changes, and managing lifecycle of versioned resources.
    """

    def __init__(self, config: dict[str, Any], base_dir: Path):
        """Initialize version control system.

        Args:
            config: Version control configuration
            base_dir: Base directory for the run (worktrees will be created at
                {base_dir}/worktrees)
        """
        pass

    @abstractmethod
    def initialize(self) -> VersionControlResult:
        """Initialize version control repository if it doesn't exist.

        Checks if a repository already exists at the workspace root. If not,
        initializes a new one with appropriate ignore patterns and initial commit.

        Returns:
            Operation result with initialization status
        """
        pass

    @abstractmethod
    def add_worktree(self, worktree: WorktreeInfo) -> None:
        """Add an existing worktree to metadata.

        This is used when a worktree is created outside of this class (e.g. by
        the planner) and we want to track it in our metadata.

        Args:
            worktree: WorktreeInfo object representing the worktree to add
        """
        pass

    @abstractmethod
    def create_worktree(
        self,
        name: str,
        base_commit: str | None = None,
        base_branch: str | None = None,
    ) -> VersionControlResult:
        """Create an isolated worktree for algorithm development.

        Creates a new branch and associated worktree directory where code
        modifications can be made without affecting the main repository or
        other worktrees.

        Args:
            name: Unique name for the worktree (will be used as directory name)
            base_commit: Optional commit hash to base the worktree on
            base_branch: Optional branch name to base the worktree on

        Returns:
            Operation result with worktree information
        """
        pass

    @abstractmethod
    def commit_changes(
        self,
        worktree: WorktreeInfo,
        message: str,
        author: str | None = None,
    ) -> VersionControlResult:
        """Commit all changes in a worktree.

        Stages and commits all modifications in the specified worktree,
        creating a new version snapshot.

        Args:
            worktree: the worktree to commit
            message: Commit message describing the changes
            author: Optional commit author information

        Returns:
            Operation result with commit information
        """
        pass

    @abstractmethod
    def delete_worktree(
        self,
        worktree: WorktreeInfo,
        force: bool = False,
    ) -> VersionControlResult:
        """Delete a worktree and its associated branch.

        Removes the worktree directory and deletes the corresponding branch
        from the repository.

        Args:
            worktree: WorktreeInfo of the worktree to delete.
            force: If True, delete even if there are uncommitted changes.

        Returns:
            Operation result with deletion status
        """
        pass

    @abstractmethod
    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all existing worktrees.

        Returns:
            List of worktree information objects
        """
        pass

    @abstractmethod
    def cleanup_old_resources(
        self,
        max_age_days: float | None = None,
        max_worktrees: int | None = None,
    ) -> VersionControlResult:
        """Clean up old worktrees and branches to manage disk space.

        Removes worktrees that exceed the specified age limit or when the total
        number of worktrees exceeds the maximum allowed. Preserves worktrees
        that are marked as locked or recently used.

        Args:
            max_age_days: Maximum age of worktrees to keep (in days).
                If None, use the value from configuration.
            max_worktrees: Maximum number of worktrees to keep.
                If None, use the value from configuration.

        Returns:
            Operation result with cleanup statistics
        """
        pass

    @abstractmethod
    def get_worktree_path(self, worktree_name: str) -> Path | None:
        """Get the filesystem path of a worktree.

        Args:
            worktree_name: Name of the worktree

        Returns:
            Path to worktree directory if it exists, None otherwise
        """
        pass

    @abstractmethod
    def lock_worktree(
        self,
        worktree_name: str,
        reason: str = "",
    ) -> VersionControlResult:
        """Mark a worktree as locked to prevent automatic cleanup.

        Args:
            worktree_name: Name of the worktree to lock
            reason: Optional reason for locking

        Returns:
            Operation result with lock status
        """
        pass

    @abstractmethod
    def unlock_worktree(
        self,
        worktree_name: str,
    ) -> VersionControlResult:
        """Unlock a worktree to allow automatic cleanup.

        Args:
            worktree_name: Name of the worktree to unlock

        Returns:
            Operation result with unlock status
        """
        pass

    @abstractmethod
    def get_changed_files(
        self,
        commit_hash: str,
    ) -> list[dict[str, str]]:
        """Get changed files for a specific commit.

        Args:
            commit_hash: The commit hash to get changes for

        Returns:
            List of dictionaries containing file_path and diff content
        """
        pass
