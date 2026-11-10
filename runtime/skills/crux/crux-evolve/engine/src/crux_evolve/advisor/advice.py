"""Data classes produced by the evolve-block advisor.

The advisor analyzes a user-selected code block (an EVOLVE block or an
arbitrary region a user has highlighted in the frontend) against a stated
algorithm-evolution goal, and returns structured feedback the frontend
can render next to the selection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# Single source of truth for the LLM-output language flag threaded through
# advisor / recommender. Extend this Literal to add more languages later.
Lang = Literal["en", "zh"]
SUPPORTED_LANGS: tuple[Lang, ...] = ("en", "zh")


@dataclass
class BlockAdvice:
    """Structured advice about a single candidate evolve block.

    All fields are JSON-serializable so the CLI can stream the result to
    a frontend without custom encoders.

    Attributes:
        block_summary: One to three sentences describing what the block
            currently does. Grounded in the block content, not the goal.
        feasibility: One of ``"yes"``, ``"partial"``, ``"no"``. Whether
            evolving this block can plausibly move the goal metric.
        feasibility_reason: Short justification for the feasibility verdict.
        significance: One of ``"high"``, ``"medium"``, ``"low"``. How
            impactful successfully evolving this block would be relative
            to the stated goal.
        significance_reason: Short justification for the significance
            verdict.
        concerns: Bullet list of risks or pitfalls the user should know
            before launching evolution on this block.
        suggestions: Bullet list of concrete, actionable refinements
            (e.g., extend the block to include a helper, narrow it to
            only the scoring function, add a metric).
        rationale: One-paragraph overall assessment tying feasibility,
            significance, concerns, and suggestions together.
        score: Optional numeric score reserved for ranking when multiple
            candidate blocks are compared. Populated by the recommender
            layer, not by single-block advice.
        block_ref: Optional reference to the block that was analyzed
            (file path, line range, block name). Useful for frontends
            that display results next to the source selection.
        lang: Language used for the LLM's free-text fields. ``"en"`` (the
            default) means English; ``"zh"`` means Simplified Chinese.
            Set by the advisor at request time so frontends can render
            the result without re-detecting.
    """

    block_summary: str = ""
    feasibility: str = ""
    feasibility_reason: str = ""
    significance: str = ""
    significance_reason: str = ""
    concerns: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    rationale: str = ""
    score: float | None = None
    block_ref: dict[str, Any] | None = None
    lang: Lang = "en"

    _VALID_FEASIBILITY = ("yes", "partial", "no")
    _VALID_SIGNIFICANCE = ("high", "medium", "low")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return asdict(self)

    @classmethod
    def from_llm_json(
        cls,
        data: dict[str, Any],
        *,
        block_ref: dict[str, Any] | None = None,
        lang: Lang = "en",
    ) -> BlockAdvice:
        """Build a BlockAdvice from a raw LLM JSON response.

        Unknown fields are ignored, missing fields fall back to sensible
        defaults. Feasibility and significance are normalized to lowercase
        and constrained to the allowed vocabulary; anything else becomes
        the empty string.

        Args:
            data: Parsed JSON dict returned by the LLM.
            block_ref: Optional pointer to the analyzed block to attach
                to the result.
            lang: Language used to drive the LLM call. Stored on the
                returned advice so frontends can render correctly.

        Returns:
            A populated BlockAdvice instance.
        """
        feas = str(data.get("feasibility", "")).strip().lower()
        if feas not in cls._VALID_FEASIBILITY:
            feas = ""
        sig = str(data.get("significance", "")).strip().lower()
        if sig not in cls._VALID_SIGNIFICANCE:
            sig = ""

        return cls(
            block_summary=str(data.get("block_summary", "")).strip(),
            feasibility=feas,
            feasibility_reason=str(data.get("feasibility_reason", "")).strip(),
            significance=sig,
            significance_reason=str(data.get("significance_reason", "")).strip(),
            concerns=_as_str_list(data.get("concerns")),
            suggestions=_as_str_list(data.get("suggestions")),
            rationale=str(data.get("rationale", "")).strip(),
            block_ref=block_ref,
            lang=lang,
        )


def _as_str_list(value: Any) -> list[str]:
    """Coerce an LLM-supplied value into a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


@dataclass
class AdviseResult:
    """Top-level envelope for one or many block advice runs.

    Both single-block (``advise_block``) and multi-block (``advise_blocks``,
    triggered by the CLI's ``--all`` flag) paths return this type so the
    frontend never needs to discriminate. Single-block runs produce one
    entry in ``results``; multi-block runs produce N. Per-block failures
    are recorded in ``errors`` so a single failing block does not abort
    the whole run.

    Attributes:
        goal: The user's evolution goal (echoed for frontend display).
        repo_path: Absolute POSIX path of the repo, or ``None`` for
            ``--code`` mode where there is no repo.
        lang: Language used to drive the LLM call(s). Echoed at the
            envelope level so a frontend can render labels without
            inspecting individual results.
        count: Convenience field equal to ``len(results)``.
        results: One :class:`BlockAdvice` per successfully analyzed block.
            Order is the order in which blocks were discovered by
            :class:`~crux_evolve.infra.repo_analyzer.evolve_detector.EvolveDetector`.
        errors: One entry per block whose analysis failed, shaped
            ``{"block_id", "file_path", "line_start", "line_end", "error"}``.
    """

    goal: str
    repo_path: str | None
    lang: Lang
    count: int
    results: list[BlockAdvice] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return {
            "goal": self.goal,
            "repo_path": self.repo_path,
            "lang": self.lang,
            "count": self.count,
            "results": [r.to_dict() for r in self.results],
            "errors": list(self.errors),
        }

    @classmethod
    def single(
        cls,
        advice: BlockAdvice,
        *,
        goal: str,
        repo_path: str | None,
        lang: Lang,
    ) -> AdviseResult:
        """Wrap a single :class:`BlockAdvice` in the standard envelope."""
        return cls(
            goal=goal,
            repo_path=repo_path,
            lang=lang,
            count=1,
            results=[advice],
            errors=[],
        )
