"""Version control configuration models."""

from typing import Literal

from pydantic import BaseModel, Field

from crux_evolve.config.ui import ui


class VersionControlConfig(BaseModel):
    """Version control configuration.

    Configures the version control system for tracking algorithm changes
    and managing isolated workspaces.
    """

    enabled: bool = Field(
        default=True,
        description="Enable version control",
        json_schema_extra=ui(
            label_zh="启用", label_en="Enabled",
            desc_zh="是否启用版本控制系统来跟踪算法变更",
            desc_en="Whether to enable version control for tracking algorithm changes",
        ),
    )
    type: Literal["git_worktree", "none"] = Field(
        default="git_worktree",
        description="Version control implementation type",
        json_schema_extra=ui(
            label_zh="类型", label_en="Type",
            desc_zh="版本控制实现类型：git_worktree（Git 工作树隔离）或 none（禁用）",
            desc_en="Version control type: git_worktree (Git worktree isolation) or none (disabled)",
        ),
    )
    local_path: str | None = Field(
        default=None,
        description="Path to local code repository on disk",
        json_schema_extra=ui(
            user_required=True,
            label_zh="本地仓库路径", label_en="Local Path",
            desc_zh="本地代码仓库的磁盘路径，用于创建隔离工作空间",
            desc_en="Local code repository path on disk, used to create isolated workspaces",
        ),
    )
    remote_url: str | None = Field(
        default=None,
        description="Remote Git URL to clone from (e.g., https://github.com/user/repo.git)",
        json_schema_extra=ui(
            label_zh="远程仓库地址", label_en="Remote URL",
            desc_zh="远程 Git 仓库 URL，用于克隆代码（如 https://github.com/user/repo.git）",
            desc_en="Remote Git URL to clone from (e.g., https://github.com/user/repo.git)",
        ),
    )
    revision: str | None = Field(
        default=None,
        description="Git revision (branch name, commit hash, or tag) to check out when cloning",
        json_schema_extra=ui(
            label_zh="Git 版本", label_en="Revision",
            desc_zh="克隆时检出的 Git 版本：分支名、提交哈希或标签",
            desc_en="Git revision to check out when cloning: branch name, commit hash, or tag",
        ),
    )
    auto_initialize: bool = Field(
        default=True,
        description="Automatically initialize repository if it doesn't exist (only for local_path)",
        json_schema_extra=ui(
            label_zh="自动初始化", label_en="Auto Initialize",
            desc_zh="当本地仓库不存在时是否自动初始化（仅对 local_path 生效）",
            desc_en="Automatically initialize the repository if it doesn't exist (only for local_path)",
        ),
    )
    auto_cleanup: bool = Field(
        default=True,
        description="Automatically clean up old worktrees",
        json_schema_extra=ui(
            label_zh="自动清理", label_en="Auto Cleanup",
            desc_zh="是否自动清理过期的 Git 工作树", desc_en="Whether to automatically clean up expired Git worktrees",
        ),
    )
    max_worktree_age_days: float = Field(
        default=7.0,
        ge=0.0,
        description="Maximum age of worktrees before automatic cleanup (in days)",
        json_schema_extra=ui(
            label_zh="工作树最大保留天数", label_en="Max Worktree Age (days)",
            desc_zh="工作树超过此天数后将被自动清理", desc_en="Worktrees older than this many days are automatically cleaned up",
        ),
    )
    max_worktrees: int = Field(
        default=100,
        ge=1,
        description="Maximum number of worktrees to keep",
        json_schema_extra=ui(
            label_zh="最大工作树数量", label_en="Max Worktrees",
            desc_zh="允许同时保留的最大工作树数量", desc_en="Maximum number of worktrees to keep simultaneously",
        ),
    )
    default_branch: str = Field(
        default="main",
        description="Default branch name for new repositories",
        json_schema_extra=ui(
            label_zh="默认分支", label_en="Default Branch",
            desc_zh="新建仓库时使用的默认分支名称", desc_en="Default branch name when initializing new repositories",
        ),
    )
    commit_message_template: str = Field(
        default="Algorithm {algorithm_id}: {description}",
        description="Template for commit messages",
        json_schema_extra=ui(
            hidden=True,
            label_zh="提交信息模板", label_en="Commit Message Template",
            desc_zh="提交信息模板，支持 {algorithm_id} 和 {description} 占位符",
            desc_en="Commit message template with {algorithm_id} and {description} placeholders",
        ),
    )
