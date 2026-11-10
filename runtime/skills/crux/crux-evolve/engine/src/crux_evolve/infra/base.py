"""Base classes and types for the infrastructure layer."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

# =============================================================================
# Checkpoint Types
# =============================================================================


class CheckpointData(BaseModel):
    """Data structure for checkpoint save/restore.

    Contains all state needed to resume an evolution run.
    """

    generation: int
    population: list[Any]  # List[AlgorithmInsight] - imported at runtime
    memory: Any  # Memory object - imported at runtime
    config: dict[str, Any]
    rng_state: dict | None = None
    timestamp: float = 0.0

    model_config = ConfigDict(arbitrary_types_allowed=True)


# =============================================================================
# Monitoring Types
# =============================================================================


class SystemMetrics(BaseModel):
    """System resource metrics."""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_gb: float = 0.0
    memory_total_gb: float = 0.0
    gpu_percent: float | None = None
    gpu_memory_used_gb: float | None = None
    gpu_memory_total_gb: float | None = None
    disk_io_read_mb: float = 0.0
    disk_io_write_mb: float = 0.0
    network_sent_mb: float = 0.0
    network_recv_mb: float = 0.0


class EvolutionMetrics(BaseModel):
    """Evolution process metrics."""

    generation: int = 0
    population_size: int = 0
    best_score: float = 0.0
    worst_score: float = 0.0
    mean_score: float = 0.0
    median_score: float = 0.0
    std_score: float = 0.0
    diversity_score: float = 0.0  # Population diversity measure
    improvement_rate: float = 0.0  # Score improvement per generation


class LLMMetrics(BaseModel):
    """LLM API usage metrics."""

    requests_count: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    errors_count: int = 0
    rate_limit_hits: int = 0


class EvaluationMetrics(BaseModel):
    """Algorithm evaluation metrics."""

    total_evaluations: int = 0
    successful_evaluations: int = 0
    failed_evaluations: int = 0
    avg_eval_time_ms: float = 0.0
    total_eval_time_ms: float = 0.0
    throughput_per_sec: float = 0.0  # Evaluations per second


class MetricsSnapshot(BaseModel):
    """Complete metrics snapshot at a point in time."""

    timestamp: float
    run_id: str
    system: SystemMetrics
    evolution: EvolutionMetrics
    llm: LLMMetrics
    evaluation: EvaluationMetrics

    model_config = ConfigDict(arbitrary_types_allowed=True)


class EvolutionStats(BaseModel):
    """Complete evolution statistics for a generation."""

    generation: int
    timestamp: float
    best_algorithm_id: str | None = None
    best_score: float = 0.0
    population_stats: dict[str, float] = {}
    metrics: MetricsSnapshot


# =============================================================================
# Base Classes
# =============================================================================


class BaseCheckpointManager(ABC):
    """Abstract checkpoint manager interface.

    Handles saving and restoring evolution state for fault tolerance
    and the ability to resume long-running evolution processes.
    """

    def __init__(self, checkpoint_dir: str, save_interval: int = 10, max_checkpoints: int = 5):
        """Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoint files
            save_interval: Save checkpoint every N generations
            max_checkpoints: Maximum number of checkpoints to keep
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.save_interval = save_interval
        self.max_checkpoints = max_checkpoints

    @abstractmethod
    async def save(self, data: CheckpointData) -> Path:
        """Save a checkpoint.

        Args:
            data: Checkpoint data to save

        Returns:
            Path to saved checkpoint file
        """
        pass

    @abstractmethod
    async def load(self, checkpoint_path: Path) -> CheckpointData:
        """Load a checkpoint.

        Args:
            checkpoint_path: Path to checkpoint file

        Returns:
            Loaded checkpoint data
        """
        pass

    @abstractmethod
    async def list_checkpoints(self) -> list[Path]:
        """List all available checkpoints.

        Returns:
            List of checkpoint file paths, sorted by time
        """
        pass

    @abstractmethod
    async def get_latest(self) -> CheckpointData | None:
        """Get the most recent checkpoint.

        Returns:
            Latest checkpoint data, or None if no checkpoints exist
        """
        pass

    @abstractmethod
    async def should_save(self, generation: int) -> bool:
        """Check if a checkpoint should be saved at this generation.

        Args:
            generation: Current generation number

        Returns:
            True if checkpoint should be saved
        """
        pass

    @abstractmethod
    async def cleanup_old(self) -> None:
        """Remove old checkpoints, keeping only max_checkpoints most recent."""
        pass


class BaseMonitor(ABC):
    """Abstract monitor interface.

    Real-time system monitoring for tracking compute resource usage during evolution.
    Tracks generation progress, population statistics, best scores, LLM API usage,
    and evaluation throughput.
    """

    def __init__(self, config: dict):
        """Initialize monitor.

        Args:
            config: Monitor configuration dict
        """
        self.config = config
        self.run_id: str = ""
        self.start_time: float = 0.0
        self.history: list[EvolutionStats] = []

    @abstractmethod
    async def start(self, run_id: str) -> None:
        """Start monitoring a new evolution run.

        Args:
            run_id: Unique identifier for this evolution run
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop monitoring."""
        pass

    @abstractmethod
    async def record_system(self) -> SystemMetrics:
        """Collect current system metrics (CPU, memory, GPU, etc.).

        Returns:
            Current system metrics
        """
        pass

    @abstractmethod
    async def record_evolution(self, generation: int, population: list[Any]) -> EvolutionMetrics:
        """Record evolution progress metrics.

        Args:
            generation: Current generation number
            population: Current population of algorithms

        Returns:
            Evolution metrics for this generation
        """
        pass

    @abstractmethod
    async def record_llm(
        self, requests: int, tokens: int, cost: float, latency: float
    ) -> LLMMetrics:
        """Record LLM API usage metrics.

        Args:
            requests: Number of API requests
            tokens: Total tokens used
            cost: Total cost in USD
            latency: Total latency in seconds

        Returns:
            LLM metrics
        """
        pass

    @abstractmethod
    async def record_evaluation(self, evaluations: int, time_per_eval: float) -> EvaluationMetrics:
        """Record evaluation metrics.

        Args:
            evaluations: Number of evaluations completed
            time_per_eval: Average time per evaluation in seconds

        Returns:
            Evaluation metrics
        """
        pass

    @abstractmethod
    def get_current_stats(self) -> EvolutionStats:
        """Get current statistics snapshot.

        Returns:
            Current evolution statistics
        """
        pass

    @abstractmethod
    def get_history(self) -> list[EvolutionStats]:
        """Get full evolution history.

        Returns:
            List of evolution statistics for all generations
        """
        pass

    @abstractmethod
    async def export_prometheus(self, port: int = 8000) -> None:
        """Export metrics to Prometheus.

        Args:
            port: Port to expose Prometheus metrics on
        """
        pass

    @abstractmethod
    async def export_tensorboard(self, log_dir: str) -> None:
        """Export metrics to TensorBoard.

        Args:
            log_dir: Directory to write TensorBoard logs
        """
        pass


class BaseScheduler(ABC):
    """Abstract scheduler interface.

    Ray-based parallel task scheduler for distributing evaluation workloads
    across clusters.
    """

    def __init__(self, config: dict):
        """Initialize scheduler.

        Args:
            config: Scheduler configuration dict
        """
        self.config = config

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the scheduler and connect to Ray cluster."""
        pass

    @abstractmethod
    async def submit(self, task: Any) -> str:
        """Submit a task for execution.

        Args:
            task: Task to execute

        Returns:
            Task ID
        """
        pass

    @abstractmethod
    async def submit_batch(self, tasks: list[Any]) -> list[str]:
        """Submit multiple tasks for execution.

        Args:
            tasks: List of tasks to execute

        Returns:
            List of task IDs
        """
        pass

    @abstractmethod
    async def get_result(self, task_id: str, timeout: float | None = None) -> Any:
        """Get the result of a task.

        Args:
            task_id: Task ID
            timeout: Timeout in seconds

        Returns:
            Task result
        """
        pass

    @abstractmethod
    async def get_status(self, task_id: str) -> str:
        """Get the status of a task.

        Args:
            task_id: Task ID

        Returns:
            Task status (pending, running, completed, failed)
        """
        pass

    @abstractmethod
    async def cancel(self, task_id: str) -> bool:
        """Cancel a task.

        Args:
            task_id: Task ID

        Returns:
            True if cancelled successfully
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the scheduler and disconnect from Ray cluster."""
        pass

    @abstractmethod
    def get_cluster_info(self) -> dict:
        """Get information about the Ray cluster.

        Returns:
            Dictionary with cluster information
        """
        pass


class BaseSandbox(ABC):
    """Abstract sandbox interface.

    Safe execution environment to run untrusted code securely.
    """

    def __init__(self, config: dict):
        """Initialize sandbox.

        Args:
            config: Sandbox configuration dict
        """
        self.config = config

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the sandbox environment."""
        pass

    @abstractmethod
    async def execute(
        self, code: str, timeout: float = 60.0, memory_limit: int = 512, **kwargs
    ) -> dict:
        """Execute code in the sandbox.

        Args:
            code: Code to execute
            timeout: Timeout in seconds
            memory_limit: Memory limit in MB
            **kwargs: Additional execution options

        Returns:
            Execution result with stdout, stderr, returncode
        """
        pass

    @abstractmethod
    async def execute_file(self, file_path: str, timeout: float = 60.0, **kwargs) -> dict:
        """Execute a file in the sandbox.

        Args:
            file_path: Path to file to execute
            timeout: Timeout in seconds
            **kwargs: Additional execution options

        Returns:
            Execution result
        """
        pass

    @abstractmethod
    async def install_dependencies(self, dependencies: list[str], **kwargs) -> bool:
        """Install dependencies in the sandbox.

        Args:
            dependencies: List of dependencies to install
            **kwargs: Additional install options

        Returns:
            True if installation succeeded
        """
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up the sandbox environment."""
        pass

    @abstractmethod
    def get_status(self) -> dict:
        """Get sandbox status.

        Returns:
            Dictionary with sandbox status
        """
        pass


class BaseGitManager(ABC):
    """Abstract git manager interface.

    Git-based version control for tracking algorithm evolution.
    Each algorithm lives in a separate git worktree (branch).
    New algorithms branch from their parent algorithm's branch.
    """

    def __init__(self, repo_path: str, worktrees_root: str):
        """Initialize git manager.

        Args:
            repo_path: Path to the main git repository
            worktrees_root: Root directory for all algorithm worktrees
        """
        self.repo_path = Path(repo_path)
        self.worktrees_root = Path(worktrees_root)
        self.worktrees_root.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def init_repo(self) -> None:
        """Initialize the main repository if not exists."""
        pass

    @abstractmethod
    def create_algorithm_version(
        self,
        insight_id: str,
        generation: int,
        parent_id: str | None = None,
        parent_generation: int | None = None,
        code_files: dict[str, str] | None = None,
        commit_message: str | None = None,
    ) -> Any:  # Returns AlgorithmVersion
        """Create a new algorithm version as a new git worktree.

        Args:
            insight_id: Unique identifier for this algorithm insight
            generation: Generation number in evolution
            parent_id: Parent algorithm's insight_id (if this is a child/mutation)
            parent_generation: Parent's generation number
            code_files: Dict of {filename: content} to write
            commit_message: Custom commit message

        Returns:
            AlgorithmVersion with branch and commit info
        """
        pass

    @abstractmethod
    def compare_algorithms(
        self, insight_id_1: str, generation_1: int, insight_id_2: str, generation_2: int
    ) -> str:
        """Compare two algorithm versions (returns diff).

        Args:
            insight_id_1: First algorithm insight ID
            generation_1: First algorithm generation
            insight_id_2: Second algorithm insight ID
            generation_2: Second algorithm generation

        Returns:
            Git diff string between the two versions
        """
        pass

    @abstractmethod
    def checkout_version(self, insight_id: str, generation: int) -> str:
        """Get the path to a specific algorithm version's worktree.

        Args:
            insight_id: Algorithm insight ID
            generation: Generation number

        Returns:
            Path to the worktree directory
        """
        pass

    @abstractmethod
    def get_best_algorithm(self) -> Any | None:  # Returns Optional[AlgorithmVersion]
        """Get the algorithm with the highest score.

        Returns:
            Best algorithm version, or None if no algorithms exist
        """
        pass
