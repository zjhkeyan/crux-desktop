"""Utility modules for CruxEvolve.

Includes the registry system for plugin management and diff utilities.
"""

from crux_evolve.utils.diff_utils import (
    apply_unified_diff,
    generate_unified_diff,
    hash_content,
    parse_diff_stats,
    validate_diff,
)
from crux_evolve.utils.registry import Registrable, Registry

__all__ = [
    "Registry",
    "Registrable",
    "hash_content",
    "generate_unified_diff",
    "apply_unified_diff",
    "validate_diff",
    "parse_diff_stats",
]
