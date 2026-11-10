"""Console-based monitor for evolution progress logging.

Simple implementation of BaseMonitor that logs evolution progress
to the console using rich for nice formatted output.
"""

import time
from typing import Any

from rich.console import Console
from rich.table import Table

from crux_evolve.infra.base import (
    BaseMonitor,
    EvaluationMetrics,
    EvolutionMetrics,
    EvolutionStats,
    LLMMetrics,
    MetricsSnapshot,
    SystemMetrics,
)

console = Console()


class ConsoleMonitor(BaseMonitor):
    """Console-based monitor that logs progress to stdout.

    Uses rich library for nice formatted output of generation statistics.
    """

    def __init__(self, config):
        """Initialize console monitor.

        Args:
            config: Logging configuration from AppConfig.
        """
        super().__init__(config)
        self.console = Console()

    async def start(self, run_id: str) -> None:
        """Start monitoring a new evolution run."""
        self.run_id = run_id
        self.start_time = time.time()
        self.console.print(
            f"[bold blue]Starting evolution run:[/bold blue] [green]{run_id}[/green]"
        )
        self.console.print()

    async def stop(self) -> None:
        """Stop monitoring."""
        duration = time.time() - self.start_time
        self.console.print()
        self.console.print(
            f"[bold blue]Evolution completed in[/bold blue] [green]{duration:.2f}s[/green]"
        )

    async def record_system(self) -> SystemMetrics:
        """Collect current system metrics."""
        # Try to get actual system metrics if psutil is available
        metrics = SystemMetrics()
        try:
            import psutil

            metrics.cpu_percent = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            metrics.memory_percent = mem.percent
            metrics.memory_used_gb = mem.used / (1024**3)
            metrics.memory_total_gb = mem.total / (1024**3)
        except ImportError:
            # psutil not available, leave as zeros
            pass
        return metrics

    async def record_evolution(self, generation: int, population: list[Any]) -> EvolutionMetrics:
        """Record evolution progress metrics and log to console."""
        metrics = EvolutionMetrics(generation=generation)

        # Get evaluated individuals
        evaluated = [
            ind for ind in population if hasattr(ind, "is_evaluated") and ind.is_evaluated()
        ]

        if evaluated:
            scores = [ind.score for ind in evaluated]
            metrics.population_size = len(evaluated)
            metrics.best_score = max(scores)
            metrics.worst_score = min(scores)
            metrics.mean_score = sum(scores) / len(scores)

            # Log to console
            table = Table(title=f"Generation {generation} Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="magenta")

            table.add_row("Population size", str(len(evaluated)))
            table.add_row("Best score", f"{metrics.best_score:.4f}")
            table.add_row("Average score", f"{metrics.mean_score:.4f}")
            table.add_row("Worst score", f"{metrics.worst_score:.4f}")

            self.console.print(table)
            self.console.print()

        return metrics

    async def record_llm(
        self, requests: int, tokens: int, cost: float, latency: float
    ) -> LLMMetrics:
        """Record LLM API usage metrics."""
        return LLMMetrics(
            requests_count=requests,
            total_tokens=tokens,
            prompt_tokens=0,
            completion_tokens=tokens,
            total_cost_usd=cost,
            avg_latency_ms=latency * 1000,
        )

    async def record_evaluation(self, evaluations: int, time_per_eval: float) -> EvaluationMetrics:
        """Record evaluation metrics."""
        return EvaluationMetrics(
            total_evaluations=evaluations,
            successful_evaluations=evaluations,
            failed_evaluations=0,
            avg_eval_time_ms=time_per_eval * 1000,
            total_eval_time_ms=evaluations * time_per_eval * 1000,
        )

    def get_current_stats(self) -> EvolutionStats:
        """Get current statistics snapshot."""
        return EvolutionStats(
            generation=0,
            timestamp=time.time(),
            best_score=0.0,
            metrics=MetricsSnapshot(
                timestamp=time.time(),
                run_id=self.run_id,
                system=SystemMetrics(),
                evolution=EvolutionMetrics(),
                llm=LLMMetrics(),
                evaluation=EvaluationMetrics(),
            ),
        )

    def get_history(self) -> list[EvolutionStats]:
        """Get full evolution history."""
        return self.history

    async def export_prometheus(self, port: int = 8000) -> None:
        """Export metrics to Prometheus (not supported by console monitor)."""
        # Console monitor doesn't implement Prometheus export
        pass

    async def export_tensorboard(self, log_dir: str) -> None:
        """Export metrics to TensorBoard (not supported by console monitor)."""
        # Console monitor doesn't implement TensorBoard export
        pass

    def log_info(self, message: str) -> None:
        """Log an info level message."""
        self.console.print(f"[blue]INFO:[/blue] {message}")

    def log_warning(self, message: str) -> None:
        """Log a warning level message."""
        self.console.print(f"[yellow]WARNING:[/yellow] {message}")

    def log_error(self, message: str) -> None:
        """Log an error level message."""
        self.console.print(f"[red]ERROR:[/red] {message}")

    def log_generation(self, stats: dict[str, Any]) -> None:
        """Log generation statistics from orchestrator."""
        generation = stats.get("generation", 0)
        best_score = stats.get("global_best_score")

        if best_score is not None:
            self.console.print(
                f"[bold green]Generation {generation}[/bold green] - "
                f"Global best score: [bold]{best_score:.4f}[/bold]"
            )
