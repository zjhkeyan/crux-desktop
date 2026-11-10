"""Orchestrator layer for CruxEvolve.

Controls the main evolution workflow: Planner → Coder → Evaluator loop.
Implements search algorithms (GA, Evolution Strategy) and workflow management.
"""

from crux_evolve.infra.state import (
    GenerationMetrics,
    ModuleTiming,
    ResourceUsage,
    StateTracker,
    StateTrackerConfig,
)
from crux_evolve.orchestrator.base import (
    BaseOrchestrator,
    EvolutionCheckpoint,
    EvolutionConfig,
    EvolutionResult,
    EvolutionState,
)
from crux_evolve.orchestrator.dyca import DyCAConfig, DyCAOrchestrator
from crux_evolve.orchestrator.eoh import EoHOrchestrator, EoHPopulation
from crux_evolve.orchestrator.island_ga import (
    DiverseIslandGAConfig,
    DiverseIslandGAOrchestrator,
    Island,
    IslandGAConfig,
    IslandGAOrchestrator,
    MigrationStrategy,
    MigrationTopology,
)
from crux_evolve.orchestrator.mcts_ahd import MCTSAHDOrchestrator
from crux_evolve.orchestrator.meoh import MEoHOrchestrator
from crux_evolve.orchestrator.meoh_population import MEoHPopulation
from crux_evolve.orchestrator.reevo import ReEvoOrchestrator

__all__ = [
    # Base
    "BaseOrchestrator",
    "EvolutionState",
    "EvolutionResult",
    "EvolutionConfig",
    "EvolutionCheckpoint",
    # Island GA
    "IslandGAOrchestrator",
    "IslandGAConfig",
    "DiverseIslandGAOrchestrator",
    "DiverseIslandGAConfig",
    "Island",
    "MigrationStrategy",
    "MigrationTopology",
    # DyCA
    "DyCAOrchestrator",
    "DyCAConfig",
    # MEoH
    "MEoHOrchestrator",
    "MEoHPopulation",
    # EoH
    "EoHOrchestrator",
    "EoHPopulation",
    # ReEvo
    "ReEvoOrchestrator",
    # MCTS-AHD
    "MCTSAHDOrchestrator",
    # State tracking
    "StateTracker",
    "StateTrackerConfig",
    "ModuleTiming",
    "ResourceUsage",
    "GenerationMetrics",
]
