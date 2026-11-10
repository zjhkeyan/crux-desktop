"""Conversation state management for the Consultant module.

Tracks conversation progress through phases, stores collected configuration
data, and supports save/resume functionality.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PhaseStatus(str, Enum):
    """Status of a conversation phase."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class StageStatus(str, Enum):
    """Status of a conversation stage (kept for backward compatibility)."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class StageState(BaseModel):
    """State of a single conversation stage (kept for backward compatibility)."""

    status: StageStatus = StageStatus.PENDING
    collected_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured config fragment collected during this stage",
    )


class ConversationState(BaseModel):
    """Full conversation state, serializable for resume support.

    Tracks the current phase, needs profile, blueprint data, and
    full chat message history for LLM context continuity.
    """

    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    phase: PhaseStatus = Field(
        default=PhaseStatus.PENDING,
        description="Current phase: pending (not started), in_progress (gathering needs), completed",
    )
    current_phase_name: str = Field(
        default="needs_gathering",
        description="Name of the current phase: needs_gathering, building, review",
    )
    needs_profile: dict[str, Any] = Field(
        default_factory=dict,
        description="Serialized NeedsProfile from Phase 1",
    )
    blueprint_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Serialized TaskBlueprint metadata from Phase 2",
    )
    stages: dict[str, StageState] = Field(default_factory=dict)
    messages: list[dict[str, str]] = Field(
        default_factory=list,
        description="Full chat history as [{role, content}, ...]",
    )
    template_name: str | None = Field(
        default=None,
        description="Name of the template used as starting point",
    )
    provider_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider configuration for resume (type, api_key, model, base_url)",
    )
    created_at: float = Field(default_factory=time.time)
    output_path: str = "./"
    user_context: str | None = Field(
        default=None,
        description="Context extracted from early conversation (e.g., file reads, problem descriptions)",
    )
    language: str | None = Field(
        default=None,
        description="Detected conversation language ('zh', 'en') for consistent LLM responses",
    )

    @property
    def current_stage(self) -> str | None:
        """Return the name of the first non-completed stage, or None."""
        for name, state in self.stages.items():
            if state.status in (StageStatus.PENDING, StageStatus.IN_PROGRESS):
                return name
        return None

    def is_complete(self) -> bool:
        """Check if all phases are completed."""
        return self.current_phase_name == "review" and self.phase == PhaseStatus.COMPLETED

    def save(self, path: Path | None = None) -> Path:
        """Save state to JSON file with restricted permissions.

        Args:
            path: File path. If None, uses default session directory.

        Returns:
            The path where state was saved.
        """
        if path is None:
            session_dir = Path.home() / ".crux_evolve" / "sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            path = session_dir / f"{self.session_id}.json"

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = self.model_dump_json(indent=2)
        path.write_text(data, encoding="utf-8")

        # Set restricted permissions (owner read/write only) for API key safety
        with contextlib.suppress(OSError):
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

        return path

    @classmethod
    def load(cls, path_or_id: str) -> ConversationState:
        """Load state from a JSON file or session ID.

        Args:
            path_or_id: Either a file path or a session ID.
                If it looks like a path (contains / or .json), load directly.
                Otherwise treat as session ID and look in default directory.

        Returns:
            Loaded ConversationState.

        Raises:
            FileNotFoundError: If state file doesn't exist.
        """
        if "/" in path_or_id or path_or_id.endswith(".json"):
            path = Path(path_or_id)
        else:
            path = Path.home() / ".crux_evolve" / "sessions" / f"{path_or_id}.json"

        if not path.exists():
            raise FileNotFoundError(f"Session state not found: {path}")

        data = path.read_text(encoding="utf-8")
        return cls.model_validate_json(data)

    @classmethod
    def list_sessions(cls) -> list[dict[str, Any]]:
        """List all saved sessions in the default directory.

        Returns:
            List of dicts with session_id, created_at, template_name, and path.
        """
        session_dir = Path.home() / ".crux_evolve" / "sessions"
        if not session_dir.exists():
            return []

        sessions = []
        for f in sorted(session_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", f.stem),
                    "created_at": data.get("created_at", 0),
                    "template_name": data.get("template_name"),
                    "current_phase": data.get("current_phase_name", "unknown"),
                    "path": str(f),
                })
            except (json.JSONDecodeError, OSError):
                continue

        return sessions
