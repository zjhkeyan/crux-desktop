"""Version control module for tracking algorithm evolution.

This module provides version control functionality for isolating and tracking
code changes during algorithm evolution. It supports Git-based worktree
management for isolated workspaces and automatic cleanup of old resources.
"""

from .base import (
    BaseVersionControl,
    VersionControlResult,
    WorktreeInfo,
)
from .config import VersionControlConfig
from .git_worktree import GitWorktreeVersionControl

__all__ = [
    "BaseVersionControl",
    "WorktreeInfo",
    "VersionControlResult",
    "VersionControlConfig",
    "GitWorktreeVersionControl",
]
