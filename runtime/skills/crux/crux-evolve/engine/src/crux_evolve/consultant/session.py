"""Main session orchestrator for the merged chat command.

ConsultantSession coordinates the three-phase flow:
1. Needs Gathering — free-form conversation to understand the user's problem
2. Building — automatic pipeline (analyze → create → validate)
3. Review & Iterate — present results, accept modifications, confirm
"""

from __future__ import annotations

import signal
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table

from crux_evolve.consultant.advisor import (
    _CONFIRMED_MARKER,
    _MODIFY_EVALUATOR_MARKER,
    _REGENERATE_MARKER,
    LLMAdvisor,
)
from crux_evolve.consultant.build_orchestrator import BuildError, BuildOrchestrator
from crux_evolve.consultant.context_limiter import ContextLimits
from crux_evolve.consultant.needs import NeedsProfile
from crux_evolve.consultant.prompts import REVIEW_SYSTEM_PROMPT, build_review_prompt
from crux_evolve.consultant.review_loop import ReviewLoop
from crux_evolve.consultant.state import ConversationState, PhaseStatus
from crux_evolve.infra.provider.base import BaseProvider


class ConsultantSession:
    """Orchestrates the three-phase interactive chat session.

    Phase 1: Needs Gathering — conversational needs collection
    Phase 2: Building — automatic builder pipeline execution
    Phase 3: Review & Iterate — present and refine generated artifacts
    """

    def __init__(
        self,
        provider: BaseProvider,
        console: Console | None = None,
        resume_path: str | None = None,
        output_path: str = "./",
        provider_config: dict[str, Any] | None = None,
        max_repair_attempts: int = 3,
        prompt: str | None = None,
        non_interactive: bool = False,
        code_path: str | None = None,
        data_path: str | None = None,
        lang: str = "auto",
        context_limits: ContextLimits | None = None,
    ) -> None:
        """Initialize the session.

        Args:
            provider: LLM provider for conversations and building.
            console: Rich console for output. Creates one if not provided.
            resume_path: Path or session ID to resume from.
            output_path: Output directory for generated files.
            provider_config: Provider configuration dict to persist in session
                state for resume support.
            max_repair_attempts: Maximum auto-repair attempts during validation.
            prompt: Direct problem description (skips Phase 1 if provided).
            non_interactive: Skip all interactive phases (requires prompt).
            code_path: Path to existing algorithm code.
            data_path: Path to dataset directory or files.
            lang: Language mode — 'auto' (detect from first input),
                'en' (English), or 'zh' (Chinese).
            context_limits: Context window limits for conversation history.
        """
        self._console = console or Console()
        self._output_path = output_path
        self._max_repair = max_repair_attempts
        self._prompt = prompt
        self._non_interactive = non_interactive
        self._code_path = code_path
        self._data_path = data_path

        # Load or create state
        if resume_path:
            self._state = ConversationState.load(resume_path)
            self._console.print(
                f"[bold green]Resumed session:[/bold green] {self._state.session_id}"
            )
        else:
            self._state = ConversationState(output_path=output_path)

        # Persist provider config in state for future resume
        if provider_config:
            self._state.provider_config = provider_config

        # Apply language setting (skip if resuming with existing language)
        if lang != "auto":
            self._state.language = lang
        # If auto and no prior language (fresh session), leave None for detection

        # Initialize components
        self._advisor = LLMAdvisor(provider, self._console, self._state, context_limits)
        self._builder = BuildOrchestrator(
            provider, self._console, max_repair_attempts=max_repair_attempts
        )
        self._review = ReviewLoop(provider, self._console)
        self._provider = provider

        # Signal handling for graceful save
        self._original_sigint = signal.getsignal(signal.SIGINT)

    async def run(self) -> str | None:
        """Run the full three-phase session.

        Returns:
            Path to the generated config file if user chose to run immediately,
            None otherwise.
        """
        signal.signal(signal.SIGINT, self._handle_interrupt)

        try:
            self._print_welcome()

            # Phase 1: Needs Gathering (skipped if --prompt provided)
            if self._prompt:
                needs = NeedsProfile(
                    description=self._prompt,
                    code_path=self._code_path,
                    data_path=self._data_path,
                )
                self._console.print(
                    "\n[dim]Using provided prompt, skipping needs gathering.[/dim]"
                )
            else:
                needs = await self._run_needs_gathering()

            # Phase 2: Build
            blueprint = await self._run_build(needs)

            # Phase 3: Review & Iterate (skipped if --non-interactive)
            if self._non_interactive:
                task_dir = self._write_output(blueprint)
            else:
                task_dir = await self._run_review(blueprint, needs)

            # Offer to run the pipeline
            return self._offer_run(task_dir)

        finally:
            signal.signal(signal.SIGINT, self._original_sigint)

    async def _run_needs_gathering(self) -> NeedsProfile:
        """Phase 1: Gather user needs through conversation.

        Returns:
            Structured NeedsProfile.
        """
        self._state.current_phase_name = "needs_gathering"
        self._state.phase = PhaseStatus.IN_PROGRESS
        self._state.save()

        self._console.print()
        self._console.print(
            Panel(
                "[bold]Phase 1: Needs Gathering[/bold]\n"
                "Tell me about the problem you want to solve. "
                "I'll ask a few questions to understand your needs.",
                border_style="blue",
            )
        )

        # Run the conversational needs gathering
        needs_dict = await self._advisor.run_needs_gathering()

        # Build NeedsProfile from extracted data
        needs = NeedsProfile.from_dict(needs_dict)

        # Persist to state
        self._state.needs_profile = needs.to_dict()
        self._state.phase = PhaseStatus.COMPLETED
        self._state.save()

        return needs

    async def _run_build(self, needs: NeedsProfile):
        """Phase 2: Run the builder pipeline.

        Args:
            needs: Structured needs from Phase 1.

        Returns:
            Validated TaskBlueprint.

        Raises:
            BuildError: If build fails and user doesn't want to retry.
        """
        self._state.current_phase_name = "building"
        self._state.phase = PhaseStatus.IN_PROGRESS
        self._state.save()

        self._console.print()
        self._console.print(
            Panel(
                "[bold]Phase 2: Building[/bold]\n"
                "Generating evaluator, algorithm template, and configuration...",
                border_style="yellow",
            )
        )

        while True:
            try:
                blueprint = await self._builder.build(needs)
                self._state.phase = PhaseStatus.COMPLETED
                self._state.save()
                return blueprint
            except BuildError as e:
                self._console.print(
                    f"\n[bold red]Build failed:[/bold red] {e}\n"
                )
                if self._non_interactive:
                    raise
                retry = Confirm.ask(
                    "Would you like to provide more details and retry?",
                    default=True,
                )
                if not retry:
                    raise
                # Re-enter Phase 1 for more details
                self._console.print(
                    "\n[dim]Let's gather more information to help the builder.[/dim]"
                )
                additional = await self._advisor.run_needs_gathering()
                # Merge additional info into needs
                if additional.get("description"):
                    needs.description += "\n\n" + additional["description"]
                if additional.get("code_path"):
                    needs.code_path = additional["code_path"]
                if additional.get("data_path"):
                    needs.data_path = additional["data_path"]
                if additional.get("evaluation_hints"):
                    needs.evaluation_hints += "\n" + additional["evaluation_hints"]
                self._state.needs_profile = needs.to_dict()
                self._state.save()

    async def _run_review(self, blueprint, needs: NeedsProfile) -> str:
        """Phase 3: Review and iterate on generated artifacts.

        Args:
            blueprint: Validated TaskBlueprint from Phase 2.
            needs: Original needs profile.

        Returns:
            Path to the output directory.
        """
        from crux_evolve.builder.writer import write_task_directory

        self._state.current_phase_name = "review"
        self._state.phase = PhaseStatus.IN_PROGRESS
        self._state.save()

        self._console.print()
        self._console.print(
            Panel(
                "[bold]Phase 3: Review & Iterate[/bold]\n"
                "Here's what was generated. Please review and confirm.",
                border_style="green",
            )
        )

        while True:
            # Present the blueprint
            self._review.present_blueprint(blueprint)

            # Get LLM explanation and ask for user action
            review_prompt = build_review_prompt(
                evaluator_code=blueprint.evaluator_code,
                description=needs.description,
                metrics=blueprint.metrics,
                language=self._state.language,
            )
            response = await self._advisor.run_review_conversation(
                system_prompt=REVIEW_SYSTEM_PROMPT,
                initial_message=review_prompt,
                language=self._state.language,
            )

            # Parse action from response
            if _CONFIRMED_MARKER in response:
                break
            elif _MODIFY_EVALUATOR_MARKER in response:
                modification = response.split(_MODIFY_EVALUATOR_MARKER, 1)[1].strip()
                self._console.print(
                    "\n[dim]Applying modifications to evaluator...[/dim]"
                )
                try:
                    blueprint = await self._builder.rebuild_evaluator(
                        blueprint, modification, needs
                    )
                except BuildError as e:
                    self._console.print(
                        f"[bold red]Modification failed:[/bold red] {e}\n"
                        "Let's try again with different instructions."
                    )
            elif _REGENERATE_MARKER in response:
                self._console.print("\n[dim]Regenerating from scratch...[/dim]")
                blueprint = await self._builder.build(needs)
            else:
                # Default to confirmed if no clear marker
                break

        # Show generated config
        self._present_config(blueprint)

        # Ask if user has further questions
        while True:
            has_questions = Confirm.ask(
                "Do you have any questions or want to modify the config?",
                default=False,
            )
            if not has_questions:
                break
            # Let user describe the change via LLM conversation
            response = await self._advisor.run_review_conversation(
                system_prompt=REVIEW_SYSTEM_PROMPT,
                initial_message=(
                    "The user wants to discuss the generated configuration. "
                    "Help them understand or modify it. When done, output [CONFIRMED]."
                ),
                language=self._state.language,
            )
            if _MODIFY_EVALUATOR_MARKER in response:
                modification = response.split(_MODIFY_EVALUATOR_MARKER, 1)[1].strip()
                self._console.print(
                    "\n[dim]Applying modifications to evaluator...[/dim]"
                )
                try:
                    blueprint = await self._builder.rebuild_evaluator(
                        blueprint, modification, needs
                    )
                    self._review.present_blueprint(blueprint)
                    self._present_config(blueprint)
                except BuildError as e:
                    self._console.print(
                        f"[bold red]Modification failed:[/bold red] {e}"
                    )
            elif _REGENERATE_MARKER in response:
                self._console.print("\n[dim]Regenerating from scratch...[/dim]")
                blueprint = await self._builder.build(needs)
                self._review.present_blueprint(blueprint)
                self._present_config(blueprint)

        # Write to disk
        task_dir = write_task_directory(blueprint, self._output_path)
        task_dir_str = str(task_dir)

        self._state.phase = PhaseStatus.COMPLETED
        self._state.save()

        self._console.print()
        self._console.print(
            Panel(
                f"[bold green]Build complete![/bold green]\n\n"
                f"Output directory: [bold]{task_dir_str}[/bold]\n\n"
                f"Files generated:\n"
                f"  • {blueprint.evaluator_file_name}\n"
                f"  • {blueprint.algorithm_dir_name}/{blueprint.algorithm_file_name}\n"
                f"  • config.yaml\n"
                f"  • debug_run.py",
                border_style="green",
            )
        )

        return task_dir_str

    def _present_config(self, blueprint) -> None:
        """Display the generated config.yaml with syntax highlighting.

        Args:
            blueprint: TaskBlueprint containing config_yaml.
        """
        self._console.print()
        self._console.print(
            Panel(
                Syntax(
                    blueprint.config_yaml,
                    "yaml",
                    theme="monokai",
                    line_numbers=True,
                ),
                title="[bold]Generated Config: config.yaml[/bold]",
                border_style="blue",
            )
        )

    def _write_output(self, blueprint) -> str:
        """Write build output to disk without interactive review.

        Used in non-interactive mode to skip Phase 3.

        Args:
            blueprint: Validated TaskBlueprint from Phase 2.

        Returns:
            Path to the output directory.
        """
        from crux_evolve.builder.writer import write_task_directory

        task_dir = write_task_directory(blueprint, self._output_path)
        task_dir_str = str(task_dir)

        self._present_config(blueprint)

        self._console.print()
        self._console.print(
            Panel(
                f"[bold green]Build complete![/bold green]\n\n"
                f"Output directory: [bold]{task_dir_str}[/bold]\n\n"
                f"Files generated:\n"
                f"  • {blueprint.evaluator_file_name}\n"
                f"  • {blueprint.algorithm_dir_name}/{blueprint.algorithm_file_name}\n"
                f"  • config.yaml\n"
                f"  • debug_run.py",
                border_style="green",
            )
        )

        return task_dir_str

    def _offer_run(self, task_dir: str) -> str | None:
        """Ask user if they want to run the pipeline immediately.

        In non-interactive mode, prints run instructions and returns None.

        Args:
            task_dir: Path to the generated task directory.

        Returns:
            Config path if user wants to run, None otherwise.
        """
        if self._non_interactive:
            self._console.print(
                f"\n[dim]To run:[/dim]\n"
                f"  crux_evolve run {task_dir}/config.yaml\n\n"
                f"[dim]To test locally first:[/dim]\n"
                f"  python {task_dir}/debug_run.py"
            )
            return None

        self._console.print()
        run_now = Confirm.ask(
            "Would you like to start the evolution pipeline now?",
            default=False,
        )
        if run_now:
            return f"{task_dir}/config.yaml"

        self._console.print(
            f"\n[dim]To run later:[/dim]\n"
            f"  crux_evolve run {task_dir}/config.yaml\n\n"
            f"[dim]To test locally first:[/dim]\n"
            f"  python {task_dir}/debug_run.py"
        )
        return None

    def _print_welcome(self) -> None:
        """Print the welcome banner."""
        self._console.print()
        self._console.print(
            Panel(
                "[bold blue]CruxEvolve Interactive Builder[/bold blue]\n\n"
                "I'll help you set up an algorithm design pipeline through conversation.\n"
                "Type [bold]quit[/bold] or press Ctrl+C at any time to save and exit.",
                border_style="blue",
            )
        )

    def _handle_interrupt(self, signum: int, frame: Any) -> None:
        """Handle Ctrl+C by saving state and exiting gracefully."""
        self._console.print("\n\n[yellow]Interrupted. Saving session...[/yellow]")
        try:
            self._state.save()
            self._console.print(
                f"[green]Session saved.[/green] Resume with: "
                f"[bold]crux_evolve chat --resume {self._state.session_id}[/bold]"
            )
        except OSError as e:
            self._console.print(f"[red]Failed to save session: {e}[/red]")

        signal.signal(signal.SIGINT, self._original_sigint)
        sys.exit(130)

    @staticmethod
    def list_saved_sessions() -> None:
        """Print a table of saved sessions."""
        from datetime import datetime

        console = Console()
        sessions = ConversationState.list_sessions()

        if not sessions:
            console.print("[dim]No saved sessions found.[/dim]")
            return

        table = Table(title="Saved Sessions")
        table.add_column("Session ID", style="cyan")
        table.add_column("Phase", style="magenta")
        table.add_column("Created", style="green")

        for s in sessions:
            created = datetime.fromtimestamp(s["created_at"]).strftime("%Y-%m-%d %H:%M")
            table.add_row(
                s["session_id"],
                s.get("current_phase") or "-",
                created,
            )

        console.print(table)
        console.print(
            "\n[dim]Resume with: crux_evolve chat --resume <session_id>[/dim]"
        )
