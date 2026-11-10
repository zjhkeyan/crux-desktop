"""Stateless core logic for needs gathering conversation.

Provides a turn-based function that both CLI and web frontends can call.
The function takes context + user input, calls the LLM, and returns a
structured response describing what to show the user.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from crux_evolve.consultant.context_limiter import (
    ContextLimits,
    estimate_tokens,
    trim_messages,
)
from crux_evolve.consultant.prompts import (
    _build_language_instruction,
    build_extraction_prompt,
    build_language_reminder,
    build_needs_gathering_prompt,
)
from crux_evolve.infra.provider.base import (
    BaseProvider,
    ChatMessage,
    ToolDefinition,
)

_NEEDS_COMPLETE_MARKER = "[NEEDS_COMPLETE]"
_MAX_FILE_LINES = 500

_OPTIONS_BLOCK_RE = re.compile(
    r"\[OPTIONS_START\].*?\[OPTIONS_END\]",
    re.DOTALL | re.IGNORECASE,
)

READ_FILE_TOOL = ToolDefinition(
    name="read_file",
    description=(
        "Read the contents of a file. Use when the user mentions a file path "
        "or you need to inspect a file to understand their code or data."
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

FileReader = Callable[[str], str]
DirectoryReader = Callable[[str], str]


def detect_language(text: str) -> str:
    """Detect language from text based on Chinese character ratio.

    Args:
        text: Input text to analyze.

    Returns:
        'zh' for Chinese, 'en' for English.
    """
    if not text.strip():
        return "en"
    chinese_chars = sum(1 for ch in text if "一" <= ch <= "鿿")
    return "zh" if chinese_chars > len(text) * 0.1 else "en"


class ResponseType(str, Enum):
    """Type of response from the needs gathering core."""

    MESSAGE = "message"
    CHOICES = "choices"
    COMPLETE = "complete"


@dataclass
class Choice:
    """A single selectable option parsed from LLM output."""

    number: int
    label: str
    description: str
    full_text: str
    is_custom: bool = False
    is_recommended: bool = False
    ask_for_path: bool = False
    ask_for_dir: bool = False

@dataclass
class NeedsGatheringContext:
    """Input context for a single turn of needs gathering.

    The caller (CLI or web) maintains this across turns.
    """

    phase_messages: list[dict[str, str]] = field(default_factory=list)
    """Conversation history for this phase: [{role, content}, ...]."""

    user_context: str | None = None
    """Context from prior file reads or context-gathering phase."""

    user_input: str | None = None
    """The user's latest input. None for the initial kickoff turn."""

    language: str | None = None
    """Detected conversation language ('zh', 'en', etc.). Passed to system prompt."""

    context_limits: ContextLimits | None = None
    """Optional context window limits. When set, trims older messages."""


@dataclass
class NeedsGatheringResponse:
    """Structured response from a single turn of needs gathering.

    The caller inspects response_type to decide how to render and
    what input to collect next.
    """

    response_type: ResponseType
    """What kind of response this is."""

    assistant_message: str
    """The text to display to the user (markers stripped)."""

    choices: list[Choice] | None = None
    """Present when response_type == CHOICES."""

    needs_profile: dict[str, Any] | None = None
    """Present when response_type == COMPLETE."""

    tool_calls_executed: list[dict[str, str]] = field(default_factory=list)
    """Informational: [{tool_name, path}] for tools that ran this turn."""

    updated_messages: list[dict[str, str]] = field(default_factory=list)
    """Full updated message history after this turn."""

def default_file_reader(path: str) -> str:
    """Default file reader that reads from the local filesystem.

    Args:
        path: File path (relative or absolute).

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


_SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".venv", "venv",
    "build", "dist", ".idea", ".vscode", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "egg-info",
}

_KEY_FILE_PATTERNS = {
    "README", "README.md", "README.rst", "readme.md",
    "__init__.py", "main.py", "app.py",
    "config.yaml", "config.yml", "pyproject.toml",
    "setup.py", "setup.cfg", "Makefile", "Cargo.toml",
    "package.json", "requirements.txt",
}

_MAX_DIR_OUTPUT = 8000
_MAX_KEY_FILE_LINES = 100
_MAX_TREE_DEPTH = 3


def default_directory_reader(path: str) -> str:
    """Read a directory tree and auto-read key files.

    Args:
        path: Directory path (relative or absolute).

    Returns:
        Tree structure string with key file contents, or error message.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        if resolved.is_file():
            return (
                f"Error: '{path}' is a file, not a directory. "
                "Use the read_file tool instead."
            )
        return f"Error: Directory not found: {path}"

    tree_lines: list[str] = [f"{resolved.name}/"]
    key_files: list[Path] = []

    def _walk(directory: Path, prefix: str, depth: int) -> None:
        if depth > _MAX_TREE_DEPTH:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            tree_lines.append(f"{prefix}[permission denied]")
            return

        dirs = [e for e in entries if e.is_dir() and not e.name.startswith(".")
                and e.name not in _SKIP_DIRS
                and not e.name.endswith(".egg-info")]
        files = [e for e in entries if e.is_file() and not e.name.startswith(".")]

        items = dirs + files
        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            tree_lines.append(f"{prefix}{connector}{item.name}")

            if item.is_dir():
                extension = "    " if is_last else "│   "
                _walk(item, prefix + extension, depth + 1)
            elif item.is_file() and depth == 0 and item.name in _KEY_FILE_PATTERNS:
                key_files.append(item)

    _walk(resolved, "", 0)

    output = "## Directory Structure\n```\n"
    output += "\n".join(tree_lines)
    output += "\n```\n"

    if key_files:
        output += "\n## Key Files\n"
        for kf in key_files:
            if len(output) >= _MAX_DIR_OUTPUT:
                output += "\n... (output truncated)\n"
                break
            try:
                content = kf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = content.splitlines()
            if len(lines) > _MAX_KEY_FILE_LINES:
                content = (
                    "\n".join(lines[:_MAX_KEY_FILE_LINES])
                    + f"\n... (truncated, {len(lines)} total lines)"
                )
            output += f"\n### {kf.name}\n```\n{content}\n```\n"

    if len(output) > _MAX_DIR_OUTPUT:
        output = output[:_MAX_DIR_OUTPUT] + "\n... (output truncated)\n"

    return output


def _strip_markers(response: str) -> str:
    """Remove completion markers and options block from display text."""
    result = response.replace(_NEEDS_COMPLETE_MARKER, "")
    result = _OPTIONS_BLOCK_RE.sub("", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


async def process_needs_gathering_turn(
    ctx: NeedsGatheringContext,
    provider: BaseProvider,
    file_reader: FileReader | None = None,
    directory_reader: DirectoryReader | None = None,
    max_tool_rounds: int = 3,
) -> NeedsGatheringResponse:
    """Process one turn of the needs gathering conversation.

    This function is stateless: it takes the full context, calls the LLM,
    and returns a structured response. The caller owns all I/O and state
    persistence.

    Args:
        ctx: Current conversation context and user input.
        provider: LLM provider for making API calls.
        file_reader: Callable to read files. Defaults to local filesystem.
        directory_reader: Callable to read directories. Defaults to local filesystem.
        max_tool_rounds: Maximum tool execution rounds per turn.

    Returns:
        Structured response indicating what to show the user.
    """
    if file_reader is None:
        file_reader = default_file_reader
    if directory_reader is None:
        directory_reader = default_directory_reader

    system_prompt = build_needs_gathering_prompt(ctx.user_context, language=ctx.language)
    phase_messages = list(ctx.phase_messages)

    if ctx.user_input is None:
        kickoff = "I'd like to set up an algorithm design pipeline."
        phase_messages.append({"role": "user", "content": kickoff})
    else:
        phase_messages.append({"role": "user", "content": ctx.user_input})

    response_text, tool_calls_info = await _chat_with_tools(
        provider=provider,
        system_prompt=system_prompt,
        messages=phase_messages,
        file_reader=file_reader,
        directory_reader=directory_reader,
        max_rounds=max_tool_rounds,
        context_limits=ctx.context_limits,
    )

    clean_text = _strip_markers(response_text)
    phase_messages.append({"role": "assistant", "content": response_text})

    is_complete = _NEEDS_COMPLETE_MARKER in response_text

    if is_complete:
        needs_profile = await extract_needs_profile(phase_messages, provider)
        return NeedsGatheringResponse(
            response_type=ResponseType.COMPLETE,
            assistant_message=clean_text,
            needs_profile=needs_profile,
            tool_calls_executed=tool_calls_info,
            updated_messages=phase_messages,
        )

    from crux_evolve.consultant.advisor import parse_choices

    parsed_choices = parse_choices(response_text)
    choices: list[Choice] | None = None
    response_type = ResponseType.MESSAGE

    if parsed_choices and len(parsed_choices) >= 2:
        response_type = ResponseType.CHOICES
        choices = [
            Choice(
                number=c.number,
                label=c.label,
                description=c.description,
                full_text=c.full_text,
                is_custom=c.is_custom,
                is_recommended=c.is_recommended,
                ask_for_path=c.ask_for_path,
                ask_for_dir=c.ask_for_dir,
            )
            for c in parsed_choices
        ]

    return NeedsGatheringResponse(
        response_type=response_type,
        assistant_message=clean_text,
        choices=choices,
        tool_calls_executed=tool_calls_info,
        updated_messages=phase_messages,
    )


def _inject_language_reminder(
    chat_messages: list[ChatMessage], language: str | None
) -> None:
    """Fold a language reminder into the most recent user message, in place.

    The language requirement lives in the system prompt, but models sometimes
    mirror the language the user just wrote in. Appending the reminder to the
    latest user turn gives the directive maximum recency right before
    generation. ``chat_messages`` is the LLM-only list (separate from the
    persisted ``phase_messages``), so this does not pollute conversation history,
    and editing the existing user message keeps role alternation valid.

    Args:
        chat_messages: Messages about to be sent to the provider.
        language: Target language code, or None to skip.
    """
    reminder = build_language_reminder(language)
    if not reminder:
        return
    for i in range(len(chat_messages) - 1, -1, -1):
        msg = chat_messages[i]
        if msg.role == "user" and isinstance(msg.content, str):
            chat_messages[i] = ChatMessage(
                role="user",
                content=msg.content + reminder,
            )
            return


async def process_needs_gathering_turn_stream(
    ctx: NeedsGatheringContext,
    provider: BaseProvider,
    file_reader: FileReader | None = None,
    directory_reader: DirectoryReader | None = None,
    max_tool_rounds: int = 3,
) -> AsyncIterator[str | NeedsGatheringResponse]:
    """Streaming variant of process_needs_gathering_turn.

    Yields text chunks as they arrive from the LLM, then yields a final
    NeedsGatheringResponse with the complete structured result.

    Args:
        ctx: Current conversation context and user input.
        provider: LLM provider for making API calls.
        file_reader: Callable to read files. Defaults to local filesystem.
        directory_reader: Callable to read directories. Defaults to local filesystem.
        max_tool_rounds: Maximum tool execution rounds per turn.

    Yields:
        str chunks during streaming, then a final NeedsGatheringResponse.
    """
    if file_reader is None:
        file_reader = default_file_reader
    if directory_reader is None:
        directory_reader = default_directory_reader

    system_prompt = build_needs_gathering_prompt(ctx.user_context, language=ctx.language)
    phase_messages = list(ctx.phase_messages)

    if ctx.user_input is None:
        kickoff = "I'd like to set up an algorithm design pipeline."
        phase_messages.append({"role": "user", "content": kickoff})
    else:
        phase_messages.append({"role": "user", "content": ctx.user_input})

    tool_calls_info: list[dict[str, str]] = []
    tools = [READ_FILE_TOOL, LIST_DIRECTORY_TOOL]

    messages_for_llm = phase_messages
    if ctx.context_limits is not None:
        sys_tokens = estimate_tokens(system_prompt)
        messages_for_llm = trim_messages(phase_messages, sys_tokens, ctx.context_limits)

    chat_messages = [ChatMessage(role="system", content=system_prompt)]
    for msg in messages_for_llm:
        chat_messages.append(ChatMessage(role=msg["role"], content=msg["content"]))
    _inject_language_reminder(chat_messages, ctx.language)

    full_text = ""
    for _ in range(max_tool_rounds):
        stream = await provider.chat_stream(chat_messages, tools=tools)
        full_text = ""
        async for chunk in stream:
            full_text += chunk
            yield chunk

        if not stream.tool_calls:
            break

        chat_messages.append(ChatMessage(
            role="assistant",
            content=full_text,
            tool_calls=stream.tool_calls,
        ))
        for tc in stream.tool_calls:
            path = tc.arguments.get("path", "")
            tool_result = (
                directory_reader(path) if tc.name == "list_directory"
                else file_reader(path)
            )
            tool_calls_info.append({"tool_name": tc.name, "path": path})
            chat_messages.append(ChatMessage(
                role="tool",
                content=tool_result,
                tool_call_id=tc.id,
            ))
        full_text = ""

    response_text = full_text
    clean_text = _strip_markers(response_text)
    phase_messages.append({"role": "assistant", "content": response_text})

    is_complete = _NEEDS_COMPLETE_MARKER in response_text

    if is_complete:
        needs_profile = await extract_needs_profile(phase_messages, provider)
        yield NeedsGatheringResponse(
            response_type=ResponseType.COMPLETE,
            assistant_message=clean_text,
            needs_profile=needs_profile,
            tool_calls_executed=tool_calls_info,
            updated_messages=phase_messages,
        )
        return

    from crux_evolve.consultant.advisor import parse_choices

    parsed_choices = parse_choices(response_text)
    choices: list[Choice] | None = None
    response_type = ResponseType.MESSAGE

    if parsed_choices and len(parsed_choices) >= 2:
        response_type = ResponseType.CHOICES
        choices = [
            Choice(
                number=c.number,
                label=c.label,
                description=c.description,
                full_text=c.full_text,
                is_custom=c.is_custom,
                is_recommended=c.is_recommended,
                ask_for_path=c.ask_for_path,
                ask_for_dir=c.ask_for_dir,
            )
            for c in parsed_choices
        ]

    yield NeedsGatheringResponse(
        response_type=response_type,
        assistant_message=clean_text,
        choices=choices,
        tool_calls_executed=tool_calls_info,
        updated_messages=phase_messages,
    )


async def extract_needs_profile(
    phase_messages: list[dict[str, str]],
    provider: BaseProvider,
) -> dict[str, Any]:
    """Extract structured NeedsProfile from completed conversation.

    Call this after process_needs_gathering_turn returns COMPLETE.

    Args:
        phase_messages: Full conversation history for the needs phase.
        provider: LLM provider for the extraction call.

    Returns:
        Extracted needs profile as a dict.
    """
    extraction_prompt = build_extraction_prompt(phase_messages)
    result = await provider.generate(extraction_prompt)
    try:
        parsed: dict[str, Any] = json.loads(result.text.strip())
        return parsed
    except json.JSONDecodeError:
        text = result.text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0]
        try:
            parsed = json.loads(text.strip())
            return parsed
        except json.JSONDecodeError:
            return {"description": ""}


async def _chat_with_tools(
    provider: BaseProvider,
    system_prompt: str,
    messages: list[dict[str, str]],
    file_reader: FileReader,
    directory_reader: DirectoryReader | None = None,
    max_rounds: int = 3,
    context_limits: ContextLimits | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Call LLM with tool support, executing tools internally.

    Args:
        provider: LLM provider.
        system_prompt: System prompt.
        messages: Conversation messages.
        file_reader: Callable to read files.
        directory_reader: Callable to read directories.
        max_rounds: Maximum tool execution rounds.
        context_limits: Optional context window limits.

    Returns:
        Tuple of (final response text, list of tool call info dicts).
    """
    if directory_reader is None:
        directory_reader = default_directory_reader

    tools = [READ_FILE_TOOL, LIST_DIRECTORY_TOOL]

    messages_for_llm = messages
    if context_limits is not None:
        sys_tokens = estimate_tokens(system_prompt)
        messages_for_llm = trim_messages(messages, sys_tokens, context_limits)

    chat_messages = [ChatMessage(role="system", content=system_prompt)]
    for msg in messages_for_llm:
        chat_messages.append(ChatMessage(role=msg["role"], content=msg["content"]))

    tool_calls_info: list[dict[str, str]] = []
    full_text = ""

    for _ in range(max_rounds):
        stream = await provider.chat_stream(chat_messages, tools=tools)
        full_text = ""
        async for chunk in stream:
            full_text += chunk

        if not stream.tool_calls:
            return full_text, tool_calls_info

        chat_messages.append(ChatMessage(
            role="assistant",
            content=full_text,
            tool_calls=stream.tool_calls,
        ))
        for tc in stream.tool_calls:
            path = tc.arguments.get("path", "")
            tool_result = (
                directory_reader(path) if tc.name == "list_directory"
                else file_reader(path)
            )
            tool_calls_info.append({"tool_name": tc.name, "path": path})
            chat_messages.append(ChatMessage(
                role="tool",
                content=tool_result,
                tool_call_id=tc.id,
            ))

    return full_text, tool_calls_info


# ---------------------------------------------------------------------------
# Phase 3: Review — stateless core
# ---------------------------------------------------------------------------

_CONFIRMED_MARKER = "[CONFIRMED]"
_MODIFY_EVALUATOR_MARKER = "[MODIFY_EVALUATOR]"
_REGENERATE_MARKER = "[REGENERATE]"

_REVIEW_MARKERS = (
    _CONFIRMED_MARKER,
    _MODIFY_EVALUATOR_MARKER,
    _REGENERATE_MARKER,
)


class ReviewAction(str, Enum):
    """Action determined from the review conversation."""

    CONFIRMED = "confirmed"
    MODIFY_EVALUATOR = "modify_evaluator"
    REGENERATE = "regenerate"
    PENDING = "pending"


@dataclass
class ReviewContext:
    """Input context for a single turn of review conversation.

    The caller (CLI or web) maintains this across turns.
    """

    phase_messages: list[dict[str, str]] = field(default_factory=list)
    """Conversation history for this review session."""

    system_prompt: str = ""
    """System prompt for the review phase."""

    user_input: str | None = None
    """The user's latest input. None for the initial turn."""

    initial_message: str | None = None
    """Initial message to send on the first turn (evaluator explanation prompt)."""

    language: str | None = None
    """Detected conversation language ('zh', 'en', etc.). Appended to system prompt."""

    context_limits: ContextLimits | None = None
    """Optional context window limits. When set, trims older messages."""


@dataclass
class ReviewResponse:
    """Structured response from a single turn of review."""

    action: ReviewAction
    """What action the LLM/user decided on."""

    assistant_message: str
    """The text to display to the user (markers stripped)."""

    choices: list[Choice] | None = None
    """Present when action == PENDING and choices detected."""

    modification_text: str | None = None
    """Present when action == MODIFY_EVALUATOR — the modification description."""

    updated_messages: list[dict[str, str]] = field(default_factory=list)
    """Full updated message history after this turn."""


def _strip_review_markers(response: str) -> str:
    """Remove all review markers and options block from display text."""
    result = response
    for marker in _REVIEW_MARKERS:
        result = result.replace(marker, "")
    result = _OPTIONS_BLOCK_RE.sub("", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _detect_review_action(
    response: str,
) -> tuple[ReviewAction, str | None]:
    """Detect which action marker is present in the response.

    Returns:
        Tuple of (action, modification_text or None).
    """
    if _CONFIRMED_MARKER in response:
        return ReviewAction.CONFIRMED, None
    if _MODIFY_EVALUATOR_MARKER in response:
        parts = response.split(_MODIFY_EVALUATOR_MARKER, 1)
        modification = parts[1].strip() if len(parts) > 1 else None
        return ReviewAction.MODIFY_EVALUATOR, modification or None
    if _REGENERATE_MARKER in response:
        return ReviewAction.REGENERATE, None
    return ReviewAction.PENDING, None


async def process_review_turn(
    ctx: ReviewContext,
    provider: BaseProvider,
) -> ReviewResponse:
    """Process one turn of the review conversation.

    Stateless: takes context, calls LLM, returns structured response.
    No tool calls needed for review (pure conversation).

    Args:
        ctx: Current review context and user input.
        provider: LLM provider for making API calls.

    Returns:
        Structured response with action and display text.
    """
    phase_messages = list(ctx.phase_messages)

    if ctx.user_input is None and ctx.initial_message is not None:
        phase_messages.append({"role": "user", "content": ctx.initial_message})
    elif ctx.user_input is not None:
        phase_messages.append({"role": "user", "content": ctx.user_input})

    full_system_prompt = ctx.system_prompt + _build_language_instruction(ctx.language)

    messages_for_llm = phase_messages
    if ctx.context_limits is not None:
        sys_tokens = estimate_tokens(full_system_prompt)
        messages_for_llm = trim_messages(phase_messages, sys_tokens, ctx.context_limits)

    chat_messages = [ChatMessage(
        role="system",
        content=full_system_prompt,
    )]
    for msg in messages_for_llm:
        chat_messages.append(ChatMessage(role=msg["role"], content=msg["content"]))
    _inject_language_reminder(chat_messages, ctx.language)

    stream = await provider.chat_stream(chat_messages)
    full_text = ""
    async for chunk in stream:
        full_text += chunk

    clean_text = _strip_review_markers(full_text)
    phase_messages.append({"role": "assistant", "content": full_text})

    action, modification_text = _detect_review_action(full_text)

    choices: list[Choice] | None = None
    if action == ReviewAction.PENDING:
        from crux_evolve.consultant.advisor import parse_choices

        parsed_choices = parse_choices(full_text)
        if parsed_choices and len(parsed_choices) >= 2:
            choices = [
                Choice(
                    number=c.number,
                    label=c.label,
                    description=c.description,
                    full_text=c.full_text,
                    is_custom=c.is_custom,
                    is_recommended=c.is_recommended,
                    ask_for_path=c.ask_for_path,
                    ask_for_dir=c.ask_for_dir,
                )
                for c in parsed_choices
            ]

    return ReviewResponse(
        action=action,
        assistant_message=clean_text,
        choices=choices,
        modification_text=modification_text,
        updated_messages=phase_messages,
    )


async def process_review_turn_stream(
    ctx: ReviewContext,
    provider: BaseProvider,
) -> AsyncIterator[str | ReviewResponse]:
    """Streaming variant of process_review_turn.

    Yields text chunks as they arrive, then a final ReviewResponse.

    Args:
        ctx: Current review context and user input.
        provider: LLM provider for making API calls.

    Yields:
        str chunks during streaming, then a final ReviewResponse.
    """
    phase_messages = list(ctx.phase_messages)

    if ctx.user_input is None and ctx.initial_message is not None:
        phase_messages.append({"role": "user", "content": ctx.initial_message})
    elif ctx.user_input is not None:
        phase_messages.append({"role": "user", "content": ctx.user_input})

    full_system_prompt = ctx.system_prompt + _build_language_instruction(ctx.language)

    messages_for_llm = phase_messages
    if ctx.context_limits is not None:
        sys_tokens = estimate_tokens(full_system_prompt)
        messages_for_llm = trim_messages(phase_messages, sys_tokens, ctx.context_limits)

    chat_messages = [ChatMessage(
        role="system",
        content=full_system_prompt,
    )]
    for msg in messages_for_llm:
        chat_messages.append(ChatMessage(role=msg["role"], content=msg["content"]))
    _inject_language_reminder(chat_messages, ctx.language)

    stream = await provider.chat_stream(chat_messages)
    full_text = ""
    async for chunk in stream:
        full_text += chunk
        yield chunk

    clean_text = _strip_review_markers(full_text)
    phase_messages.append({"role": "assistant", "content": full_text})

    action, modification_text = _detect_review_action(full_text)

    choices: list[Choice] | None = None
    if action == ReviewAction.PENDING:
        from crux_evolve.consultant.advisor import parse_choices

        parsed_choices = parse_choices(full_text)
        if parsed_choices and len(parsed_choices) >= 2:
            choices = [
                Choice(
                    number=c.number,
                    label=c.label,
                    description=c.description,
                    full_text=c.full_text,
                    is_custom=c.is_custom,
                    is_recommended=c.is_recommended,
                    ask_for_path=c.ask_for_path,
                    ask_for_dir=c.ask_for_dir,
                )
                for c in parsed_choices
            ]

    yield ReviewResponse(
        action=action,
        assistant_message=clean_text,
        choices=choices,
        modification_text=modification_text,
        updated_messages=phase_messages,
    )
