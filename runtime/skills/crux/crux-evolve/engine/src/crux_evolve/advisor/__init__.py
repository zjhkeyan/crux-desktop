"""Evolve-block advisor for CruxEvolve.

On-demand analysis for a user-selected code block against a stated
algorithm-evolution goal. Returns structured feedback — feasibility,
significance, concerns, suggestions, rationale — that a frontend can
render next to the user's selection before committing to an expensive
evolution run.

Direct API::

    from crux_evolve.advisor import advise_block_sync

    advice = advise_block_sync(
        goal="minimize comparisons on random inputs",
        repo_path="./my_solver/",
        file_path="src/algo.py",
        line_range=(42, 87),
        api_key="sk-...",
        model="gpt-4o",
    )
    print(advice.to_dict())

Config-based API (recommended for multi-user platforms)::

    from crux_evolve.advisor import generate_advisor_config, advise_from_config_sync

    generate_advisor_config("advise_config.yaml", goal="...")
    # user fills in credentials, then:
    advice = advise_from_config_sync("advise_config.yaml")

The advisor is fully independent from :mod:`crux_evolve.builder` — it reads
only public utilities from :mod:`crux_evolve.infra.repo_analyzer` and
:mod:`crux_evolve.infra.provider`.
"""

from crux_evolve.advisor.advice import AdviseResult, BlockAdvice
from crux_evolve.advisor.advisor_config import (
    AdviseTaskConfig,
    AdvisorConfig,
    AdvisorLLMConfig,
    generate_advisor_config,
    load_advisor_config,
)
from crux_evolve.advisor.analyzer import BlockAdvisor
from crux_evolve.advisor.pipeline import (
    AdvisorError,
    advise_block,
    advise_block_sync,
    advise_blocks,
    advise_blocks_sync,
    advise_from_config,
    advise_from_config_sync,
    find_block_by_id,
)
from crux_evolve.advisor.recommendation import BlockRecommendation, RepoRecommendations
from crux_evolve.advisor.recommender import (
    RepoRecommender,
    recommend_blocks,
    recommend_blocks_sync,
)

__all__ = [
    "AdviseResult",
    "AdviseTaskConfig",
    "AdvisorConfig",
    "AdvisorError",
    "AdvisorLLMConfig",
    "BlockAdvice",
    "BlockAdvisor",
    "BlockRecommendation",
    "RepoRecommendations",
    "RepoRecommender",
    "advise_block",
    "advise_block_sync",
    "advise_blocks",
    "advise_blocks_sync",
    "advise_from_config",
    "advise_from_config_sync",
    "find_block_by_id",
    "generate_advisor_config",
    "load_advisor_config",
    "recommend_blocks",
    "recommend_blocks_sync",
]
