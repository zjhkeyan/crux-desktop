"""Context limiting utilities for consultant conversation history.

Provides sliding-window (round count) and token-budget trimming so that
only the most relevant recent messages are sent to the LLM provider.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContextLimits:
    """Configuration for conversation context trimming.

    Attributes:
        max_rounds: Maximum number of user/assistant round pairs to keep.
        max_tokens: Maximum total token budget for conversation messages
            (excluding system prompt).
    """

    max_rounds: int = 20
    max_tokens: int = 100_000


def estimate_tokens(text: str) -> int:
    """Fast local token count approximation (~4 chars per token).

    Args:
        text: Text to estimate token count for.

    Returns:
        Estimated number of tokens.
    """
    return len(text) // 4


def trim_messages(
    messages: list[dict[str, str]],
    system_prompt_tokens: int,
    limits: ContextLimits,
) -> list[dict[str, str]]:
    """Trim conversation messages by applying round and token limits.

    Applies both limits and returns the stricter result (whichever keeps
    fewer messages). Always preserves at least the most recent round.

    Args:
        messages: Conversation messages as [{role, content}, ...].
        system_prompt_tokens: Token count of the system prompt (reserved).
        limits: Round and token budget configuration.

    Returns:
        Trimmed message list (newest messages preserved).
    """
    if len(messages) <= 2:
        return messages

    trailing_user = None
    working = list(messages)
    if working and working[-1]["role"] == "user":
        trailing_user = working.pop()

    rounds: list[list[dict[str, str]]] = []
    i = 0
    while i < len(working):
        if i + 1 < len(working) and working[i]["role"] == "user" and working[i + 1]["role"] == "assistant":
            rounds.append([working[i], working[i + 1]])
            i += 2
        else:
            rounds.append([working[i]])
            i += 1

    round_trimmed = rounds[-limits.max_rounds:] if len(rounds) > limits.max_rounds else rounds

    available_tokens = limits.max_tokens - system_prompt_tokens
    if trailing_user:
        available_tokens -= estimate_tokens(trailing_user["content"])

    token_trimmed: list[list[dict[str, str]]] = []
    accumulated = 0
    for rnd in reversed(rounds):
        rnd_tokens = sum(estimate_tokens(msg["content"]) for msg in rnd)
        if accumulated + rnd_tokens > available_tokens and token_trimmed:
            break
        token_trimmed.append(rnd)
        accumulated += rnd_tokens
    token_trimmed.reverse()

    result_rounds = round_trimmed if len(round_trimmed) <= len(token_trimmed) else token_trimmed

    if not result_rounds and rounds:
        result_rounds = [rounds[-1]]

    result: list[dict[str, str]] = []
    for rnd in result_rounds:
        result.extend(rnd)
    if trailing_user:
        result.append(trailing_user)

    return result
