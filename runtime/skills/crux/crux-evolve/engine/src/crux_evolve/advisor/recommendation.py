"""Data classes produced by the evolve-block recommender.

The recommender scans a repository against a user goal and proposes
single-block evolution targets grouped into three tiers:

- ``core``        — the most promising minimal block
- ``expanded``    — widenings of the core block (optional)
- ``alternatives``— other standalone blocks elsewhere (optional)

CruxEvolve's evolution engine is single-block-only today, so picking any
recommendation replaces the others; tiers are *choices*, not a set to
co-evolve. See [src/crux_evolve/planner/sampler/init_sampler.py:102] and
siblings for the single-block constraint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from crux_evolve.advisor.advice import BlockAdvice, Lang

Tier = Literal["core", "expanded", "alternative"]


@dataclass
class BlockRecommendation:
    """A single recommended block together with its advice.

    Attributes:
        file_path: Path relative to the repo root.
        line_start: 1-based inclusive start line.
        line_end: 1-based inclusive end line.
        tier: Which tier this recommendation belongs to.
        variant_index: Sort order within the expanded tier (None for
            core and alternatives).
        size_lines: ``line_end - line_start + 1``.
        discovery_rationale: Short justification the discovery LLM gave
            for proposing this block.
        advice: Phase 1 :class:`BlockAdvice` for this block. ``None``
            when advice enrichment failed for this block specifically.
        advice_error: Error message recorded when ``advice`` is ``None``.
    """

    file_path: str
    line_start: int
    line_end: int
    tier: Tier
    variant_index: int | None = None
    size_lines: int = 0
    discovery_rationale: str = ""
    advice: BlockAdvice | None = None
    advice_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        data = asdict(self)
        # asdict() turned nested BlockAdvice into a dict already.
        return data


@dataclass
class RepoRecommendations:
    """Full recommender output for a single (repo, goal) request.

    Attributes:
        goal: The goal the user passed in.
        repo_path: Absolute path of the analyzed repository.
        core: The core recommendation. ``None`` only if the discovery
            call itself succeeded but the LLM refused to produce one;
            in that case the recommender raises instead of returning,
            so in practice ``core`` is always populated on success.
        expanded: Expanded variants of core, sorted by ``size_lines``
            ascending.
        alternatives: Alternative blocks outside the core region.
        unreadable_files: Files skipped during repo compaction
            (permission / decode errors).
        dropped_candidates: LLM-proposed candidates that failed
            validation, each entry shaped
            ``{"file_path", "line_start", "line_end", "tier", "reason"}``.
        discovery_raw: Unparsed LLM text, attached only when the caller
            passes ``include_raw=True``.
        lang: Language used for the LLM's free-text fields (rationales,
            advice). ``"en"`` (the default) keeps current English
            behaviour; ``"zh"`` indicates the result was generated under
            a Simplified Chinese directive.
    """

    goal: str
    repo_path: str
    core: BlockRecommendation | None = None
    expanded: list[BlockRecommendation] = field(default_factory=list)
    alternatives: list[BlockRecommendation] = field(default_factory=list)
    unreadable_files: list[str] = field(default_factory=list)
    dropped_candidates: list[dict[str, Any]] = field(default_factory=list)
    discovery_raw: str | None = None
    lang: Lang = "en"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return {
            "goal": self.goal,
            "repo_path": self.repo_path,
            "core": self.core.to_dict() if self.core is not None else None,
            "expanded": [r.to_dict() for r in self.expanded],
            "alternatives": [r.to_dict() for r in self.alternatives],
            "unreadable_files": list(self.unreadable_files),
            "dropped_candidates": list(self.dropped_candidates),
            "discovery_raw": self.discovery_raw,
            "lang": self.lang,
        }
