"""Needs profile data model for the merged chat command.

NeedsProfile is the output of Phase 1 (needs gathering) and the input
to Phase 2 (build). It captures the user's problem description, code
references, dataset paths, and evaluation hints collected during the
conversational needs-gathering phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NeedsProfile:
    """Structured output of the needs-gathering conversation.

    Captures everything the builder pipeline needs to generate
    evaluator code, algorithm templates, and pipeline config.
    """

    description: str
    """Natural language problem description."""

    code_path: str | None = None
    """Path to existing algorithm code (enables from_code mode)."""

    data_path: str | None = None
    """Path to dataset directory or files."""

    metrics_hints: list[str] = field(default_factory=list)
    """User-provided hints about evaluation metrics (e.g., 'minimize distance')."""

    evaluation_hints: str = ""
    """Free-form description of how algorithms should be evaluated."""

    project_name: str | None = None
    """User-specified project name (optional, auto-generated if not provided)."""

    multimodal: bool = False
    """Whether to generate multimodal evaluator with visualization support."""

    visualization_hint: str | None = None
    """User-provided visualization requirements for multimodal mode."""

    language: str = "python"
    """Programming language for generated algorithm code."""

    extra_context: dict[str, Any] = field(default_factory=dict)
    """Additional context gathered from file reads or conversation."""

    existing_evaluator_path: str | None = None
    """Path to existing evaluator script if user chose to reuse one."""

    use_existing_evaluator: bool = False
    """Whether user chose to use existing evaluator instead of generating new one."""

    def has_code(self) -> bool:
        """Check if user provided existing code."""
        return self.code_path is not None

    def has_data(self) -> bool:
        """Check if user provided dataset."""
        return self.data_path is not None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for state persistence."""
        return {
            "description": self.description,
            "code_path": self.code_path,
            "data_path": self.data_path,
            "metrics_hints": self.metrics_hints,
            "evaluation_hints": self.evaluation_hints,
            "project_name": self.project_name,
            "multimodal": self.multimodal,
            "visualization_hint": self.visualization_hint,
            "language": self.language,
            "extra_context": self.extra_context,
            "existing_evaluator_path": self.existing_evaluator_path,
            "use_existing_evaluator": self.use_existing_evaluator,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NeedsProfile:
        """Deserialize from dict."""
        return cls(
            description=data.get("description", ""),
            code_path=data.get("code_path"),
            data_path=data.get("data_path"),
            metrics_hints=data.get("metrics_hints", []),
            evaluation_hints=data.get("evaluation_hints", ""),
            project_name=data.get("project_name"),
            multimodal=data.get("multimodal", False),
            visualization_hint=data.get("visualization_hint"),
            language=data.get("language", "python"),
            extra_context=data.get("extra_context", {}),
            existing_evaluator_path=data.get("existing_evaluator_path"),
            use_existing_evaluator=data.get("use_existing_evaluator", False),
        )
