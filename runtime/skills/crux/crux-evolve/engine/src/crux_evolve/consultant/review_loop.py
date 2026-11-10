"""Review loop for Phase 3 of the merged chat command.

Handles presenting the generated evaluator and config to the user,
explaining the evaluation logic, and iterating on modifications
until the user confirms.
"""

from __future__ import annotations

from enum import Enum

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from crux_evolve.builder.blueprint import TaskBlueprint
from crux_evolve.consultant.needs import NeedsProfile
from crux_evolve.infra.provider.base import BaseProvider, ChatMessage


class ReviewAction(str, Enum):
    """Possible user actions during review."""

    CONFIRM = "confirm"
    MODIFY_EVALUATOR = "modify_evaluator"
    MODIFY_CONFIG = "modify_config"
    REGENERATE = "regenerate"


REVIEW_SYSTEM_PROMPT = """\
You are reviewing generated code for an algorithm design pipeline. \
Your role is to:
1. Explain the evaluator logic clearly and concisely
2. Help the user understand what the code does
3. When the user wants changes, determine the appropriate action

## Response Format
After explaining the code, ask the user if they want to:
  1) Confirm and save — everything looks good
  2) Modify the evaluator — change evaluation logic
  3) Modify the config — adjust pipeline parameters
  4) Regenerate — start over with different approach

IMPORTANT: Each numbered choice MUST be on its own line, indented with exactly \
2 spaces, using the format "  N) label — description".

## When User Requests Changes
If the user describes a modification to the evaluator, output [MODIFY_EVALUATOR] \
followed by a clear description of what to change.

If the user wants to change config parameters, output [MODIFY_CONFIG] followed \
by the specific changes.

If the user wants to regenerate everything, output [REGENERATE].

If the user confirms, output [CONFIRMED].
"""

EXPLAIN_EVALUATOR_PROMPT = """\
Explain the following evaluator code to the user in a clear, concise way. \
Focus on:
1. What problem it evaluates
2. How algorithms are scored (metrics and their meaning)
3. What input/output format is expected
4. Any important implementation details

Keep the explanation under 10 sentences. Use the user's language if they \
wrote in a non-English language during the conversation.

## Evaluator Code:
```python
{evaluator_code}
```

## Original Problem Description:
{description}
"""


class ReviewLoop:
    """Manages the Phase 3 review and iteration cycle.

    Presents generated artifacts to the user, explains the evaluation
    logic via LLM, and handles modification requests.
    """

    def __init__(
        self,
        provider: BaseProvider,
        console: Console | None = None,
    ) -> None:
        """Initialize the review loop.

        Args:
            provider: LLM provider for explanations and modifications.
            console: Rich console for output.
        """
        self._provider = provider
        self._console = console or Console()

    def present_blueprint(self, blueprint: TaskBlueprint) -> None:
        """Display the generated evaluator code and config summary.

        Args:
            blueprint: The validated blueprint to present.
        """
        self._console.print()
        self._console.print(
            Panel(
                Syntax(
                    blueprint.evaluator_code,
                    "python",
                    theme="monokai",
                    line_numbers=True,
                ),
                title=f"[bold]Generated Evaluator: {blueprint.evaluator_file_name}[/bold]",
                border_style="green",
            )
        )

        self._console.print()
        metrics_text = ", ".join(
            f"{m['name']} ({m.get('type', 'minimize')})" for m in blueprint.metrics
        )
        self._console.print(
            Panel(
                f"[bold]Project:[/bold] {blueprint.project_name}\n"
                f"[bold]Function to evolve:[/bold] {blueprint.function_to_evolve}\n"
                f"[bold]Metrics:[/bold] {metrics_text}\n"
                f"[bold]Algorithm:[/bold] {blueprint.algorithm_dir_name}/{blueprint.algorithm_file_name}",
                title="[bold]Config Summary[/bold]",
                border_style="blue",
            )
        )

    async def explain_evaluator(
        self, blueprint: TaskBlueprint, needs: NeedsProfile
    ) -> str:
        """Generate a natural language explanation of the evaluator.

        Args:
            blueprint: Blueprint containing the evaluator code.
            needs: Original needs for context.

        Returns:
            Explanation text from the LLM.
        """
        prompt = EXPLAIN_EVALUATOR_PROMPT.format(
            evaluator_code=blueprint.evaluator_code,
            description=needs.description,
        )
        messages = [
            ChatMessage(role="system", content=REVIEW_SYSTEM_PROMPT),
            ChatMessage(role="user", content=prompt),
        ]
        result = await self._provider.chat(messages)
        return result.text

    def parse_review_action(self, response: str) -> tuple[ReviewAction, str]:
        """Parse the user's review action from LLM response.

        Args:
            response: LLM response text.

        Returns:
            Tuple of (action, detail). Detail contains modification
            description for modify actions, empty string otherwise.
        """
        if "[CONFIRMED]" in response:
            return ReviewAction.CONFIRM, ""
        if "[MODIFY_EVALUATOR]" in response:
            detail = response.split("[MODIFY_EVALUATOR]", 1)[1].strip()
            return ReviewAction.MODIFY_EVALUATOR, detail
        if "[MODIFY_CONFIG]" in response:
            detail = response.split("[MODIFY_CONFIG]", 1)[1].strip()
            return ReviewAction.MODIFY_CONFIG, detail
        if "[REGENERATE]" in response:
            return ReviewAction.REGENERATE, ""
        return ReviewAction.CONFIRM, ""
