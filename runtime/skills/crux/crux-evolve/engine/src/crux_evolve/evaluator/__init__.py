"""Evaluator layer for CruxEvolve.

Responsible for measuring algorithm quality through evaluation tasks and metrics.
"""

from crux_evolve.evaluator.base import (
    BaseEvaluator,
    BenchmarkEvaluator,
    EvaluationResult,
    ExecutableEvaluator,
    Metric,
    MetricType,
    PythonEvaluator,
)
from crux_evolve.evaluator.behavior import BehaviorData, BehaviorVisualization
from crux_evolve.evaluator.dispatcher import EvaluationDispatcher
from crux_evolve.evaluator.llm_judge import LLMJudgeEvaluator
from crux_evolve.evaluator.solver.evaluator import SolverEvaluator
from crux_evolve.evaluator.task import Task, TaskConfig, TaskType

__all__ = [
    # Base types
    "BaseEvaluator",
    "EvaluationResult",
    "EvaluationDispatcher",
    # Behavior data
    "BehaviorData",
    "BehaviorVisualization",
    # Concrete base classes
    "PythonEvaluator",
    "ExecutableEvaluator",
    "BenchmarkEvaluator",
    "LLMJudgeEvaluator",
    "SolverEvaluator",
    # Task management
    "Task",
    "TaskConfig",
    "TaskType",
    # Metric types
    "Metric",
    "MetricType",
]
