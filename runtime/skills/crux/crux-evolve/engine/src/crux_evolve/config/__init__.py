"""Configuration management for CruxEvolve.

Handles loading, validation, and schema definition for all configuration.
"""

from crux_evolve.config.app import (
    AppConfig,
    LoggingConfig,
    ProviderConfig,
    RepoAnalyzerConfig,
    WorkspaceConfig,
)
from crux_evolve.config.coder import (
    ClaudeCodeConfig,
    CoderConfig,
    CustomCoderConfig,
    OpenCodeConfig,
)
from crux_evolve.config.evaluator import (
    CustomEvaluatorConfig,
    DatasetConfig,
    EvalContext,
    EvaluatorConfig,
    ExecutableEvaluatorConfig,
    MetricPatternConfig,
    SolverEvaluatorConfig,
    SolverMetricConfig,
)
from crux_evolve.config.evolution import (
    DiverseIslandGAConfig,
    DyCAConfig,
    EvolutionConfig,
    IslandGAConfig,
    MEoHConfig,
)
from crux_evolve.config.memory import (
    AutoExtractionConfig,
    MemoryCardConfig,
    MemoryConfig,
)
from crux_evolve.config.planner import (
    BuildConfig,
    PlannerConfig,
    SamplerConfig,
)
from crux_evolve.config.settings import (
    get_default_settings_path,
    load_global_settings,
    load_yaml_with_env_expansion,
    merge_with_global_settings,
)

__all__ = [
    # app
    "AppConfig",
    "ProviderConfig",
    "WorkspaceConfig",
    "LoggingConfig",
    "RepoAnalyzerConfig",
    # evaluator
    "DatasetConfig",
    "MetricPatternConfig",
    "EvaluatorConfig",
    "CustomEvaluatorConfig",
    "ExecutableEvaluatorConfig",
    "SolverEvaluatorConfig",
    "SolverMetricConfig",
    "EvalContext",
    # coder
    "CoderConfig",
    "ClaudeCodeConfig",
    "OpenCodeConfig",
    "CustomCoderConfig",
    # memory
    "MemoryCardConfig",
    "AutoExtractionConfig",
    "MemoryConfig",
    # planner
    "SamplerConfig",
    "BuildConfig",
    "PlannerConfig",
    # evolution
    "EvolutionConfig",
    "DyCAConfig",
    "IslandGAConfig",
    "DiverseIslandGAConfig",
    # settings
    "MEoHConfig",
    "get_default_settings_path",
    "load_global_settings",
    "load_yaml_with_env_expansion",
    "merge_with_global_settings",
]
