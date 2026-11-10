"""Provider layer for CruxEvolve.

Abstract interfaces and implementations for LLM providers (OpenAI, Anthropic, etc.)
"""

from crux_evolve.infra.provider.anthropic import AnthropicProvider
from crux_evolve.infra.provider.base import (
    BaseProvider,
    ChatMessage,
    ContentPart,
    GenerationResult,
    ProviderType,
    StreamResponse,
    ToolCall,
    ToolDefinition,
)
from crux_evolve.infra.provider.mock import MockProvider
from crux_evolve.infra.provider.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "BaseProvider",
    "GenerationResult",
    "ChatMessage",
    "ContentPart",
    "ProviderType",
    "StreamResponse",
    "ToolCall",
    "ToolDefinition",
    "OpenAICompatibleProvider",
    "AnthropicProvider",
    "MockProvider",
]
