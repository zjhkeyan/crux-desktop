"""Prompt templates for the evolve-block recommender.

Independent from both :mod:`crux_evolve.advisor.prompts` and
:mod:`crux_evolve.builder.prompts`. The recommender's discovery prompt asks the
LLM to propose concrete ``(file, line_start, line_end)`` tuples given a
compacted view of the repo — very different from single-block advice or
from builder's spec extraction.
"""

DISCOVER_BLOCKS_PROMPT = """\
{lang_directive}You are an expert reviewer for an LLM-driven algorithm-evolution platform.
A user has pointed our platform at their repository and stated a goal.
CruxEvolve can only evolve ONE code block per run, so your job is to pick
which block(s) the user should consider evolving.

=== USER GOAL ===
{goal}

=== REPOSITORY ===
Root: {repo_path}

File tree:
{file_tree}

Selected file contents (truncated when necessary):
{file_contents}

=== TASK ===
Propose code blocks that a user might evolve to move the goal metric.
Group your proposals into three tiers:

1. **core** (REQUIRED): the single most promising MINIMAL block. Keep
   the range as tight as possible while still covering the logic that
   matters for the goal. Cheapest to evolve, highest-confidence win.

2. **expanded** (optional, 0-3 entries): widenings of the core block in
   the SAME FILE and overlapping the core line range. Each variant
   grows core by pulling in related helpers, setup code, or a
   surrounding function. Higher potential yield, higher token cost.
   Do NOT propose an expansion that leaves core's file or drops core's
   lines.

3. **alternatives** (optional, 0-3 entries): other standalone blocks in
   the repo that are independently worth evolving. An alternative must
   NOT overlap core (it's a different evolution choice the user could
   make instead). Each alternative should be minimal-and-self-contained,
   like core.

Rules you MUST follow:
- All ``file_path`` values must be relative paths that appear in the
  file tree above.
- ``line_start`` and ``line_end`` must be 1-based, inclusive, and fall
  within the file's length.
- ``line_start <= line_end``.
- If a file's content is not shown above, DO NOT propose blocks inside
  it — you cannot reason about code you have not seen.
- Do not invent file paths. Do not round line numbers to "nice" values.
- ``rationale`` for each block: 1-2 sentences tying the block to the
  goal. Reference concrete names from the code.

=== OUTPUT SCHEMA ===
Respond with a single JSON object and nothing else (no prose, no code
fences):

{{
  "core": {{
    "file_path": "...",
    "line_start": N,
    "line_end": M,
    "rationale": "..."
  }},
  "expanded": [
    {{"file_path": "...", "line_start": N, "line_end": M, "rationale": "..."}}
  ],
  "alternatives": [
    {{"file_path": "...", "line_start": N, "line_end": M, "rationale": "..."}}
  ]
}}

``expanded`` and ``alternatives`` may be empty arrays if you do not see
good options. ``core`` must be present.
"""
