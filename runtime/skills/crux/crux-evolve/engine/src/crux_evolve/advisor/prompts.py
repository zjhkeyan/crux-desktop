"""Prompts for the evolve-block advisor.

These prompts are intentionally independent from ``builder/prompts.py``.
The builder's ``CLASSIFY_EVOLVE_ROLE_PROMPT`` is optimized for extracting
role/schema/helper information to drive code generation. This module's
prompt is optimized for producing user-facing feasibility, significance,
concerns, and suggestions about a selected block versus a stated goal.
"""

from __future__ import annotations

from crux_evolve.advisor.advice import Lang


def language_directive(lang: Lang) -> str:
    """Return a prompt prefix that constrains the LLM's response language.

    The directive only affects free-text fields (rationale, reasons,
    summary, concerns, suggestions, discovery_rationale). JSON keys,
    enum values (``yes``/``partial``/``no``, ``high``/``medium``/``low``),
    file paths, and code snippets are explicitly out of scope so the
    structured shape stays parseable.

    Args:
        lang: Target language. ``"en"`` returns the empty string so the
            existing English prompts are byte-identical; ``"zh"`` returns
            a Simplified-Chinese instruction block.

    Returns:
        A string to prepend to a prompt template; trailing newline included
        when non-empty so the body that follows reads naturally.
    """
    if lang == "zh":
        return (
            "IMPORTANT: Respond in Simplified Chinese (中文) for all "
            "free-text fields (rationale, reasons, summary, concerns, "
            "suggestions, discovery_rationale). Keep the JSON keys, "
            "enum values (yes/partial/no, high/medium/low), file paths, "
            "and code snippets unchanged.\n\n"
        )
    return ""


ADVISE_BLOCK_PROMPT = """\
{lang_directive}You are an expert reviewer for an LLM-driven algorithm-evolution platform.
A user has highlighted a code block they are considering evolving. Your job
is to decide how promising that choice is, and to surface concrete advice
they can act on BEFORE they launch an expensive evolution run.

=== USER GOAL ===
{goal}

=== SELECTED BLOCK ===
File: {file_path}
Lines: {line_start}-{line_end}
Language: {language}
Block name: {block_name}

```{language}
{block_content}
```

=== SURROUNDING CONTEXT ===
Context BEFORE the block:
```{language}
{context_before}
```

Context AFTER the block:
```{language}
{context_after}
```

=== TASK ===
Analyze the selected block in light of the user's goal and respond with a
single JSON object. Do NOT include commentary, markdown, or code fences
around the JSON.

Your analysis must address:

1. **block_summary** — In 1-3 plain sentences, say what THIS block does
   today, grounded in its code (not the goal). Reference concrete names
   from the block.

2. **feasibility** — Can evolving this block plausibly move the goal's
   metric? Choose one of:
     - "yes"     — the block sits on the critical path for the goal
     - "partial" — improvements help but are limited by surrounding code
     - "no"      — changes here are unlikely to affect the goal
   Then **feasibility_reason** — 1-2 sentences explaining the verdict,
   citing concrete evidence from the block or its context (e.g., "this
   function is called once at startup, so its runtime has no effect on
   steady-state throughput").

3. **significance** — If evolution succeeds, how big is the impact?
     - "high"   — a material change in the goal metric
     - "medium" — noticeable but bounded
     - "low"    — cosmetic or marginal
   Then **significance_reason** — 1-2 sentences. Measure against the
   GOAL, not against generic code quality.

4. **concerns** — A list of 0-5 risks or pitfalls specific to evolving
   THIS block. Examples: hidden coupling to external state, narrow
   input-type assumptions, side effects, non-determinism, tests that
   would mask regressions. Skip generic advice.

5. **suggestions** — A list of 0-5 concrete, actionable refinements the
   user should make BEFORE launching evolution. Examples: "also mark the
   helper at lines X-Y as part of the block", "narrow the block to just
   the scoring function", "add a unit test covering edge case Z".
   Each suggestion must be directly tied to the block you see.

6. **rationale** — One paragraph (2-4 sentences) tying the verdicts
   together. Speak directly to the user.

=== OUTPUT SCHEMA ===
{{
  "block_summary": "...",
  "feasibility": "yes | partial | no",
  "feasibility_reason": "...",
  "significance": "high | medium | low",
  "significance_reason": "...",
  "concerns": ["...", "..."],
  "suggestions": ["...", "..."],
  "rationale": "..."
}}

Return only the JSON object.
"""
