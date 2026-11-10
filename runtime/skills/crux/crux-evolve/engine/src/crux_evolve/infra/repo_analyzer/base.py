"""Base interface for repository analysis.

Defines the abstract interface and data structures for repository analysis
that finds evolvable regions (EVOLVE blocks) in codebases.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from crux_evolve.utils.registry import Registrable


@dataclass
class EvolveBlock:
    """Represents a discovered EVOLVE block in the code.

    Stores all information about the block including:
    - Location (file path, line numbers)
    - Original content
    - Surrounding context for LLM prompt building
    - Detected programming language
    """

    file_path: str  #: Relative path from repository root
    absolute_path: Path  #: Absolute file path on disk
    line_start: int  #: Starting line number (1-based)
    line_end: int  #: Ending line number (1-based)
    comment_style: str  #: Comment style used ("#", "//", "/* */", "<!-- -->")
    block_name: str  #: Optional name from after "EVOLVE START"
    original_content: str  #: Original content inside the block
    context_before: str  #: Code context before the block (configurable number of lines)
    context_after: str  #: Code context after the block (configurable number of lines)
    language: str  #: Detected programming language


@dataclass
class AnalyzedRepository:
    """Result of repository analysis containing all discovered EVOLVE blocks.

    Returned by the analyzer after complete repository scan. Provides
    summary statistics along with the complete list of blocks.
    """

    repo_path: Path  #: Root path of the analyzed repository
    evolvable_blocks: list[EvolveBlock]  #: All discovered EVOLVE blocks
    files_analyzed: int  #: Total number of files scanned
    files_with_blocks: int  #: Number of files that contained at least one EVOLVE block
    file_type_counts: dict[str, int]  #: Count of discovered files by file extension


class BaseRepositoryAnalyzer(ABC, Registrable):
    """Base interface for repository analyzers.

    Implementations analyze a code repository to discover evolvable regions
    (marked with EVOLVE comments) and extract them with surrounding context
    for use during evolution.
    """

    @abstractmethod
    def analyze(self, repo_path: Path | str) -> AnalyzedRepository:
        """Analyze the repository at the given path and find all evolvable regions.

        Args:
            repo_path: Path to the repository root (can be absolute or relative)

        Returns:
            AnalyzedRepository containing all discovered EVOLVE blocks
            along with summary statistics.
        """
        ...
