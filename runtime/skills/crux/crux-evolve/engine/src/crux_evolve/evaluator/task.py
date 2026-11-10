"""Task management for the evaluator layer."""

import hashlib
import time
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskType(Enum):
    """Types of evaluation tasks."""

    SINGLE_OBJECTIVE = "single_objective"
    MULTI_OBJECTIVE = "multi_objective"
    CONSTRAINED = "constrained"
    BENCHMARK = "benchmark"


class TaskConfig(BaseModel):
    """Configuration for an evaluation task.

    The dataset_path can be:
    - A file path (csv, json, npy, etc.)
    - A directory path containing dataset files
    - None if the task generates data programmatically
    """

    name: str
    description: str = ""
    task_type: TaskType = TaskType.SINGLE_OBJECTIVE

    # Dataset configuration
    dataset_path: str | None = None
    dataset_format: str | None = None  # csv, json, npy, etc.

    # Evaluation configuration
    timeout: float = 60.0
    max_retries: int = 1
    batch_size: int = 1

    # Objective configuration (for multi-objective)
    objectives: list[str] = Field(default_factory=list)
    objective_weights: dict[str, float] = Field(default_factory=dict)

    # Constraint configuration
    constraints: list[str] = Field(default_factory=list)

    # Custom configuration
    custom: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def get_dataset_hash(self) -> str | None:
        """Compute hash of the dataset for caching/validation.

        Returns:
            MD5 hash of dataset content, or None if no dataset
        """
        if not self.dataset_path:
            return None

        path = Path(self.dataset_path)
        if not path.exists():
            return None

        if path.is_file():
            content = path.read_bytes()
            return hashlib.md5(content).hexdigest()
        elif path.is_dir():
            # Hash all files in directory
            hasher = hashlib.md5()
            for file in sorted(path.rglob("*")):
                if file.is_file():
                    hasher.update(file.read_bytes())
            return hasher.hexdigest()

        return None

    def validate(self) -> list[str]:
        """Validate the task configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.name:
            errors.append("Task name is required")

        if self.dataset_path:
            path = Path(self.dataset_path)
            if not path.exists():
                errors.append(f"Dataset path does not exist: {self.dataset_path}")

        if self.timeout <= 0:
            errors.append("Timeout must be positive")

        if self.batch_size < 1:
            errors.append("Batch size must be at least 1")

        # Validate objectives match weights
        for obj in self.objectives:
            if obj not in self.objective_weights:
                errors.append(f"Missing weight for objective: {obj}")

        return errors


class Task:
    """Evaluation task manager.

    Manages evaluation tasks including dataset paths and result collection.
    The dataset is passed as a path to user-provided evaluation functions,
    allowing users to define their own data loading logic.
    """

    def __init__(self, config: TaskConfig):
        """Initialize task.

        Args:
            config: Task configuration
        """
        self.config = config
        self.results: list[dict] = []

    def get_dataset_path(self) -> str | None:
        """Get the dataset path.

        Returns:
            Path to dataset (file or folder), or None if not configured
        """
        return self.config.dataset_path

    def validate_dataset(self) -> tuple[bool, str]:
        """Validate that the dataset exists and is accessible.

        Returns:
            Tuple of (is_valid, error_message)
        """
        path_str = self.config.dataset_path
        if not path_str:
            return True, ""  # No dataset required

        path = Path(path_str)
        if not path.exists():
            return False, f"Dataset path does not exist: {path_str}"

        if not path.is_file() and not path.is_dir():
            return False, f"Dataset path is not a file or directory: {path_str}"

        return True, ""

    def add_result(self, algorithm_id: str, result: dict) -> None:
        """Add an evaluation result.

        Args:
            algorithm_id: ID of the evaluated algorithm
            result: Evaluation result dictionary
        """
        result["algorithm_id"] = algorithm_id
        result["timestamp"] = time.time()
        self.results.append(result)

    def get_results(self, algorithm_id: str | None = None) -> list[dict]:
        """Get evaluation results.

        Args:
            algorithm_id: Optional algorithm ID to filter by

        Returns:
            List of evaluation results
        """
        if algorithm_id:
            return [r for r in self.results if r.get("algorithm_id") == algorithm_id]
        return self.results.copy()

    def clear_results(self) -> None:
        """Clear all stored results."""
        self.results.clear()
