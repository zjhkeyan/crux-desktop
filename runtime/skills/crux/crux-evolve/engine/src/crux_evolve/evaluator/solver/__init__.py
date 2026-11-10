"""Generic solver-backed evaluation primitives."""

from crux_evolve.evaluator.solver.base import (
    BaseSolverAdapter,
    SolverContext,
    SolverRunResult,
    SolverValidationResult,
)
from crux_evolve.evaluator.solver.evaluator import SolverEvaluator
from crux_evolve.evaluator.solver.parameter_search import (
    ParameterSearchResult,
    ParameterSpace,
    TunableParameter,
    maximize_bounded_parameters,
)

__all__ = [
    "BaseSolverAdapter",
    "ParameterSearchResult",
    "ParameterSpace",
    "SolverContext",
    "SolverEvaluator",
    "SolverRunResult",
    "SolverValidationResult",
    "TunableParameter",
    "maximize_bounded_parameters",
]
