"""CruxEvolve Consultant — interactive pipeline builder assistant.

Provides an LLM-powered multi-turn conversation interface that helps
users set up algorithm design pipelines through a three-phase flow:
1. Needs Gathering — understand the user's problem
2. Building — automatically generate evaluator and config
3. Review & Iterate — present results and accept modifications
"""

from crux_evolve.consultant.core import (
    Choice,
    NeedsGatheringContext,
    NeedsGatheringResponse,
    ResponseType,
    ReviewAction,
    ReviewContext,
    ReviewResponse,
    detect_language,
    extract_needs_profile,
    process_needs_gathering_turn,
    process_needs_gathering_turn_stream,
    process_review_turn,
    process_review_turn_stream,
)
from crux_evolve.consultant.session import ConsultantSession

__all__ = [
    "Choice",
    "ConsultantSession",
    "NeedsGatheringContext",
    "NeedsGatheringResponse",
    "ResponseType",
    "ReviewAction",
    "ReviewContext",
    "ReviewResponse",
    "detect_language",
    "extract_needs_profile",
    "process_needs_gathering_turn",
    "process_needs_gathering_turn_stream",
    "process_review_turn",
    "process_review_turn_stream",
]
