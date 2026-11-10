"""ClaudeCode coder implementation.

This coder uses the ClaudeCode agent to generate code from algorithm insights.
"""

import os
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from loguru import logger

from crux_evolve.coder.base import BaseCoder, GenerateResult, GenerateStatus
from crux_evolve.config.app import ProviderConfig
from crux_evolve.config.schema import ClaudeCodeConfig
from crux_evolve.infra.timing import ExecutionTiming


@BaseCoder.register("claude_code")
class ClaudeCode(BaseCoder):
    """ClaudeCode coder implementation that uses ClaudeCode for code generation.

    This coder delegates code generation to the ClaudeCode agent which can
    handle incremental code changes and targeted EVOLVE block replacements.
    """
    def __init__(self, config: ClaudeCodeConfig, provider_config: ProviderConfig | None = None) -> None:
        """Initialize the ClaudeCode coder.

        Args:
            config: Configuration for the ClaudeCode coder.
            provider_config: Resolved provider configuration with LLM credentials.
        """
        super().__init__(config)
        self._provider_config = provider_config
        if provider_config:
            if provider_config.api_key:
                os.environ["ANTHROPIC_API_KEY"] = provider_config.api_key
            if provider_config.auth_token:
                os.environ["ANTHROPIC_AUTH_TOKEN"] = provider_config.auth_token
            if provider_config.base_url:
                os.environ["ANTHROPIC_BASE_URL"] = provider_config.base_url
            if provider_config.model:
                os.environ["ANTHROPIC_MODEL"] = provider_config.model
        # Force UTF-8 mode to avoid GBK encoding errors on Windows
        os.environ["PYTHONUTF8"] = "1"

    @property
    def name(self) -> str:
        """Return the name of the coder."""
        return "Claude Code"

    async def generate(
        self,
        prompt: str,
        context: dict[str, Any],
        working_dir: str,
        log_file: Path | None,
        **kwargs,
    ) -> GenerateResult:
        """Generate code from algorithm insight using coding agent.

        The coder writes generated files to the specified working directory.
        We don't return the code itself - we just track success/failure and file locations.

        Args:
            prompt: The prompt for code generation
            context: Additional context containing:
                - task_description: Description of the task
                - constraints: Any constraints on the solution
                - test_cases: Optional test cases
                - parent_code: Code from parent (for mutation)
                - similar_solutions: Similar successful solutions
            working_dir: Directory to write generated code files
            log_file: Optional path to log the generation process (for debugging)
            **kwargs: Additional generation options

        Returns:
            GenerateResult with status and generated file paths
        """
        model_name = self._provider_config.model if self._provider_config else "unknown"
        logger.debug("ClaudeCode coder using model: {}", model_name)
        token_used = 0
        start_time = time.time()

        if log_file:
            with open(log_file, "w", encoding="utf-8") as f:
                token_used = await self._generate_with_log(
                    prompt, working_dir, f, token_used
                )
        else:
            token_used = await self._generate_with_log(prompt, working_dir, None, token_used)

        return GenerateResult(
            status=GenerateStatus.SUCCESS,
            working_dir=working_dir,
            token_used=token_used,
            timing=ExecutionTiming(
                wall_time_ms=(time.time() - start_time) * 1000,
                llm_coding_ms=(time.time() - start_time) * 1000,
            ).recompute_overhead(),
        )

    async def _generate_with_log(
        self,
        prompt: str,
        working_dir: str,
        f: Any,
        token_used: int,
    ) -> int:
        """Helper method to generate code with optional log file."""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=working_dir, permission_mode="bypassPermissions"
            ),
        ):
            # For simplicity, we just print the generated code here.
            # In a real implementation, we would write the code to files in working_dir.
            if isinstance(message, SystemMessage):
                continue
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ThinkingBlock):
                        if self.config.log_to_console:
                            logger.trace(f"Think: {block.thinking}")
                        if f:
                            f.write(f"Think: {block.thinking}\n")
                    elif isinstance(block, TextBlock):
                        if self.config.log_to_console:
                            logger.trace(block.text)
                        if f:
                            f.write(f"{block.text}\n")
                    elif isinstance(block, ToolUseBlock):
                        if self.config.log_to_console:
                            logger.trace(
                                f"<Tool Use>: {block.name} with input {block.input}"
                            )
                        if f:
                            f.write(
                                f"<Tool Use>: {block.name} with input {block.input}\n"
                            )
            elif isinstance(message, UserMessage):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        if self.config.log_to_console:
                            logger.trace(f"<Tool Result>: {block.content}")
                        if f:
                            f.write(f"<Tool Result>: {block.content}\n")
            elif isinstance(message, ResultMessage) and message.usage:
                token_used = message.usage.get("input_tokens", 0) + message.usage.get(
                    "output_tokens", 0
                )
        return token_used
