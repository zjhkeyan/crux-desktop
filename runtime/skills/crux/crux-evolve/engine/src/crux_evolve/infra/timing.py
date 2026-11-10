"""Shared timing models for CruxEvolve execution and evaluation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ExecutionTiming(BaseModel):
    """Unified timing breakdown for a candidate or run."""

    wall_time_ms: float = 0.0
    llm_planning_ms: float = 0.0
    llm_coding_ms: float = 0.0
    evaluation_total_ms: float = 0.0
    candidate_runtime_ms: float = 0.0
    overhead_ms: float = 0.0

    model_config = ConfigDict(frozen=False)

    def add(self, other: ExecutionTiming) -> ExecutionTiming:
        """Add another timing breakdown in-place."""
        self.wall_time_ms += other.wall_time_ms
        self.llm_planning_ms += other.llm_planning_ms
        self.llm_coding_ms += other.llm_coding_ms
        self.evaluation_total_ms += other.evaluation_total_ms
        self.candidate_runtime_ms += other.candidate_runtime_ms
        self.overhead_ms += other.overhead_ms
        return self

    def recompute_overhead(self) -> ExecutionTiming:
        """Recompute wall-clock overhead from the known sub-phases."""
        accounted = self.llm_planning_ms + self.llm_coding_ms + self.evaluation_total_ms
        self.overhead_ms = max(0.0, self.wall_time_ms - accounted)
        return self

    @classmethod
    def from_llm_stage(cls, stage: str, latency_ms: float) -> ExecutionTiming:
        """Create a timing payload from a single LLM request."""
        timing = cls(wall_time_ms=latency_ms)
        if stage == "planner":
            timing.llm_planning_ms = latency_ms
        elif stage == "coder":
            timing.llm_coding_ms = latency_ms
        return timing


class EvaluationBreakdown(BaseModel):
    """Detailed timing breakdown for a single evaluator invocation."""

    runtime_ms: float = 0.0
    setup_ms: float = 0.0
    parse_ms: float = 0.0
    validation_ms: float = 0.0
    total_ms: float = 0.0

    model_config = ConfigDict(frozen=False)
