"""Backward-compatible re-exports.

All config classes previously defined here have been split into
domain-specific modules under ``crux_evolve.config``:

- ``evaluator``: DatasetConfig, MetricPatternConfig, EvaluatorConfig, etc.
- ``coder``: CoderConfig, ClaudeCodeConfig, OpenCodeConfig, CustomCoderConfig
- ``memory``: MemoryCardConfig, AutoExtractionConfig, MemoryConfig
- ``planner``: SamplerConfig, BuildConfig, PlannerConfig
- ``app``: ProviderConfig, WorkspaceConfig, LoggingConfig, RepoAnalyzerConfig, AppConfig

Prefer importing directly from the specific submodule.
"""

from crux_evolve.config.app import (  # noqa: F401
    AppConfig,
    LoggingConfig,
    ProviderConfig,
    RepoAnalyzerConfig,
    WorkspaceConfig,
)
from crux_evolve.config.coder import (  # noqa: F401
    ClaudeCodeConfig,
    CoderConfig,
    CustomCoderConfig,
    OpenCodeConfig,
)
from crux_evolve.config.evaluator import (  # noqa: F401
    CustomEvaluatorConfig,
    DatasetConfig,
    EvalContext,
    EvaluatorConfig,
    ExecutableEvaluatorConfig,
    MetricPatternConfig,
    SolverEvaluatorConfig,
    SolverMetricConfig,
)
from crux_evolve.config.evolution import (  # noqa: F401
    DiverseIslandGAConfig,
    DyCAConfig,
    EvolutionConfig,
    IslandGAConfig,
)
from crux_evolve.config.memory import (  # noqa: F401
    AutoExtractionConfig,
    MemoryCardConfig,
    MemoryConfig,
)
from crux_evolve.config.planner import (  # noqa: F401
    BuildConfig,
    PlannerConfig,
    SamplerConfig,
)
