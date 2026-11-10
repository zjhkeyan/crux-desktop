"""Git worktree based version control implementation."""

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from loguru import logger

from .base import (
    BaseVersionControl,
    VersionControlResult,
    WorktreeInfo,
)
from .config import VersionControlConfig


@BaseVersionControl.register("git_worktree")
class GitWorktreeVersionControl(BaseVersionControl):
    """Git worktree based version control implementation.

    Uses git worktrees to provide isolated development environments for
    algorithm evolution. Each worktree is associated with a unique branch,
    allowing concurrent modification and independent version tracking.

    Worktrees are always created at {base_dir}/worktrees, where base_dir is
    the run's base directory. This ensures proper isolation between different
    runs and automatic cleanup when the run completes.
    """

    def __init__(self, config: dict[str, Any], base_dir: Path):
        """Initialize Git worktree version control.

        Args:
            config: Version control configuration dictionary
            base_dir: Base directory for the run (worktrees go here)
        """
        self.config = VersionControlConfig(**config)
        self.base_dir = Path(base_dir).resolve()

        # Worktrees are always created at base_dir/worktrees
        self.worktree_root = self.base_dir / "worktrees"
        self.worktree_root.mkdir(parents=True, exist_ok=True)

        self._metadata_file = self.worktree_root / "worktree_metadata.json"
        self._metadata = self._load_metadata()

        # Handle code repository configuration
        if self.config.remote_url is not None:
            # Clone remote repository
            self._git_root = self._clone_remote_repository()
        elif self.config.local_path is not None:
            # Use local repository
            local_path = Path(self.config.local_path).resolve()
            self._git_root = self._prepare_local_repository(local_path)
        else:
            # Auto-detect by traversing upwards
            self._git_root = self._find_git_root(self.base_dir)

        # Ensure we have a git repository
        if not self._is_git_repo(self._git_root):
            if self.config.auto_initialize:
                self._initialize_git_repository()
            else:
                raise ValueError(
                    f"No git repository found at {self._git_root}. "
                    "Set auto_initialize=True to automatically initialize an empty repository."
                )

    def _find_git_root(self, start_path: Path) -> Path:
        """Find the git repository root by traversing upwards.

        Args:
            start_path: Starting path to search from

        Returns:
            Path to the git repository root
        """
        current = start_path
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        # If no .git found, use the base directory (we'll initialize later)
        return start_path

    def _is_git_repo(self, path: Path) -> bool:
        """Check if the path is a git repository.

        Args:
            path: Path to check.

        Returns:
            True if this is a git repository (has .git directory), False otherwise.
        """
        return (path / ".git").exists()

    def _clone_remote_repository(self) -> Path:
        """Clone the remote repository from configuration.

        The repository is cloned into {base_dir}/repo directory.

        Returns:
            Path to the cloned repository.

        Raises:
            RuntimeError: If clone fails.
        """
        repo_dir = self.base_dir / "repo"
        if repo_dir.exists():
            # Already cloned
            return repo_dir

        url = self.config.remote_url
        assert url is not None
        revision = self.config.revision or self.config.default_branch

        self.worktree_root.parent.mkdir(parents=True, exist_ok=True)

        # Clone the repository
        clone_args = ["clone", "--depth=1"]
        if revision:
            clone_args.extend(["--branch", revision])
        clone_args.extend([url, str(repo_dir)])

        code, stdout, stderr = self._run_git_command(clone_args, cwd=self.worktree_root.parent)
        if code != 0:
            raise RuntimeError(f"Failed to clone remote repository: {stderr}")

        return repo_dir

    def _prepare_local_repository(self, local_path: Path) -> Path:
        """Prepare a local repository.

        If the local path doesn't exist or isn't a git repo, we'll either
        initialize it (if auto_initialize=True) or raise an error.

        Args:
            local_path: Path to local repository.

        Returns:
            Path to the prepared repository.
        """
        if not local_path.exists():
            local_path.mkdir(parents=True, exist_ok=True)

        return local_path

    def _initialize_git_repository(self) -> None:
        """Initialize an empty git repository at _git_root."""
        # Initialize git
        code, _, stderr = self._run_git_command(["init"], cwd=self._git_root)
        if code != 0:
            raise RuntimeError(f"Failed to initialize git repository: {stderr}")

        # Configure user
        self._run_git_command(["config", "user.name", "CruxEvolve"], cwd=self._git_root)
        self._run_git_command(["config", "user.email", "crux_evolve@example.com"], cwd=self._git_root)

        # Check if we have any actual files to commit (excluding .git and worktrees)
        has_committable_files = False
        for entry in self._git_root.iterdir():
            if entry.name not in [".git", "worktrees"]:
                has_committable_files = True
                break

        if not has_committable_files:
            # Create an initial README file
            readme = self._git_root / "README.md"
            readme.write_text(
                "# Code Repository for CruxEvolve Evolution\n\n"
                "This repository is managed by CruxEvolve for algorithm evolution.\n"
            )

        # Create initial commit
        self._run_git_command(["add", "."], cwd=self._git_root)
        # Only commit if there are changes, ignore errors when nothing to commit
        self._run_git_command(["commit", "-m", "Initial commit by CruxEvolve"], cwd=self._git_root)

    def _run_git_command(
        self,
        args: list[str],
        cwd: Path | None = None,
    ) -> tuple[int, str, str]:
        """Run a git command and return the result.

        Args:
            args: Command arguments (excluding 'git')
            cwd: Working directory for the command

        Returns:
            Tuple of (returncode, stdout, stderr)
        """
        cmd = ["git"] + args
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or self._git_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            return (result.returncode, result.stdout, result.stderr)
        except Exception as e:
            return (-1, "", str(e))

    def _load_metadata(self) -> dict[str, Any]:
        """Load worktree metadata from disk.

        Returns:
            Loaded metadata dictionary
        """
        if self._metadata_file.exists():
            try:
                with open(self._metadata_file, encoding="utf-8") as f:
                    result: dict[str, Any] = json.load(f)
                    return result
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def _save_metadata(self) -> None:
        """Save worktree metadata to disk."""
        with open(self._metadata_file, "w", encoding="utf-8") as f:
            json.dump(self._metadata, f, indent=2)

    def initialize(self) -> VersionControlResult:
        """Initialize git repository if it doesn't exist.

        Returns:
            Operation result with initialization status
        """
        git_dir = self._git_root / ".git"
        if git_dir.exists():
            return VersionControlResult(
                success=True,
                message="Git repository already exists",
                data={"already_initialized": True},
            )

        # Initialize git repo
        returncode, stdout, stderr = self._run_git_command(["init"])
        if returncode != 0:
            return VersionControlResult(
                success=False,
                message="Failed to initialize git repository",
                error=stderr,
            )

        # Set default branch
        self._run_git_command(["checkout", "-b", self.config.default_branch])

        # Create .gitignore for CruxEvolve artifacts
        gitignore_path = self._git_root / ".gitignore"
        if not gitignore_path.exists():
            gitignore_content = """
# CruxEvolve generated files
*.pyc
__pycache__/
*.pyo
*.pyd
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
*.swp
*.bak
*.swo
*~
            """.strip() + "\n"
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(gitignore_content)

        # Initial commit
        self._run_git_command(["add", "."])
        self._run_git_command(
            [
                "commit",
                "-m",
                "Initial commit from CruxEvolve",
                "--author",
                "CruxEvolve <noreply@crux_evolve.dev>",
            ]
        )

        return VersionControlResult(
            success=True,
            message="Git repository initialized successfully",
            data={"already_initialized": False},
        )

    def create_worktree(
        self,
        name: str,
        base_commit: str | None = None,
        base_branch: str | None = None,
    ) -> VersionControlResult:
        """Create a new git worktree.

        Args:
            name: Unique name for the worktree
            base_commit: Optional base commit hash
            base_branch: Optional base branch name

        Returns:
            Operation result with worktree information
        """
        worktree_path = self.worktree_root / name
        branch_name = f"crux_evolve/{name}"

        if worktree_path.exists():
            # Get commit hash even though worktree already exists
            commit_hash = ""
            if worktree_path.exists():
                returncode, ch, _ = self._run_git_command(
                    ["rev-parse", "HEAD"],
                    cwd=worktree_path,
                )
                if returncode == 0:
                    commit_hash = ch.strip()

            # Create WorktreeInfo
            worktree_info = WorktreeInfo(
                name=name,
                path=str(worktree_path),
                branch=branch_name,
                commit_hash=commit_hash,
                is_locked=(
                    self._metadata[name].get("is_locked", False)
                    if name in self._metadata
                    else False
                ),
                created_at=(
                    self._metadata[name].get("created_at", time.time())
                    if name in self._metadata
                    else time.time()
                ),
                last_used_at=(
                    self._metadata[name].get("last_used_at", time.time())
                    if name in self._metadata
                    else time.time()
                ),
            )

            return VersionControlResult(
                success=False,
                message=f"Worktree {name} already exists",
                error="Worktree directory already exists",
                data={
                    "worktree": worktree_info,
                },
            )

        # Check if init git repo
        head_returncode, _, _ = self._run_git_command(
            ["rev-parse", "--verify", "HEAD^{commit}"],
        )
        if head_returncode != 0:
            return VersionControlResult(
                success=False,
                message=f"Failed to create worktree {name}",
                error=f"Cannot create worktree: because the repository has no commits yet. "
                      f"Please make an initial commit in {self._git_root} first.",
            )

        # Determine base reference
        base_ref = base_branch or base_commit or self.config.default_branch

        # Check if base_ref exists
        check_returncode, _, _ = self._run_git_command(
            ["rev-parse", "--verify", base_ref + "^{commit}"]
        )
        if check_returncode != 0:
            # If the default branch doesn't exist, use HEAD instead
            # This can happen when the repository has just been initialized with no commits
            base_ref = "HEAD"

        # Create worktree with new branch
        returncode, stdout, stderr = self._run_git_command(
            [
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
                base_ref,
            ]
        )

        if returncode != 0:
            return VersionControlResult(
                success=False,
                message=f"Failed to create worktree {name}",
                error=stderr,
            )

        # Store metadata
        current_time = time.time()
        self._metadata[name] = {
            "name": name,
            "branch": branch_name,
            "path": str(worktree_path),
            "created_at": current_time,
            "last_used_at": current_time,
            "is_locked": False,
            "lock_reason": "",
        }
        self._save_metadata()

        # Get current commit hash
        commit_hash = ""
        returncode, ch, _ = self._run_git_command(
            ["rev-parse", "HEAD"],
            cwd=worktree_path,
        )
        if returncode == 0:
            commit_hash = ch.strip()

        # Create WorktreeInfo
        worktree_info = WorktreeInfo(
            name=name,
            path=str(worktree_path),
            branch=branch_name,
            commit_hash=commit_hash,
            is_locked=False,
            created_at=current_time,
            last_used_at=current_time,
        )

        return VersionControlResult(
            success=True,
            message=f"Worktree {name} created successfully",
            data={
                "worktree": worktree_info,
            },
        )

    def commit_changes(
        self,
        worktree: WorktreeInfo,
        message: str,
        author: str | None = None,
    ) -> VersionControlResult:
        """Commit changes in a worktree.

        Args:
            worktree: The worktree to commit
            message: Commit message
            author: Optional commit author

        Returns:
            Operation result with commit information
        """
        if worktree.name not in self._metadata:
            return VersionControlResult(
                success=False,
                message=f"Worktree {worktree.name} not found",
                error="Worktree does not exist",
            )

        worktree_info = self._metadata[worktree.name]
        worktree_path = Path(worktree_info["path"])

        if not worktree_path.exists():
            return VersionControlResult(
                success=False,
                message=f"Worktree directory not found at {worktree_path}",
                error="Worktree directory missing",
            )

        # Stage all changes
        self._run_git_command(["add", "."], cwd=worktree_path)

        # Build commit command
        commit_cmd = ["commit", "-m", message]
        if author:
            commit_cmd.extend(["--author", author])
        else:
            commit_cmd.extend(["--author", "CruxEvolve <noreply@crux_evolve.dev>"])

        returncode, stdout, stderr = self._run_git_command(
            commit_cmd,
            cwd=worktree_path,
        )

        if returncode != 0:
            # Check if there are no changes to commit
            if "nothing to commit" in stderr or "no changes added to commit" in stderr:
                logger.warning(f"No changes to commit in worktree {worktree.name}")
                return VersionControlResult(
                    success=True,
                    message="No changes to commit",
                    data={"commit_hash": None, "changes_committed": False},
                )
            return VersionControlResult(
                success=False,
                message=f"Failed to commit changes to worktree {worktree.name}",
                error=stderr,
            )

        # Get commit hash
        returncode, commit_hash, stderr = self._run_git_command(
            ["rev-parse", "HEAD"],
            cwd=worktree_path,
        )
        worktree.commit_hash = commit_hash.strip() if returncode == 0 else worktree.commit_hash

        # Update last used time
        self._metadata[worktree.name]["last_used_at"] = time.time()
        self._save_metadata()

        return VersionControlResult(
            success=True,
            message="Changes committed successfully",
            data={
                "commit_hash": commit_hash.strip() if returncode == 0 else None,
                "changes_committed": True,
            },
        )

    def add_worktree(self, worktree: WorktreeInfo) -> None:
        """Add an existing worktree to metadata.

        This is used when a worktree is created outside of this class (e.g. by
        the planner) and we want to track it in our metadata.

        Args:
            worktree: WorktreeInfo object representing the worktree to add
        """
        self._metadata[worktree.name] = {
            "name": worktree.name,
            "branch": worktree.branch,
            "path": worktree.path,
            "created_at": worktree.created_at,
            "last_used_at": worktree.last_used_at,
            "is_locked": worktree.is_locked,
            "lock_reason": "",
        }
        self._save_metadata()

    def delete_worktree(
        self,
        worktree: WorktreeInfo,
        force: bool = False,
        delete_branch: bool = False
    ) -> VersionControlResult:
        """Delete a worktree and its branch.

        Args:
            worktree: WorktreeInfo of the worktree to delete.
            force: Force deletion even if uncommitted changes exist.
            delete_branch: Whether to delete the associated branch.

        Returns:
            Operation result with deletion status
        """
        if worktree.name not in self._metadata:
            return VersionControlResult(
                success=False,
                message=f"Worktree {worktree.name} not found",
                error="Worktree does not exist",
            )

        worktree_info = self._metadata[worktree.name]
        worktree_path = Path(worktree_info["path"])
        branch_name = worktree_info["branch"]

        # Remove worktree
        cmd = ["worktree", "remove", str(worktree_path)]
        if force:
            cmd.append("--force")

        returncode, stdout, stderr = self._run_git_command(cmd)

        if returncode != 0 and not force:
            return VersionControlResult(
                success=False,
                message=f"Failed to delete worktree {worktree.name}",
                error=stderr,
            )

        if delete_branch:
            # Delete branch from main repo
            self._run_git_command(["branch", "-D", branch_name])

        # Remove from metadata
        del self._metadata[worktree.name]
        self._save_metadata()

        return VersionControlResult(
            success=True,
            message=f"Worktree {worktree.name} deleted successfully",
            data={"deleted_branch": branch_name},
        )

    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all existing worktrees.

        Returns:
            List of worktree information objects
        """
        worktrees = []
        for name, info in self._metadata.items():
            worktree_path = Path(info["path"])
            commit_hash = ""
            if worktree_path.exists():
                returncode, ch, _ = self._run_git_command(
                    ["rev-parse", "HEAD"],
                    cwd=worktree_path,
                )
                if returncode == 0:
                    commit_hash = ch.strip()

            worktrees.append(
                WorktreeInfo(
                    name=name,
                    path=info["path"],
                    branch=info["branch"],
                    commit_hash=commit_hash,
                    is_locked=info.get("is_locked", False),
                    created_at=info["created_at"],
                    last_used_at=info["last_used_at"],
                )
            )
        return worktrees

    def cleanup_old_resources(
        self,
        max_age_days: float | None = None,
        max_worktrees: int | None = None,
    ) -> VersionControlResult:
        """Clean up old worktrees.

        Args:
            max_age_days: Maximum age of worktrees to keep (overrides config)
            max_worktrees: Maximum number of worktrees to keep (overrides config)

        Returns:
            Operation result with cleanup statistics
        """
        worktrees = self.list_worktrees()
        current_time = time.time()

        # Use config values if not specified
        if max_age_days is None:
            max_age_days = self.config.max_worktree_age_days
        if max_worktrees is None:
            max_worktrees = self.config.max_worktrees

        max_age_seconds = max_age_days * 24 * 60 * 60

        # Filter worktrees eligible for deletion (not locked and too old)
        eligible = [
            wt
            for wt in worktrees
            if not wt.is_locked and (current_time - wt.last_used_at) > max_age_seconds
        ]

        # If still over max_worktrees, delete oldest unlocked first
        total_unlocked = sum(1 for wt in worktrees if not wt.is_locked)
        if total_unlocked > max_worktrees:
            # Sort by last used time (oldest first)
            sorted_unlocked = sorted(
                [wt for wt in worktrees if not wt.is_locked],
                key=lambda x: x.last_used_at,
            )
            over_limit = total_unlocked - max_worktrees
            additional = sorted_unlocked[:over_limit]
            for wt in additional:
                if wt not in eligible:
                    eligible.append(wt)

        deleted = []
        errors = []

        for wt in eligible:
            result = self.delete_worktree(wt, force=True)
            if result.success:
                deleted.append(wt.name)
            else:
                errors.append(f"{wt.name}: {result.error}")

        return VersionControlResult(
            success=len(errors) == 0,
            message=f"Cleanup completed: deleted {len(deleted)} worktrees",
            data={
                "deleted_count": len(deleted),
                "deleted_worktrees": deleted,
                "error_count": len(errors),
                "errors": errors,
            },
        )

    def get_worktree_path(self, worktree_name: str) -> Path | None:
        """Get worktree path.

        Args:
            worktree_name: Name of the worktree

        Returns:
            Path to worktree if it exists, None otherwise
        """
        if worktree_name in self._metadata:
            return Path(self._metadata[worktree_name]["path"])
        return None

    def lock_worktree(
        self,
        worktree_name: str,
        reason: str = "",
    ) -> VersionControlResult:
        """Lock a worktree.

        Args:
            worktree_name: Name of the worktree
            reason: Reason for locking

        Returns:
            Operation result with lock status
        """
        if worktree_name not in self._metadata:
            return VersionControlResult(
                success=False,
                message=f"Worktree {worktree_name} not found",
                error="Worktree does not exist",
            )

        self._metadata[worktree_name]["is_locked"] = True
        self._metadata[worktree_name]["lock_reason"] = reason
        self._metadata[worktree_name]["last_used_at"] = time.time()
        self._save_metadata()

        return VersionControlResult(
            success=True,
            message=f"Worktree {worktree_name} locked",
            data={"reason": reason},
        )

    def unlock_worktree(
        self,
        worktree_name: str,
    ) -> VersionControlResult:
        """Unlock a worktree.

        Args:
            worktree_name: Name of the worktree

        Returns:
            Operation result with unlock status
        """
        if worktree_name not in self._metadata:
            return VersionControlResult(
                success=False,
                message=f"Worktree {worktree_name} not found",
                error="Worktree does not exist",
            )

        self._metadata[worktree_name]["is_locked"] = False
        self._metadata[worktree_name]["lock_reason"] = ""
        self._save_metadata()

        return VersionControlResult(
            success=True,
            message=f"Worktree {worktree_name} unlocked",
            data={},
        )

    def get_changed_files(
        self,
        commit_hash: str,
    ) -> list[dict[str, str]]:
        """Get changed files for a specific commit.

        Args:
            commit_hash: The commit hash to get changes for

        Returns:
            List of dictionaries containing file_path and file content
        """
        # Get the parent commit to compare against
        returncode, stdout, stderr = self._run_git_command(
            ["rev-parse", commit_hash + "^"],
        )

        parent_hash = ""
        if returncode == 0:
            parent_hash = stdout.strip()
        else:
            # This might be the first commit, check if commit exists
            returncode, _, _ = self._run_git_command(
                ["cat-file", "-t", commit_hash],
            )
            if returncode != 0:
                # Commit doesn't exist
                return []

        # Get list of changed files
        if parent_hash:
            returncode, stdout, stderr = self._run_git_command(
                ["diff", "--name-only", parent_hash, commit_hash],
            )
        else:
            # First commit - show all files
            returncode, stdout, stderr = self._run_git_command(
                ["diff", "--name-only", commit_hash],
            )

        if returncode != 0:
            return []

        files = [f.strip() for f in stdout.strip().split("\n") if f.strip()]
        if not files:
            return []

        # Get file content for each changed file
        changed_files = []
        for file_path in files:
            returncode, file_content, _ = self._run_git_command(
                ["show", f"{commit_hash}:{file_path}"],
            )

            if returncode == 0:
                changed_files.append(
                    {
                        "file_path": file_path,
                        "content": file_content,
                    }
                )

        return changed_files

    def get_diff_stats(
        self,
        commit_hash: str,
    ) -> dict[str, int]:
        """Get diff statistics (lines added/removed) for a specific commit.

        Args:
            commit_hash: The commit hash to get stats for.

        Returns:
            Dictionary with 'additions' and 'deletions' counts.
        """
        # Get parent commit
        returncode, stdout, _ = self._run_git_command(
            ["rev-parse", commit_hash + "^"],
        )

        if returncode == 0:
            parent_hash = stdout.strip()
            returncode, stdout, _ = self._run_git_command(
                ["diff", "--numstat", parent_hash, commit_hash],
            )
        else:
            returncode, stdout, _ = self._run_git_command(
                ["diff", "--numstat", commit_hash],
            )

        additions = 0
        deletions = 0
        if returncode == 0 and stdout.strip():
            for line in stdout.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    try:
                        additions += int(parts[0]) if parts[0] != "-" else 0
                        deletions += int(parts[1]) if parts[1] != "-" else 0
                    except ValueError:
                        continue

        return {"additions": additions, "deletions": deletions}
