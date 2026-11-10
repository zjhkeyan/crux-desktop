"""Single-shot block advisor.

Given an :class:`~crux_evolve.infra.repo_analyzer.base.EvolveBlock` and a user
goal, call the LLM once and return a populated
:class:`~crux_evolve.advisor.advice.BlockAdvice`.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from crux_evolve.advisor.advice import BlockAdvice, Lang
from crux_evolve.advisor.prompts import ADVISE_BLOCK_PROMPT, language_directive
from crux_evolve.infra.provider.base import BaseProvider
from crux_evolve.infra.repo_analyzer.base import EvolveBlock


class BlockAdvisor:
    """Produces a :class:`BlockAdvice` for a single (block, goal) pair.

    The advisor is intentionally stateless and thread-safe aside from
    the provider it wraps, so a long-running frontend can instantiate
    one per request.
    """

    def __init__(self, provider: BaseProvider):
        """Initialize the advisor.

        Args:
            provider: Live LLM provider used to run the advice prompt.
        """
        self._provider = provider

    async def advise(
        self,
        goal: str,
        block: EvolveBlock,
        *,
        temperature: float = 0.2,
        lang: Lang = "en",
    ) -> BlockAdvice:
        """Run the advisor on a single block.

        Args:
            goal: The user's stated algorithm-evolution goal.
            block: The candidate block to analyze.
            temperature: LLM sampling temperature. Low by default for
                stable judgments.
            lang: Language for the LLM's free-text output. ``"en"`` (the
                default) keeps current behaviour; ``"zh"`` instructs the
                model to respond in Simplified Chinese without changing
                the JSON schema.

        Returns:
            A populated ``BlockAdvice``. If the LLM response cannot be
            parsed as JSON, the raw text is recorded in ``rationale``
            and the structured fields are left at their defaults.
        """
        prompt = ADVISE_BLOCK_PROMPT.format(
            lang_directive=language_directive(lang),
            goal=goal.strip(),
            file_path=block.file_path,
            line_start=block.line_start,
            line_end=block.line_end,
            language=block.language or "text",
            block_name=block.block_name or "(unnamed)",
            block_content=block.original_content,
            context_before=block.context_before,
            context_after=block.context_after,
        )

        result = await self._provider.generate(prompt, temperature=temperature)
        block_ref = {
            "file_path": block.file_path,
            "line_start": block.line_start,
            "line_end": block.line_end,
            "block_name": block.block_name,
            "language": block.language,
        }

        parsed = _parse_json_response(result.text)
        if parsed is None:
            logger.warning(
                "Advisor could not parse JSON from LLM response; "
                "returning raw text in rationale."
            )
            return BlockAdvice(
                rationale=result.text.strip(),
                block_ref=block_ref,
                lang=lang,
            )
        return BlockAdvice.from_llm_json(parsed, block_ref=block_ref, lang=lang)


def _parse_json_response(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from an LLM response.

    Mirrors the tolerant parsing done by builder's analyzer so we stay
    robust to markdown fences and leading prose.

    Args:
        text: Raw text returned by the LLM.

    Returns:
        Parsed dict on success, ``None`` on failure.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        stripped = "\n".join(lines).strip()

    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            obj = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None

    return obj if isinstance(obj, dict) else None
