"""State tracking for evolutionary algorithm execution.

Provides a centralized state tracker that records evolution progress,
resource consumption, module timing statistics, and historical metrics.
All data can be exported in JSON-serializable format for frontend visualization.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from crux_evolve.infra.timing import ExecutionTiming


class EvolutionState(Enum):
    """State of the evolution process."""

    IDLE = "idle"  # Not started
    RUNNING = "running"  # Actively evolving
    PAUSED = "paused"  # Temporarily paused
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"  # Error occurred

class ModuleTiming(BaseModel):
    """Timing statistics for individual modules.

    Tracks cumulative, average, min, and max execution times
    for a given module operation.
    """

    total_time_ms: float = 0.0
    call_count: int = 0
    average_time_ms: float = 0.0
    min_time_ms: float = float("inf")
    max_time_ms: float = 0.0
    last_time_ms: float = 0.0

    model_config = ConfigDict(frozen=False)


class ResourceUsage(BaseModel):
    """Snapshot of system resource consumption.

    Records memory usage, CPU utilization, and other system
    resource metrics at a point in time.
    """

    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    worktree_count: int = 0
    active_tasks: int = 0
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())

    model_config = ConfigDict(frozen=False)


class GenerationMetrics(BaseModel):
    """Metrics collected at the end of each generation.

    Contains summary statistics about the population for
    a single generation of evolution.
    """

    generation: int
    best_score: float
    average_score: float
    worst_score: float
    total_evaluations: int
    successful_evaluations: int
    failed_evaluations: int
    island_best_scores: dict[int, float] = Field(default_factory=dict)
    total_tokens: int = Field(default=0, description="Total tokens consumed in this generation")
    timing: ExecutionTiming = Field(default_factory=ExecutionTiming)
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())

    model_config = ConfigDict(frozen=False)


class StateTrackerConfig(BaseModel):
    """Configuration for the state tracker.

    Controls which features are enabled and their behavior.
    """

    enable_resource_tracking: bool = True
    resource_tracking_interval_seconds: float = 5.0
    enable_detailed_timing: bool = True
    max_history_entries: int = 1000

    model_config = ConfigDict(frozen=False)


class StateTracker(BaseModel):
    """Centralized state tracker for evolutionary algorithm execution.

    Tracks all aspects of the evolution process:
    - Current evolution progress (generation, state, timing)
    - Cumulative timing statistics per module
    - Historical resource usage snapshots
    - Historical generation metrics
    - Global statistics and custom metadata
    - Workspace directory paths

    All data can be exported to JSON-serializable format for
    frontend visualization and analysis.
    """

    # Evolution progress
    state: EvolutionState = EvolutionState.IDLE
    current_generation: int = 0
    total_generations: int = 0
    start_time: float = Field(default_factory=lambda: datetime.now().timestamp())
    end_time: float | None = None
    run_id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))

    # Workspace directory paths
    base_dir: Path | None = None
    state_dir: Path | None = None
    logs_dir: Path | None = None
    checkpoints_dir: Path | None = None
    generated_dir: Path | None = None
    temp_dir: Path | None = None
    worktrees_dir: Path | None = None
    coder_dir: Path | None = None
    memory_dir: Path | None = None
    embedding_dir: Path | None = None
    best_dir: Path | None = None

    # Configuration
    config: StateTrackerConfig = Field(default_factory=StateTrackerConfig)

    # Timing statistics per module
    module_timing: dict[str, ModuleTiming] = Field(default_factory=dict)

    # Resource usage history
    resource_history: list[ResourceUsage] = Field(default_factory=list)

    # Evolution metrics history
    metrics_history: list[GenerationMetrics] = Field(default_factory=list)

    # Per-candidate and per-generation timing (used by MEoH)
    candidate_timings: dict[str, ExecutionTiming] = Field(default_factory=dict)
    generation_timing: dict[int, ExecutionTiming] = Field(default_factory=dict)
    run_timing: ExecutionTiming = Field(default_factory=ExecutionTiming)

    # Global statistics
    global_best_score: float = float("-inf")
    total_evaluations: int = 0
    total_migrations: int = 0

    # Custom metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    def start_run(self, total_generations: int) -> None:
        """Mark the start of an evolution run.

        Initializes the state tracker for a new run with
        the specified total number of generations.

        Args:
            total_generations: Maximum number of generations for this run.
        """
        self.state = EvolutionState.RUNNING
        self.total_generations = total_generations
        self.start_time = datetime.now().timestamp()
        self.end_time = None
        self.current_generation = 0
        self.metrics_history.clear()
        self.resource_history.clear()
        self.module_timing.clear()
        self.candidate_timings.clear()
        self.generation_timing.clear()
        self.run_timing = ExecutionTiming()
        self.global_best_score = float("-inf")
        self.total_evaluations = 0
        self.total_migrations = 0

    def set_workspace_dirs(
        self,
        base_dir: Path,
        subdirs: dict[str, str] | None = None,
    ) -> None:
        """Set workspace directory paths.

        Args:
            base_dir: Base directory for the run workspace.
            subdirs: Optional dict mapping dir keys to subdir names.
                Default subdirs: state, logs, checkpoints, generated, temp, worktrees
        """
        if subdirs is None:
            subdirs = {
                "state": "state",
                "logs": "logs",
                "checkpoints": "checkpoints",
                "generated": "generated",
                "temp": "temp",
                "worktrees": "worktrees",
                "coder": "coder",
                "embedding": "embedding",
                "best": "best",
            }

        self.base_dir = base_dir
        self.state_dir = base_dir / subdirs.get("state", "state")
        self.logs_dir = base_dir / subdirs.get("logs", "logs")
        self.checkpoints_dir = base_dir / subdirs.get("checkpoints", "checkpoints")
        self.generated_dir = base_dir / subdirs.get("generated", "generated")
        self.temp_dir = base_dir / subdirs.get("temp", "temp")
        self.worktrees_dir = base_dir / subdirs.get("worktrees", "worktrees")
        self.coder_dir = base_dir / subdirs.get("coder", "coder")
        self.memory_dir = base_dir / subdirs.get("memory", "memory")
        self.embedding_dir = base_dir / subdirs.get("embedding", "embedding")
        self.best_dir = base_dir / subdirs.get("best", "best")

        os.makedirs(self.state_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.checkpoints_dir, exist_ok=True)
        os.makedirs(self.generated_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.worktrees_dir, exist_ok=True)
        os.makedirs(self.coder_dir, exist_ok=True)
        os.makedirs(self.memory_dir, exist_ok=True)
        os.makedirs(self.embedding_dir, exist_ok=True)
        os.makedirs(self.best_dir, exist_ok=True)

    def end_run(self, state: EvolutionState = EvolutionState.COMPLETED) -> None:
        """Mark the end of an evolution run.

        Records the end time and final state of the run.

        Args:
            state: Final evolution state (default: COMPLETED).
        """
        self.state = state
        self.end_time = datetime.now().timestamp()

    def update_generation(self, generation: int, metrics: GenerationMetrics) -> None:
        """Update state with new generation metrics.

        Adds the generation metrics to history and updates
        global statistics like best score.

        Args:
            generation: Current generation number.
            metrics: Metrics collected from this generation.
        """
        self.current_generation = generation
        self.metrics_history.append(metrics)
        self.global_best_score = max(self.global_best_score, metrics.best_score)
        self.total_evaluations += metrics.total_evaluations

        # Trim history if needed
        if len(self.metrics_history) > self.config.max_history_entries:
            self.metrics_history.pop(0)

    def record_timing(self, module_name: str, time_ms: float) -> None:
        """Record timing for a module operation.

        Updates the cumulative timing statistics for the
        specified module. Does nothing if detailed timing
        is disabled in configuration.

        Args:
            module_name: Name of the module (e.g., "planner.sample").
            time_ms: Execution time in milliseconds.
        """
        if not self.config.enable_detailed_timing:
            return

        if module_name not in self.module_timing:
            self.module_timing[module_name] = ModuleTiming()

        timing = self.module_timing[module_name]
        timing.total_time_ms += time_ms
        timing.call_count += 1
        timing.average_time_ms = timing.total_time_ms / timing.call_count
        timing.min_time_ms = min(timing.min_time_ms, time_ms)
        timing.max_time_ms = max(timing.max_time_ms, time_ms)
        timing.last_time_ms = time_ms

    def record_resource_usage(self, usage: ResourceUsage) -> None:
        """Record current resource usage.

        Adds a new resource usage snapshot to history if
        resource tracking is enabled in configuration.

        Args:
            usage: Resource usage snapshot to record.
        """
        if not self.config.enable_resource_tracking:
            return

        self.resource_history.append(usage)

        # Trim history if needed
        if len(self.resource_history) > self.config.max_history_entries:
            self.resource_history.pop(0)

    def increment_migration_count(self) -> None:
        """Increment the total migration count.

        Should be called after each migration operation
        to keep track of how many migrations have occurred.
        """
        self.total_migrations += 1

    def record_candidate_timing(self, candidate_id: str, timing: ExecutionTiming) -> None:
        """Record timing for a single candidate evaluation.

        Accumulates timing if the candidate has been seen before.

        Args:
            candidate_id: Unique identifier of the candidate.
            timing: Timing breakdown for this candidate.
        """
        if candidate_id not in self.candidate_timings:
            self.candidate_timings[candidate_id] = ExecutionTiming()
        self.candidate_timings[candidate_id].add(timing)
        self.candidate_timings[candidate_id].recompute_overhead()

    def record_generation_timing(
        self, generation: int | None = None, timing: ExecutionTiming | None = None
    ) -> None:
        """Record or update timing for a generation.

        If *timing* is provided it replaces the stored snapshot for
        *generation* (defaulting to ``self.current_generation``).
        The cumulative ``run_timing`` is kept in sync.

        Args:
            generation: Generation number (defaults to current_generation).
            timing: Timing snapshot for the generation.
        """
        if timing is None:
            return
        if generation is None:
            generation = self.current_generation

        # Subtract the previous snapshot so we can replace it
        previous = self.generation_timing.get(generation)
        if previous is not None:
            self.run_timing.add(
                ExecutionTiming(
                    wall_time_ms=-previous.wall_time_ms,
                    llm_planning_ms=-previous.llm_planning_ms,
                    llm_coding_ms=-previous.llm_coding_ms,
                    evaluation_total_ms=-previous.evaluation_total_ms,
                    candidate_runtime_ms=-previous.candidate_runtime_ms,
                    overhead_ms=-previous.overhead_ms,
                )
            )

        snapshot = timing.model_copy(deep=True)
        snapshot.recompute_overhead()
        self.generation_timing[generation] = snapshot
        self.run_timing.add(snapshot)
        self.run_timing.recompute_overhead()

    def get_status_summary(self) -> dict[str, Any]:
        """Get a summary of current status for quick monitoring.

        Returns a dictionary with the most important
        status information, suitable for quick display
        or API responses.

        Returns:
            Dictionary containing current status summary.
        """
        duration = (self.end_time or datetime.now().timestamp()) - self.start_time
        progress_percent = (
            (self.current_generation / self.total_generations * 100)
            if self.total_generations > 0
            else 0
        )

        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "current_generation": self.current_generation,
            "total_generations": self.total_generations,
            "progress_percent": progress_percent,
            "global_best_score": self.global_best_score,
            "total_evaluations": self.total_evaluations,
            "total_migrations": self.total_migrations,
            "duration_seconds": duration,
            "active_worktrees": (
                self.resource_history[-1].worktree_count if self.resource_history else 0
            ),
        }

    def export_for_visualization(self) -> dict[str, Any]:
        """Export complete state data in JSON-serializable format.

        Returns all historical data and current state in a
        format that can be easily serialized to JSON and
        consumed by frontend visualization tools.

        Returns:
            Dictionary containing all state data in JSON-serializable format.
        """
        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "current_generation": self.current_generation,
            "total_generations": self.total_generations,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "global_best_score": self.global_best_score,
            "total_evaluations": self.total_evaluations,
            "total_migrations": self.total_migrations,
            "metrics_history": [m.model_dump() for m in self.metrics_history],
            "module_timing": {k: v.model_dump() for k, v in self.module_timing.items()},
            "resource_history": [r.model_dump() for r in self.resource_history],
            "config": self.config.model_dump(),
            "metadata": self.metadata,
            "behavior_data_available": self.metadata.get("behavior_data_available", False),
        }

    def set_behavior_available(self, available: bool = True) -> None:
        """Mark whether behavior data is available in this run.

        Args:
            available: ``True`` if any algorithm has behavior data.
        """
        self.metadata["behavior_data_available"] = available

    def to_checkpoint(self) -> dict[str, Any]:
        """Export minimal state for checkpointing.

        Returns only the essential state information needed
        to resume evolution from a checkpoint, excluding
        transient timing and resource data.

        Returns:
            Dictionary containing minimal state for checkpointing.
        """
        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "current_generation": self.current_generation,
            "total_generations": self.total_generations,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "global_best_score": self.global_best_score,
            "total_evaluations": self.total_evaluations,
            "total_migrations": self.total_migrations,
            "metrics_history": [m.model_dump() for m in self.metrics_history],
            "config": self.config.model_dump(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_checkpoint(cls, checkpoint_data: dict[str, Any]) -> StateTracker:
        """Restore state from checkpoint data.

        Creates a new StateTracker instance and restores
        all saved state from the checkpoint data.

        Args:
            checkpoint_data: Checkpoint data from `to_checkpoint()`.

        Returns:
            New StateTracker instance with restored state.
        """
        tracker = cls()
        tracker.run_id = checkpoint_data.get("run_id", tracker.run_id)
        tracker.state = EvolutionState(checkpoint_data.get("state", EvolutionState.IDLE.value))
        tracker.current_generation = checkpoint_data.get("current_generation", 0)
        tracker.total_generations = checkpoint_data.get("total_generations", 0)
        tracker.start_time = checkpoint_data.get("start_time", tracker.start_time)
        tracker.end_time = checkpoint_data.get("end_time")
        tracker.global_best_score = checkpoint_data.get("global_best_score", float("-inf"))
        tracker.total_evaluations = checkpoint_data.get("total_evaluations", 0)
        tracker.total_migrations = checkpoint_data.get("total_migrations", 0)

        # Restore config
        if "config" in checkpoint_data:
            tracker.config = StateTrackerConfig(**checkpoint_data["config"])

        # Restore metrics history
        tracker.metrics_history = [
            GenerationMetrics(**m) for m in checkpoint_data.get("metrics_history", [])
        ]

        # Restore metadata
        tracker.metadata = checkpoint_data.get("metadata", {})

        return tracker

    def save_to_cache(self, prefix: str = "state") -> str | None:
        """Save state to state directory.

        Saves the complete state to a JSON file in the state directory
        for later recovery or analysis.

        Args:
            prefix: Prefix for the filename (default: "state")

        Returns:
            Path to saved file, or None if state_dir is not set
        """
        if self.state_dir is None:
            return None

        filename = f"{prefix}_gen{self.current_generation:04d}.json"
        filepath = self.state_dir / filename

        data = self.export_for_visualization()
        with open(filepath, "w", encoding="UTF-8") as f:
            json.dump(data, f, indent=2)

        return str(filepath)
