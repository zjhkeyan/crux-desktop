"""Coder layer for CruxEvolve.

Wraps existing coding agents (e.g., Claude Code, OpenCode) to implement
algorithms from natural language insights.
"""

from crux_evolve.coder.base import (
    BaseCoder,
    CodingAgentType,
    GenerateResult,
    GenerateStatus,
)
from crux_evolve.coder.claude_code import ClaudeCode
from crux_evolve.coder.custom_naive_coder import CustomNaiveCoder
from crux_evolve.coder.opencode import OpenCode

__all__ = [
    "BaseCoder",
    "GenerateResult",
    "GenerateStatus",
    "CodingAgentType",
    "ClaudeCode",
    "CustomNaiveCoder",
    "OpenCode",
]
