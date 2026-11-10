"""Repository analysis for finding evolvable regions (EVOLVE blocks).

This module provides infrastructure for analyzing existing code repositories
to discover regions marked for evolution with EVOLVE comment markers,
and extracts them with surrounding context for use in LLM prompts.
"""

from crux_evolve.infra.repo_analyzer.base import (
    AnalyzedRepository,
    BaseRepositoryAnalyzer,
    EvolveBlock,
)
from crux_evolve.infra.repo_analyzer.evolve_detector import EvolveDetector
from crux_evolve.infra.repo_analyzer.marker_tools import (
    BlockSpan,
    CleanResult,
    FileReport,
    InspectResult,
    MarkerIssue,
    classify_marker,
    clean_path,
    inspect_path,
    strip_marker_lines,
    validate_markers,
)

__all__ = [
    "AnalyzedRepository",
    "BaseRepositoryAnalyzer",
    "BlockSpan",
    "CleanResult",
    "EvolveBlock",
    "EvolveDetector",
    "FileReport",
    "InspectResult",
    "MarkerIssue",
    "classify_marker",
    "clean_path",
    "inspect_path",
    "strip_marker_lines",
    "validate_markers",
]
