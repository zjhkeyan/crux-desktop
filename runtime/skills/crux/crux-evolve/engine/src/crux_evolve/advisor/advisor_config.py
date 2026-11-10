"""Configuration schema and template for the evolve-block advisor.

Mirrors the shape of :mod:`crux_evolve.builder.builder_config` so frontends
and scripts can treat advisor configs analogously to builder configs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AdvisorLLMConfig:
    """LLM credentials for the advisor.

    Separate from any other LLM configuration in CruxEvolve so the advisor
    can run on a different (often cheaper) model than the builder or
    the main pipeline.
    """

    type: str = "openai_compatible"
    """Provider type: openai, anthropic, or openai_compatible."""

    api_key: str = ""
    """API key for the advisor's LLM."""

    base_url: str | None = None
    """Base URL for OpenAI-compatible providers."""

    model: str = "gpt-4o"
    """Model name."""


@dataclass
class AdviseTaskConfig:
    """Specification of what to analyze.

    Attributes:
        goal: The user's stated algorithm-evolution goal.
        repo_path: Optional repository root (used with ``file_path``
            and ``line_range``, or alone when the repo has exactly
            one EVOLVE-marked block).
        file_path: Relative or absolute path of the file containing
            the selected block.
        line_range: 1-based ``(start, end)`` inclusive line numbers.
        code: Raw snippet, used only when ``repo_path`` is not given.
    """

    goal: str = ""
    repo_path: str | None = None
    file_path: str | None = None
    line_range: tuple[int, int] | None = None
    code: str | None = None


@dataclass
class AdvisorConfig:
    """Complete advisor configuration loaded from YAML."""

    advisor: AdvisorLLMConfig = field(default_factory=AdvisorLLMConfig)
    task: AdviseTaskConfig = field(default_factory=AdviseTaskConfig)


ADVISOR_CONFIG_TEMPLATE = """\
# ============================================================
# CruxEvolve Evolve-Block Advisor Configuration
# ============================================================
# Fill in the sections below, then run:
#   crux_evolve advise --config this_file.yaml
#
# The advisor analyzes a user-selected code block against a stated
# algorithm-evolution goal and returns feasibility, significance,
# concerns, and suggestions as JSON.
#
# You can use ${{ENV_VAR}} syntax to reference environment variables
# instead of writing credentials directly in this file.
# ============================================================

# --- Advisor LLM Configuration ---
advisor:
  type: "openai_compatible"           # openai | anthropic | openai_compatible
  api_key: "${{CRUX_EVOLVE_ADVISE_API_KEY}}"  # Your API key (or ${{ENV_VAR}})
  base_url: "${{CRUX_EVOLVE_ADVISE_BASE_URL}}"  # e.g. https://api.openai.com/v1
  model: "gpt-4o"                     # Model to use for advice

# --- Task Specification ---
task:
  goal: |
{goal_block}
  # Point at a repo and (optionally) narrow to a specific block.
  # If repo_path is given without file_path and line_range, the advisor
  # expects exactly one EVOLVE-marked block in the repo.
  # repo_path: "./my_solver/"
  # file_path: "src/algo.py"
  # line_range: [42, 87]            # 1-based inclusive
  #
  # Or, provide a standalone snippet instead:
  # code: |
  #   def solve(data):
  #       ...
"""


def generate_advisor_config(
    output_path: str | Path,
    *,
    goal: str = "",
) -> Path:
    """Generate an advisor-config YAML template for the user to fill in.

    Args:
        output_path: Path where the YAML file will be written.
        goal: Optional pre-filled evolution goal.

    Returns:
        Path to the written file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if goal.strip():
        lines = goal.strip().splitlines()
        goal_block = "\n".join(f"    {line}" for line in lines)
    else:
        goal_block = (
            "    Describe your evolution goal here.\n"
            "    For example: Minimize the number of comparisons made\n"
            "    by the sorting algorithm on random inputs."
        )

    content = ADVISOR_CONFIG_TEMPLATE.format(goal_block=goal_block)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def load_advisor_config(config_path: str | Path) -> AdvisorConfig:
    """Load and validate an advisor-config YAML file.

    Supports ``${ENV_VAR}`` expansion in all string fields.

    Args:
        config_path: Path to the advisor-config YAML file.

    Returns:
        A populated :class:`AdvisorConfig` instance.

    Raises:
        AdvisorError: If the file is missing, unparseable, or has
            invalid fields.
    """
    from crux_evolve.advisor.pipeline import AdvisorError
    from crux_evolve.config.settings import load_yaml_with_env_expansion

    config_path = Path(config_path)
    if not config_path.exists():
        raise AdvisorError(f"Advisor config file not found: {config_path}")

    try:
        data: dict[str, Any] = load_yaml_with_env_expansion(config_path)
    except KeyError as e:
        raise AdvisorError(
            f"Environment variable expansion failed in {config_path}: {e}"
        ) from e
    except Exception as e:
        raise AdvisorError(
            f"Failed to parse advisor config {config_path}: {e}"
        ) from e

    advisor_data = data.get("advisor", {})
    task_data = data.get("task", {})

    advisor_llm = AdvisorLLMConfig(
        type=advisor_data.get("type", "openai_compatible"),
        api_key=advisor_data.get("api_key", ""),
        base_url=advisor_data.get("base_url"),
        model=advisor_data.get("model", "gpt-4o"),
    )

    line_range_raw = task_data.get("line_range")
    line_range: tuple[int, int] | None = None
    if line_range_raw is not None:
        try:
            start, end = line_range_raw
            line_range = (int(start), int(end))
        except (ValueError, TypeError) as e:
            raise AdvisorError(
                f"task.line_range must be a [start, end] pair, got: "
                f"{line_range_raw!r}"
            ) from e

    task_cfg = AdviseTaskConfig(
        goal=task_data.get("goal", ""),
        repo_path=task_data.get("repo_path"),
        file_path=task_data.get("file_path"),
        line_range=line_range,
        code=task_data.get("code"),
    )

    if not advisor_llm.api_key:
        raise AdvisorError(
            "No API key provided in advisor config.\n"
            "Set advisor.api_key in the YAML file, or use ${ENV_VAR} syntax."
        )

    if not task_cfg.goal.strip():
        raise AdvisorError(
            "No goal provided in advisor config.\n"
            "Set task.goal in the YAML file."
        )

    return AdvisorConfig(advisor=advisor_llm, task=task_cfg)
