"""LLM-powered conversation advisor for the Consultant.

Drives multi-turn conversations for needs gathering (Phase 1)
and review iteration (Phase 3).
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console

from crux_evolve.consultant.context_limiter import ContextLimits
from crux_evolve.consultant.state import ConversationState
from crux_evolve.infra.provider.base import BaseProvider, ChatMessage, ToolCall, ToolDefinition

# Markers that the LLM uses to signal phase transitions
_STAGE_COMPLETE_MARKER = "[STAGE_COMPLETE]"
_NEEDS_COMPLETE_MARKER = "[NEEDS_COMPLETE]"
_CONFIRMED_MARKER = "[CONFIRMED]"
_MODIFY_EVALUATOR_MARKER = "[MODIFY_EVALUATOR]"
_MODIFY_CONFIG_MARKER = "[MODIFY_CONFIG]"
_REGENERATE_MARKER = "[REGENERATE]"

# Maximum number of lines to read from a file
_MAX_FILE_LINES = 500

# ---------------------------------------------------------------------------
# Choice detection — parse numbered options from LLM responses
# ---------------------------------------------------------------------------

# Matches lines like "  1) openai — recommended" or "  2) 自定义输入"
_CHOICE_LINE_RE = re.compile(
    r"^\s{2,}(\d+)\)\s+(.+)$",
    re.MULTILINE,
)

# Heuristic for detecting "enter your own value" variants (EN + ZH)
_CUSTOM_INPUT_RE = re.compile(
    r"(?i)"
    r"(?:enter|type|input|provide|specify|write|custom|other|自定义|输入|自行填写|手动输入|其他)"
)

# Strip "(recommended)" and variants from a label
_RECOMMENDED_RE = re.compile(r"\s*\(recommended[^)]*\)", re.IGNORECASE)

# Detect [PATH] tag appended by LLM to file-path-related choices
_PATH_TAG_RE = re.compile(r"\s*\[PATH\]", re.IGNORECASE)

# Detect [DIR] tag appended by LLM to directory-path-related choices
_DIR_TAG_RE = re.compile(r"\s*\[DIR\]", re.IGNORECASE)

# Extract the options block between [OPTIONS_START] and [OPTIONS_END]
_OPTIONS_BLOCK_RE = re.compile(
    r"\[OPTIONS_START\](.*?)\[OPTIONS_END\]",
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class ParsedChoice:
    """A single choice parsed from an LLM response."""

    number: int
    label: str
    description: str
    full_text: str
    is_custom: bool
    is_recommended: bool
    ask_for_path: bool = False
    ask_for_dir: bool = False


def parse_choices(response: str) -> list[ParsedChoice] | None:
    """Parse numbered choice blocks from an LLM response.

    Prefers extracting from [OPTIONS_START]...[OPTIONS_END] markers if present.
    Falls back to scanning the full response for the last contiguous block of
    sequentially-numbered choices (``1)``, ``2)``, ``3)`` ...).

    Args:
        response: Full LLM response text.

    Returns:
        List of parsed choices, or ``None`` if no valid block found.
    """
    # Prefer the marked options block if present
    block_match = _OPTIONS_BLOCK_RE.search(response)
    search_text = block_match.group(1) if block_match else response

    matches = list(_CHOICE_LINE_RE.finditer(search_text))
    if len(matches) < 2:
        return None

    # Group into contiguous blocks of sequential numbering
    blocks: list[list[re.Match[str]]] = []
    current_block: list[re.Match[str]] = [matches[0]]

    for prev, curr in zip(matches, matches[1:], strict=False):
        prev_num = int(prev.group(1))
        curr_num = int(curr.group(1))
        if curr_num == prev_num + 1:
            current_block.append(curr)
        else:
            blocks.append(current_block)
            current_block = [curr]
    blocks.append(current_block)

    # Take the last block that starts from 1 and has >= 2 items
    chosen_block: list[re.Match[str]] | None = None
    for block in reversed(blocks):
        if len(block) >= 2 and int(block[0].group(1)) == 1:
            chosen_block = block
            break

    if chosen_block is None:
        return None

    result: list[ParsedChoice] = []
    for m in chosen_block:
        number = int(m.group(1))
        full_text = m.group(2).strip()

        # Detect and strip [PATH] tag
        ask_for_path = bool(_PATH_TAG_RE.search(full_text))
        if ask_for_path:
            full_text = _PATH_TAG_RE.sub("", full_text).strip()

        # Detect and strip [DIR] tag
        ask_for_dir = bool(_DIR_TAG_RE.search(full_text))
        if ask_for_dir:
            full_text = _DIR_TAG_RE.sub("", full_text).strip()

        # Split on " — " (em-dash) or " - " (spaced hyphen)
        if " — " in full_text:
            label, description = full_text.split(" — ", 1)
        elif " - " in full_text:
            label, description = full_text.split(" - ", 1)
        else:
            label, description = full_text, ""

        is_recommended = bool(_RECOMMENDED_RE.search(label))
        label = _RECOMMENDED_RE.sub("", label).strip()

        result.append(ParsedChoice(
            number=number,
            label=label,
            description=description.strip(),
            full_text=full_text,
            is_custom=False,
            is_recommended=is_recommended,
            ask_for_path=ask_for_path,
            ask_for_dir=ask_for_dir,
        ))

    # Mark last item as custom-input if it matches the heuristic
    if result and _CUSTOM_INPUT_RE.search(result[-1].full_text):
        result[-1].is_custom = True

    return result

# Tool definitions for the advisor
READ_FILE_TOOL = ToolDefinition(
    name="read_file",
    description=(
        "Read the contents of a file. Use when the user mentions a file path "
        "or you need to inspect a file to help with configuration."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path (relative or absolute)",
            },
        },
        "required": ["path"],
    },
)

LIST_DIRECTORY_TOOL = ToolDefinition(
    name="list_directory",
    description=(
        "List the contents of a directory as a tree structure, and auto-read "
        "key files (README, main entry points, configs). Use when the user "
        "provides a directory/folder path or you need to understand a project structure."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path (relative or absolute)",
            },
        },
        "required": ["path"],
    },
)


class LLMAdvisor:
    """Drives LLM-powered conversation for each configuration stage.

    For each stage, the advisor:
    1. Builds a system prompt with schema knowledge and context
    2. Runs a multi-turn conversation until the LLM signals completion
    3. Extracts structured config data via a separate LLM call
    4. Returns the extracted data dict
    """

    def __init__(
        self,
        provider: BaseProvider,
        console: Console,
        state: ConversationState,
        context_limits: ContextLimits | None = None,
    ) -> None:
        """Initialize the advisor.

        Args:
            provider: LLM provider for conversation.
            console: Rich console for terminal output.
            state: Shared conversation state.
            context_limits: Optional context window limits. Uses defaults if None.
        """
        self._provider = provider
        self._console = console
        self._state = state
        self._context_limits = context_limits or ContextLimits()
        self._prompt_session: PromptSession[str] = PromptSession(history=InMemoryHistory())

    @staticmethod
    def _execute_read_file_fn(path: str) -> str:
        """File reader callable for the stateless core function.

        Args:
            path: File path to read.

        Returns:
            File contents or error message.
        """
        resolved = Path(path).expanduser().resolve()
        if resolved.is_dir():
            return (
                f"Error: '{path}' is a directory, not a file. "
                "Use the list_directory tool instead."
            )
        if not resolved.is_file():
            return f"Error: File not found: {path}"
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"Error reading file: {e}"
        lines = content.splitlines()
        if len(lines) > _MAX_FILE_LINES:
            content = (
                "\n".join(lines[:_MAX_FILE_LINES])
                + f"\n\n... (truncated, {len(lines)} total lines)"
            )
        return content

    async def run_context_gathering(self) -> str | None:
        """Run a brief context-gathering conversation before main stages.

        Asks the user if they have documentation files or problem descriptions
        to share. Reads any provided files via tool calls and extracts a
        context summary for use in later stages.

        Returns:
            Context summary string, or None if user has nothing to share.
        """
        system_prompt = (
            "You are the CruxEvolve Configuration Consultant. Before diving into "
            "configuration, you want to understand the user's problem.\n\n"
            "Ask the user ONE question: whether they have a file (README, spec, "
            "problem description, existing config) or a text description of the "
            "problem they want to solve. Present it as choices:\n\n"
            "  1) I have a file — provide its path\n"
            "  2) I'll describe my problem briefly\n"
            "  3) Skip — go straight to configuration\n\n"
            "If the user provides a file path, use the read_file tool to read it. "
            "After reading, briefly confirm what you understood and ask if there's "
            "anything else to add.\n\n"
            "If the user provides a text description, acknowledge it and ask if "
            "there's anything else to add.\n\n"
            "When done (user says skip, no, or confirms the summary), respond "
            "with [CONTEXT_DONE] at the end of your message.\n\n"
            "You may use the user's language (e.g., Chinese) if they write in it."
        )

        messages: list[dict[str, str]] = [
            {"role": "user", "content": "I'm about to start configuring my pipeline."},
        ]
        self._state.messages.append(messages[0])

        response = await self._chat_with_tools(system_prompt, messages)
        messages.append({"role": "assistant", "content": response})
        self._state.messages.append(
            {"role": "assistant", "content": response.replace("[CONTEXT_DONE]", "").strip()}
        )
        self._auto_save()

        while True:
            user_input = await self._get_user_input_for_response(response)

            if user_input.lower() in ("skip", "/skip", "3"):
                return None

            messages.append({"role": "user", "content": user_input})
            self._state.messages.append({"role": "user", "content": user_input})

            response = await self._chat_with_tools(system_prompt, messages)
            messages.append({"role": "assistant", "content": response})
            self._state.messages.append(
                {"role": "assistant", "content": response.replace("[CONTEXT_DONE]", "").strip()}
            )
            self._auto_save()

            if "[CONTEXT_DONE]" in response:
                break

        # Extract a concise context summary from the conversation
        return await self._extract_context_summary(messages)

    async def _extract_context_summary(
        self,
        messages: list[dict[str, str]],
    ) -> str | None:
        """Extract a concise context summary from the gathering conversation.

        Args:
            messages: Messages from the context-gathering conversation.

        Returns:
            A text summary of relevant info, or None if nothing substantial.
        """
        conversation_text = ""
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "system":
                continue
            label = "User" if role == "user" else "Consultant"
            conversation_text += f"{label}: {content}\n\n"

        extraction_prompt = (
            "From the following conversation, extract information relevant to "
            "configuring an CruxEvolve algorithm design pipeline. Focus on:\n\n"
            "- Problem description / background (what the user wants to evolve)\n"
            "- File paths mentioned (evaluator, config, code repository, dataset)\n"
            "- Programming language and code structure\n"
            "- Evaluation approach (metrics, scoring)\n"
            "- Any other configuration hints\n\n"
            "Output a concise bullet-point summary. If the conversation contains "
            "no substantial information, output exactly: NONE\n\n"
            f"## Conversation:\n{conversation_text}\n\nExtract now:"
        )

        result = await self._provider.generate(extraction_prompt)
        text = result.text.strip()

        if not text or text.upper() == "NONE":
            return None
        return text

    async def run_needs_gathering(self) -> dict[str, Any]:
        """Run Phase 1: free-form needs gathering conversation.

        Uses the stateless core function in a loop, handling CLI-specific
        I/O (streaming output, interactive selection, text input).

        Returns:
            Extracted needs profile dict.
        """
        from crux_evolve.consultant.core import (
            NeedsGatheringContext,
            NeedsGatheringResponse,
            ResponseType,
            detect_language,
            process_needs_gathering_turn_stream,
        )

        phase_messages: list[dict[str, str]] = []
        user_input: str | None = None
        language: str | None = self._state.language

        while True:
            ctx = NeedsGatheringContext(
                phase_messages=phase_messages,
                user_context=self._state.user_context,
                user_input=user_input,
                language=language,
                context_limits=self._context_limits,
            )

            # Stream the response to the console
            self._console.print()
            self._console.print("[bold green]Consultant >[/bold green] ", end="")

            response: NeedsGatheringResponse | None = None
            stream = process_needs_gathering_turn_stream(
                ctx, self._provider, file_reader=self._execute_read_file_fn,
            )
            async for item in stream:
                if isinstance(item, str):
                    self._console.print(item, end="", markup=False, highlight=False)
                else:
                    response = item
            self._console.print()

            assert response is not None

            # Update local state
            phase_messages = response.updated_messages
            if user_input is None:
                self._state.messages.append(
                    {"role": "user", "content": "I'd like to set up an algorithm design pipeline."}
                )
            self._state.messages.append(
                {"role": "assistant", "content": response.assistant_message}
            )
            self._auto_save()

            # Log tool calls
            for tc_info in response.tool_calls_executed:
                self._console.print(f"[dim]  Reading {tc_info['path']}...[/dim]")

            if response.response_type == ResponseType.COMPLETE:
                return response.needs_profile or {"description": self._state.user_context or ""}

            # Collect user input
            if response.choices:
                user_input = await self._interactive_select_from_core_choices(response.choices)
            else:
                user_input = await self._get_user_input()

            if user_input.lower() in ("quit", "/quit", "exit", "/exit"):
                raise KeyboardInterrupt("User requested exit")

            # Detect language from first real user input
            if language is None:
                language = detect_language(user_input)
                self._state.language = language

            self._state.messages.append({"role": "user", "content": user_input})

    async def run_review_conversation(
        self,
        system_prompt: str,
        initial_message: str,
        language: str | None = None,
    ) -> str:
        """Run a review conversation and return the LLM's final response with action marker.

        Uses the stateless core function in a loop, handling CLI-specific
        I/O (streaming output, interactive selection).

        Args:
            system_prompt: System prompt for the review phase.
            initial_message: Initial user message to start the review.
            language: Language code for consistent LLM responses.

        Returns:
            Final LLM response containing an action marker.
        """
        from crux_evolve.consultant.core import (
            ReviewAction,
            ReviewContext,
            ReviewResponse,
            process_review_turn_stream,
        )

        phase_messages: list[dict[str, str]] = []
        user_input: str | None = None
        is_first_turn = True

        while True:
            ctx = ReviewContext(
                phase_messages=phase_messages,
                system_prompt=system_prompt,
                user_input=user_input,
                initial_message=initial_message if is_first_turn else None,
                language=language,
                context_limits=self._context_limits,
            )

            # Stream the response to the console
            self._console.print()
            self._console.print("[bold green]Consultant >[/bold green] ", end="")

            response: ReviewResponse | None = None
            stream = process_review_turn_stream(ctx, self._provider)
            async for item in stream:
                if isinstance(item, str):
                    self._console.print(item, end="", markup=False, highlight=False)
                else:
                    response = item
            self._console.print()

            assert response is not None

            phase_messages = response.updated_messages

            if is_first_turn:
                self._state.messages.append(
                    {"role": "user", "content": initial_message}
                )
            elif user_input is not None:
                self._state.messages.append({"role": "user", "content": user_input})

            self._state.messages.append(
                {"role": "assistant", "content": response.assistant_message}
            )
            self._auto_save()
            is_first_turn = False

            if response.action != ReviewAction.PENDING:
                return self._reconstruct_marker_response(response)

            # Collect user input
            if response.choices:
                user_input = await self._interactive_select_from_core_choices(
                    response.choices
                )
            else:
                user_input = await self._get_user_input()

            if user_input.lower() in ("quit", "/quit", "exit", "/exit"):
                raise KeyboardInterrupt("User requested exit")

    @staticmethod
    def _reconstruct_marker_response(response: Any) -> str:
        """Reconstruct raw response with markers for session.py parsing.

        Args:
            response: ReviewResponse from the core function.

        Returns:
            Response string with action marker appended.
        """
        from crux_evolve.consultant.core import ReviewAction

        marker_map = {
            ReviewAction.CONFIRMED: "[CONFIRMED]",
            ReviewAction.MODIFY_EVALUATOR: "[MODIFY_EVALUATOR]",
            ReviewAction.REGENERATE: "[REGENERATE]",
        }
        marker = marker_map.get(response.action, "")
        if response.action == ReviewAction.MODIFY_EVALUATOR and response.modification_text:
            return f"{response.assistant_message}\n{marker}\n{response.modification_text}"
        return f"{response.assistant_message}\n{marker}"

    async def _chat_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> tuple[str, str | None]:
        """Send a chat request with streaming output.

        Args:
            system_prompt: System prompt for this conversation.
            messages: List of {role, content} message dicts.
                For assistant messages, may include 'reasoning_content' key.

        Returns:
            Tuple of (complete assistant response text, reasoning_content or None).
        """
        chat_messages = [ChatMessage(role="system", content=system_prompt)]
        for msg in messages:
            chat_messages.append(ChatMessage(
                role=msg["role"],
                content=msg["content"],
                reasoning_content=msg.get("reasoning_content"),
            ))

        # Start streaming display
        self._console.print()
        self._console.print("[bold green]Consultant >[/bold green] ", end="")

        full_text = ""
        stream = await self._provider.chat_stream(chat_messages)
        async for chunk in stream:
            full_text += chunk
            self._console.print(chunk, end="", markup=False, highlight=False)

        self._console.print()  # Newline after stream completes
        return full_text, stream.reasoning_content

    async def _chat_with_tools(
        self,
        system_prompt: str,
        stage_messages: list[dict[str, str]],
        max_rounds: int = 3,
    ) -> str:
        """Stream text to console with automatic tool execution loop.

        Uses streaming chat with tool definitions. After each streaming round,
        checks for tool calls. If any, executes them and loops with results.

        Args:
            system_prompt: System prompt for this conversation.
            stage_messages: List of {role, content} message dicts.
            max_rounds: Maximum tool execution rounds.

        Returns:
            Final assistant response text.
        """
        tools = [READ_FILE_TOOL, LIST_DIRECTORY_TOOL]
        chat_messages = [ChatMessage(role="system", content=system_prompt)]
        for msg in stage_messages:
            chat_messages.append(ChatMessage(role=msg["role"], content=msg["content"]))

        full_text = ""
        for _ in range(max_rounds):
            # Stream text to console
            self._console.print()
            self._console.print("[bold green]Consultant >[/bold green] ", end="")

            stream = await self._provider.chat_stream(chat_messages, tools=tools)
            full_text = ""
            async for chunk in stream:
                full_text += chunk
                self._console.print(chunk, end="", markup=False, highlight=False)
            self._console.print()

            # Check for tool calls after stream completes
            if not stream.tool_calls:
                return full_text

            # Execute tools and loop
            chat_messages.append(ChatMessage(
                role="assistant",
                content=full_text,
                tool_calls=stream.tool_calls,
                reasoning_content=stream.reasoning_content,
            ))
            for tc in stream.tool_calls:
                path = tc.arguments.get("path", "")
                if tc.name == "list_directory":
                    self._console.print(f"[dim]  Listing {path}...[/dim]")
                    tool_result = self._execute_list_directory(tc)
                else:
                    self._console.print(f"[dim]  Reading {path}...[/dim]")
                    tool_result = self._execute_read_file(tc)
                chat_messages.append(ChatMessage(
                    role="tool",
                    content=tool_result,
                    tool_call_id=tc.id,
                ))

        return full_text

    @staticmethod
    def _execute_read_file(tool_call: ToolCall) -> str:
        """Execute a read_file tool call.

        Args:
            tool_call: The tool call to execute.

        Returns:
            File contents or error message.
        """
        path_str = tool_call.arguments.get("path", "")
        resolved = Path(path_str).expanduser().resolve()

        if resolved.is_dir():
            return (
                f"Error: '{path_str}' is a directory, not a file. "
                "Use the list_directory tool instead."
            )
        if not resolved.is_file():
            return f"Error: File not found: {path_str}"

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"Error reading file: {e}"

        lines = content.splitlines()
        if len(lines) > _MAX_FILE_LINES:
            content = (
                "\n".join(lines[:_MAX_FILE_LINES])
                + f"\n\n... (truncated, {len(lines)} total lines)"
            )
        return content

    @staticmethod
    def _execute_list_directory(tool_call: ToolCall) -> str:
        """Execute a list_directory tool call.

        Args:
            tool_call: The tool call to execute.

        Returns:
            Directory tree with key file contents, or error message.
        """
        from crux_evolve.consultant.core import default_directory_reader

        path_str = tool_call.arguments.get("path", "")
        return default_directory_reader(path_str)

    def _auto_save(self) -> None:
        """Persist conversation state to disk after each exchange."""
        with contextlib.suppress(OSError):
            self._state.save()

    async def _get_user_input(self) -> str:
        """Read user input from the terminal.

        Uses prompt_toolkit for cross-platform line editing, history recall
        (up/down arrows), and colored prompt.

        Returns:
            User's input string.
        """
        try:
            self._console.print()
            return await self._prompt_session.prompt_async(
                HTML("<b><cyan>You &gt;</cyan></b> ")
            )
        except EOFError:
            raise

    async def _get_user_input_for_response(self, response: str) -> str:
        """Get user input, using interactive selection if choices are detected.

        Parses the LLM response for numbered choice blocks. If found,
        presents an InquirerPy interactive selector instead of a raw text
        prompt. Falls back to normal text input on any failure.

        Args:
            response: The last LLM response text.

        Returns:
            User's selection or typed input.
        """
        choices = parse_choices(response)
        if choices and len(choices) >= 2:
            try:
                return await self._interactive_select(choices)
            except (ImportError, OSError):
                pass  # InquirerPy not installed or terminal issue
        return await self._get_user_input()

    async def _interactive_select(self, choices: list[ParsedChoice]) -> str:
        """Present an InquirerPy interactive selector for parsed choices.

        Always includes a custom-input option at the end so the user
        can type their own answer when none of the choices fit.

        Args:
            choices: Parsed choices from the LLM response.

        Returns:
            The selected label, or custom text from the user.
        """
        from InquirerPy import inquirer
        from InquirerPy.base.control import Choice

        iq_choices: list[Choice] = []
        default_idx: int | None = None
        has_custom = any(c.is_custom for c in choices)

        for i, c in enumerate(choices):
            iq_choices.append(Choice(value=i, name=c.full_text))
            if c.is_recommended:
                default_idx = i

        custom_idx = len(choices)
        if not has_custom:
            is_chinese = self._detect_chinese(choices)
            custom_label = "自行输入" if is_chinese else "Other — enter your own"
            iq_choices.append(Choice(value=custom_idx, name=custom_label))

        self._console.print()

        result: Any = await inquirer.select(  # type: ignore[func-returns-value]
            message="",
            choices=iq_choices,
            default=default_idx,
            pointer=">",
            qmark="",
            amark="",
            instruction="(arrow keys to move, Enter to select)",
        ).execute_async()

        selected_idx = int(result)

        if selected_idx == custom_idx or (
            selected_idx < len(choices) and choices[selected_idx].is_custom
        ):
            return await self._get_user_input()

        return choices[selected_idx].label

    async def _interactive_select_from_core_choices(
        self, choices: list[Any],
    ) -> str:
        """Present an InquirerPy interactive selector for core Choice objects.

        Args:
            choices: List of core.Choice dataclass instances.

        Returns:
            The selected label, or custom text from the user.
        """
        from InquirerPy import inquirer
        from InquirerPy.base.control import Choice as IQChoice

        iq_choices: list[IQChoice] = []
        default_idx: int | None = None
        has_custom = any(c.is_custom for c in choices)

        for i, c in enumerate(choices):
            iq_choices.append(IQChoice(value=i, name=c.full_text))
            if c.is_recommended:
                default_idx = i

        custom_idx = len(choices)
        if not has_custom:
            text = " ".join(c.full_text for c in choices)
            is_chinese = any("一" <= ch <= "鿿" for ch in text)
            custom_label = "自行输入" if is_chinese else "Other — enter your own"
            iq_choices.append(IQChoice(value=custom_idx, name=custom_label))

        self._console.print()

        result: Any = await inquirer.select(  # type: ignore[func-returns-value]
            message="",
            choices=iq_choices,
            default=default_idx,
            pointer=">",
            qmark="",
            amark="",
            instruction="(arrow keys to move, Enter to select)",
        ).execute_async()

        selected_idx = int(result)

        if selected_idx == custom_idx or (
            selected_idx < len(choices) and choices[selected_idx].is_custom
        ):
            return await self._get_user_input()

        label: str = choices[selected_idx].label
        return label

    @staticmethod
    def _detect_chinese(choices: list[ParsedChoice]) -> bool:
        """Detect if the choices are in Chinese based on character content."""
        text = " ".join(c.full_text for c in choices)
        return any("一" <= ch <= "鿿" for ch in text)

    @staticmethod
    def _has_action_marker(response: str) -> bool:
        """Check if the response contains any action marker.

        Args:
            response: LLM response text.

        Returns:
            True if any action marker is present.
        """
        markers = (
            _NEEDS_COMPLETE_MARKER,
            _CONFIRMED_MARKER,
            _MODIFY_EVALUATOR_MARKER,
            _MODIFY_CONFIG_MARKER,
            _REGENERATE_MARKER,
            _STAGE_COMPLETE_MARKER,
        )
        return any(m in response for m in markers)

    @staticmethod
    def _strip_markers(response: str) -> str:
        """Remove all known markers from display text.

        Args:
            response: LLM response text.

        Returns:
            Text with markers removed.
        """
        markers = (
            _NEEDS_COMPLETE_MARKER,
            _CONFIRMED_MARKER,
            _MODIFY_EVALUATOR_MARKER,
            _MODIFY_CONFIG_MARKER,
            _REGENERATE_MARKER,
            _STAGE_COMPLETE_MARKER,
        )
        result = response
        for marker in markers:
            result = result.replace(marker, "")
        result = _OPTIONS_BLOCK_RE.sub("", result)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()
