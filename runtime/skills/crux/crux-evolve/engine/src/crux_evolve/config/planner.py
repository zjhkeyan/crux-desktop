"""Planner configuration schemas.

Defines configuration classes for the planner layer including
sampler setup and build verification.
"""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from crux_evolve.config.ui import ui


class SamplerConfig(BaseModel):
    """Configuration for a single sampler."""

    name: str = Field(
        ..., description="Registered sampler name",
        json_schema_extra=ui(
            label_zh="采样器名称", label_en="Sampler Name",
            desc_zh="已注册的采样器名称，用于选择具体的采样策略",
            desc_en="Registered sampler name that selects a sampling strategy",
        ),
    )
    config: dict[str, Any] = Field(
        default_factory=dict, description="Sampler-specific config",
        json_schema_extra=ui(
            label_zh="采样器配置", label_en="Sampler Config",
            desc_zh="该采样器的自定义参数，不同采样器支持不同的配置项",
            desc_en="Custom parameters; different samplers support different options",
        ),
    )


class BuildConfig(BaseModel):
    """Configuration for algorithm build verification.

    Supports multi-line build scripts executed in the worktree directory.
    The ``script`` field accepts either a single string (used on all platforms)
    or a mapping from platform names (``linux``, ``darwin``, ``windows``) to
    platform-specific scripts.

    Examples:
        Single script for all platforms::

            build:
              script: "make -j4"

        Platform-specific scripts::

            build:
              script:
                linux: |
                  cmake -B build && cmake --build build -j4
                darwin: |
                  cmake -B build && cmake --build build -j4
                windows: |
                  msbuild /p:Configuration=Release
    """

    ALLOWED_PLATFORMS: ClassVar[set[str]] = {"linux", "darwin", "windows"}

    script: str | dict[str, str] = Field(
        ...,
        description=(
            "Build script commands. Either a single string (all platforms) "
            "or a dict mapping platform (linux/darwin/windows) to script."
        ),
        json_schema_extra=ui(
            label_zh="构建脚本", label_en="Build Script",
            desc_zh="构建命令，可以是单个字符串（所有平台通用）或按平台（linux/darwin/windows）映射的字典",
            desc_en="Build commands; a single string (all platforms) or a dict mapping platform to script",
            multiline=True,
        ),
    )
    timeout: float = Field(
        default=60.0, description="Build timeout in seconds",
        json_schema_extra=ui(
            label_zh="构建超时", label_en="Build Timeout",
            desc_zh="构建过程的最大超时时间（秒）", desc_en="Maximum timeout for the build process in seconds",
        ),
    )

    @field_validator("script")
    @classmethod
    def validate_script_keys(cls, v: str | dict[str, str]) -> str | dict[str, str]:
        """Validate that dict keys are valid platform names."""
        if isinstance(v, dict):
            invalid = set(v.keys()) - cls.ALLOWED_PLATFORMS
            if invalid:
                raise ValueError(
                    f"Invalid platform keys: {invalid}. "
                    f"Allowed: {sorted(cls.ALLOWED_PLATFORMS)}"
                )
        return v


class PlannerConfig(BaseModel):
    """Planner configuration with list of samplers."""

    type: str = Field(
        default="llm_evolution", description="Planner type (registered name)",
        json_schema_extra=ui(
            hidden=True,
            label_zh="规划器类型", label_en="Planner Type",
            desc_zh="规划器的注册名称，决定使用哪种规划策略",
            desc_en="Registered planner name that determines the planning strategy",
        ),
    )
    provider: str = Field(
        default="default",
        description="Name of the LLM provider to use for planning",
        json_schema_extra=ui(
            hidden=True,
            label_zh="LLM 提供者", label_en="Provider",
            desc_zh="用于算法规划阶段的 LLM 提供者名称，需在 providers 列表中预先配置",
            desc_en="Name of the LLM provider for the planning phase; must be defined in the providers list",
        ),
    )
    samplers: list[SamplerConfig] = Field(
        default_factory=list, description="List of samplers to use",
        json_schema_extra=ui(
            label_zh="采样器列表", label_en="Samplers",
            desc_zh="配置一个或多个采样器，用于生成算法变异和交叉方案",
            desc_en="Configure samplers for generating mutation and crossover plans",
        ),
    )
    selection_strategy: Literal["random", "weighted", "tournament", "roulette"] = Field(
        default="weighted", description="Selection strategy for choosing samplers",
        json_schema_extra=ui(
            label_zh="采样器选择策略", label_en="Selection Strategy",
            desc_zh="从多个采样器中选择的策略：random（随机）、weighted（加权）、tournament（锦标赛）、roulette（轮盘赌）",
            desc_en="Strategy for choosing among samplers: random, weighted, tournament, or roulette",
        ),
    )
    parent_selection_strategy: Literal["tournament", "roulette", "rank", "random"] = Field(
        default="tournament", description="Strategy for selecting parents for reproduction",
        json_schema_extra=ui(
            label_zh="父代选择策略", label_en="Parent Selection Strategy",
            desc_zh="选择父代个体进行繁殖的策略：tournament（锦标赛）、roulette（轮盘赌）、rank（排名）、random（随机）",
            desc_en="Strategy for selecting parents: tournament, roulette, rank, or random",
        ),
    )
    build: BuildConfig | None = Field(
        default=None, description="Optional build configuration for algorithm verification",
        json_schema_extra=ui(
            label_zh="构建配置", label_en="Build Config",
            desc_zh="可选的构建配置，用于在评估前编译和验证生成的算法代码",
            desc_en="Optional build config for compiling generated code before evaluation",
        ),
    )
    mask_evolve_blocks: bool = Field(
        default=False,
        description=(
            "If True, replace EVOLVE block bodies with a placeholder in the "
            "project context sent to the coder, forcing novel generation. "
            "If False (default), the coder can see the existing code and "
            "iterate on it, which generally yields higher-quality mutations."
        ),
        json_schema_extra=ui(
            label_zh="遮蔽进化代码块", label_en="Mask Evolve Blocks",
            desc_zh="启用后将 EVOLVE 代码块替换为占位符，迫使 LLM 生成全新代码；关闭则允许基于现有代码迭代改进",
            desc_en="Replaces EVOLVE block bodies with placeholders to force novel generation; "
            "when disabled, the LLM can iterate on existing code",
        ),
    )
