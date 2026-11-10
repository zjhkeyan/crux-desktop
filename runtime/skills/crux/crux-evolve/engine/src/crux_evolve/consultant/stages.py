"""Phase definitions for the merged chat command.

The merged chat uses a 3-phase architecture instead of the previous
12-stage system. Each phase represents a distinct mode of interaction.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseDefinition:
    """Definition of a conversation phase."""

    name: str
    display_name: str
    description: str


PHASES: dict[str, PhaseDefinition] = {
    "needs_gathering": PhaseDefinition(
        name="needs_gathering",
        display_name="Needs Gathering",
        description=(
            "Free-form conversation to understand the user's problem. "
            "Collects: problem description, code path, dataset path, "
            "evaluation criteria, and any other relevant context."
        ),
    ),
    "building": PhaseDefinition(
        name="building",
        display_name="Building",
        description=(
            "Automatic build phase. Runs the builder pipeline "
            "(analyze → create → validate) without user interaction."
        ),
    ),
    "review": PhaseDefinition(
        name="review",
        display_name="Review & Iterate",
        description=(
            "Present generated evaluator and config to the user. "
            "Explain the evaluation logic, accept modifications, "
            "and iterate until the user confirms."
        ),
    ),
}

PHASE_ORDER: list[str] = ["needs_gathering", "building", "review"]


def get_phase(name: str) -> PhaseDefinition:
    """Get a phase definition by name.

    Args:
        name: Phase name.

    Returns:
        The matching PhaseDefinition.

    Raises:
        ValueError: If phase name is not found.
    """
    if name in PHASES:
        return PHASES[name]
    raise ValueError(f"Unknown phase: {name}")
