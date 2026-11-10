"""Base sampler interface for CruxEvolve.

This module defines the abstract interface for algorithm samplers that generate
new algorithm insights (natural language descriptions) for the evolution process.
"""

from abc import ABC, abstractmethod
from typing import Any

from crux_evolve.config.schema import SamplerConfig
from crux_evolve.infra.provider.base import BaseProvider
from crux_evolve.infra.repo_analyzer import AnalyzedRepository
from crux_evolve.planner.base import Algorithm
from crux_evolve.utils.registry import Registrable


class BaseSampler(ABC, Registrable):
    """Abstract base class for algorithm samplers.

    Samplers are responsible for generating new algorithm insights (natural language
    descriptions) from the current population and evolution context. The planner
    then uses these insights to generate complete algorithm individuals with code.
    """

    def __init__(
        self,
        provider: BaseProvider,
        memory: Any,
        config: SamplerConfig,
        analyzed_repository: AnalyzedRepository,
    ):
        """Initialize the sampler.

        Args:
            provider: LLM provider for generating insights
            memory: Memory system for storing/retrieving past experiences
            config: Sampler configuration dictionary
            analyzed_repository: Pre-analyzed repository with EVOLVE blocks
        """
        self.provider = provider
        self.memory = memory
        self.config = config
        self.analyzed_repository = analyzed_repository

    @property
    @abstractmethod
    def n_parents(self) -> int:
        """Number of parents required for sampling."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the sampler name."""
        ...

    @abstractmethod
    async def sample(
        self,
        parents: list[Algorithm],
        generation: int,
        **kwargs,
    ) -> Algorithm:
        """Sample a new algorithm insight.

        Generates a new algorithm description in natural language based on:
        - Task background and constraints
        - Current population of evolved algorithms
        - Memory of past successes and failures
        - Evolution context

        Args:
            parents: Current population of algorithms
            generation: Current generation number
            **kwargs: Additional sampling parameters

        Returns:
            Algorithm containing the new insight (only natural language description,
            code artifacts will be added later by the coder/planner).
        """
        ...

    def _get_config_value(self, key, *dicts, default=None):
        """Retrieve the value for `key` from the given dictionaries in order.

        Returns the value from the first dictionary that contains the key.
        If no dictionary contains the key, returns `default`.

        Uses ``key in d`` instead of ``d.get(key)`` to properly handle values
        that are falsy (e.g., ``0``, ``""``, ``False``).
        """
        for d in dicts:
            if d and key in d:  # Use `key in d` to avoid falsy value issues
                return d[key]
        return default
