"""MEoH-specific planner implementation."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

from crux_evolve.coder.base import BaseCoder
from crux_evolve.infra.provider import BaseProvider
from crux_evolve.infra.repo_analyzer import AnalyzedRepository
from crux_evolve.infra.state import StateTracker
from crux_evolve.infra.timing import ExecutionTiming
from crux_evolve.infra.version_control import BaseVersionControl
from crux_evolve.planner.base import Algorithm, BasePlanner
from crux_evolve.planner.llm_evolution import LLMEvolutionPlanner
from crux_evolve.planner.memory import Memory
from crux_evolve.planner.sampler.base import BaseSampler
from crux_evolve.planner.sampler.meoh_e1_sampler import MEoHE1Sampler  # noqa: F401
from crux_evolve.planner.sampler.meoh_e2_sampler import MEoHE2Sampler  # noqa: F401
from crux_evolve.planner.sampler.meoh_init_sampler import MEoHInitSampler  # noqa: F401
from crux_evolve.planner.sampler.meoh_m1_sampler import MEoHM1Sampler  # noqa: F401
from crux_evolve.planner.sampler.meoh_m2_sampler import MEoHM2Sampler  # noqa: F401
from crux_evolve.planner.sampler.meoh_prompt_templates import build_direct_code_prompt


@BasePlanner.register("meoh_evolution")
class MEoHEvolutionPlanner(LLMEvolutionPlanner):
    """Planner with explicit MEoH operator dispatch."""

    OPERATOR_TO_SAMPLER = {
        "i1": "meoh_init_sampler",
        "e1": "meoh_e1_sampler",
        "e2": "meoh_e2_sampler",
        "m1": "meoh_m1_sampler",
        "m2": "meoh_m2_sampler",
    }

    def __init__(
        self,
        provider: BaseProvider,
        coder: BaseCoder,
        memory: Memory,
        config: dict[str, Any],
        analyzed_repository: AnalyzedRepository,
        version_control: BaseVersionControl,
        state_tracker: StateTracker,
    ) -> None:
        """Initialize the MEoH planner."""
        BasePlanner.__init__(
            self,
            provider=provider,
            coder=coder,
            memory=memory,
            config=config,
            analyzed_repository=analyzed_repository,
            version_control=version_control,
            state_tracker=state_tracker,
        )
        self.samplers: list[BaseSampler] = []
        self.sampler_map: dict[str, BaseSampler] = {}
        self._init_meoh_samplers(config, provider, memory, analyzed_repository)

    def _init_meoh_samplers(
        self,
        config: dict[str, Any],
        provider: BaseProvider,
        memory: Memory,
        analyzed_repository: AnalyzedRepository,
    ) -> None:
        for sampler_name in self.OPERATOR_TO_SAMPLER.values():
            sampler = BaseSampler.create(
                sampler_name,
                provider=provider,
                memory=memory,
                config=config,
                analyzed_repository=analyzed_repository,
            )
            self.samplers.append(sampler)
            self.sampler_map[sampler_name] = sampler

    async def init(
        self,
        island_id: str,
        generation_id: int,
        algorithm_id: str,
        **kwargs,
    ):
        """Create a MEoH worktree without island-oriented naming."""
        worktree_name = f"meoh_gen_{generation_id}_ind_{algorithm_id}"
        logger.info(f"Creating worktree for MEoH generation {generation_id} ({worktree_name}) ...")
        version_control_result = self.version_control.create_worktree(name=worktree_name)

        if not version_control_result.success or not version_control_result.data:
            logger.warning(
                "Failed to create worktree for MEoH generation {} ({}): {}",
                generation_id,
                worktree_name,
                version_control_result.message,
            )
            return None

        worktree = version_control_result.data.get("worktree")
        logger.info(
            "Created worktree for MEoH generation {} ({}): {}",
            generation_id,
            worktree_name,
            worktree.path,
        )
        return worktree

    async def plan(self, population: list[Algorithm], generation: int, **kwargs) -> Algorithm:
        """Plan the next MEoH algorithm with an explicit operator."""
        operator = kwargs.get("operator", "i1")
        if operator not in self.OPERATOR_TO_SAMPLER:
            raise ValueError(f"Unsupported MEoH operator: {operator}")

        sampler_name = self.OPERATOR_TO_SAMPLER[operator]
        sampler = self.sampler_map[sampler_name]
        parents = kwargs.get("parents", population)

        start_time = time.time()
        algorithm = await sampler.sample(
            population=parents,
            generation=generation,
            parents=parents,
            background=kwargs.get("background", ""),
        )
        plan_time_ms = (time.time() - start_time) * 1000
        self.state_tracker.record_timing("planner.plan", plan_time_ms)
        if algorithm.timing.llm_planning_ms > 0:
            self.state_tracker.record_timing("provider.chat.planner", algorithm.timing.llm_planning_ms)
        return algorithm

    async def plan_and_implement(self, population: list[Algorithm], generation: int, **kwargs) -> Algorithm:
        """Unified planning + code generation in one LLM call.

        The sampler produces an Algorithm with thought (name/description) and code
        in a single LLM interaction, bypassing the separate Coder stage.
        """
        operator = kwargs.get("operator", "i1")
        if operator not in self.OPERATOR_TO_SAMPLER:
            raise ValueError(f"Unsupported MEoH operator: {operator}")

        sampler_name = self.OPERATOR_TO_SAMPLER[operator]
        sampler = self.sampler_map[sampler_name]
        parents = kwargs.get("parents", population)

        start_time = time.time()
        algorithm = await sampler.sample(
            population=parents,
            generation=generation,
            parents=parents,
            background=kwargs.get("background", ""),
        )
        plan_time_ms = (time.time() - start_time) * 1000
        self.state_tracker.record_timing("planner.plan_and_implement", plan_time_ms)
        if algorithm.timing.llm_planning_ms > 0:
            self.state_tracker.record_timing("provider.chat.planner", algorithm.timing.llm_planning_ms)

        return algorithm

    def _write_unified_code_to_worktree(self, algorithm: Algorithm, code: str) -> None:
        """Write unified-mode code into the worktree's EVOLVE block."""
        if not self.analyzed_repository or not self.analyzed_repository.evolvable_blocks:
            logger.warning(f"No EVOLVE blocks found; cannot write unified code for {algorithm.name}")
            return

        block = self.analyzed_repository.evolvable_blocks[0]
        target_path = Path(algorithm.worktree.path) / block.file_path
        if not target_path.exists():
            logger.warning(f"Target file not found for unified code: {target_path}")
            return

        clean_code = self._strip_code_fence(code)
        clean_code = self._ensure_required_imports(block.original_content, clean_code)
        clean_code = self._ensure_expected_function_names(block, clean_code)
        content = target_path.read_text(encoding="utf-8")
        updated = self._replace_evolve_block(content, clean_code)
        target_path.write_text(updated, encoding="utf-8")
        logger.info(f"Wrote unified code for algorithm {algorithm.name} to {target_path}")

    async def generate_direct_code(self, algorithm: Algorithm, **kwargs) -> Algorithm:
        """Generate EVOLVE block code directly via the planner provider."""
        if algorithm.worktree is None:
            raise ValueError("Algorithm must have a worktree for direct code generation")

        if self.analyzed_repository is None or not self.analyzed_repository.evolvable_blocks:
            raise ValueError("MEoH direct_code requires an analyzed repository with EVOLVE blocks")

        block = self.analyzed_repository.evolvable_blocks[0]
        target_path = Path(algorithm.worktree.path) / block.file_path
        if not target_path.exists():
            raise FileNotFoundError(f"Target file for direct_code not found: {target_path}")

        prompt = build_direct_code_prompt(kwargs.get("task_description", ""), block, algorithm)
        start_time = time.time()
        response = await self.provider.generate(
            prompt,
            temperature=self.config.get("temperature", 0.7),
            max_tokens=self.config.get("max_tokens", 4096),
            request_stage="coder",
        )
        implementation_ms = (time.time() - start_time) * 1000
        self.state_tracker.record_timing("planner.implement", implementation_ms)
        if response.timing.llm_coding_ms > 0:
            self.state_tracker.record_timing("provider.chat.coder", response.timing.llm_coding_ms)

        replacement = self._strip_code_fence(response.text)
        updated_content = self._replace_evolve_block(target_path.read_text(encoding="utf-8"), replacement)
        target_path.write_text(updated_content, encoding="utf-8")

        algorithm.update_timing(response.timing or ExecutionTiming.from_llm_stage("coder", implementation_ms))
        logger.info(f"Algorithm {algorithm.name} direct code generation success via planner provider")
        return algorithm

    @staticmethod
    def _extract_import_lines(code: str) -> list[str]:
        """Extract import statements from code."""
        imports = []
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)
        return imports

    @staticmethod
    def _ensure_required_imports(original_content: str, replacement: str) -> str:
        """Prepend any import lines from the original EVOLVE block that the replacement is missing."""
        original_imports = MEoHEvolutionPlanner._extract_import_lines(original_content)
        if not original_imports:
            return replacement

        replacement_text = replacement.strip()
        missing = [imp for imp in original_imports if imp not in replacement_text]
        if not missing:
            return replacement

        logger.debug(f"Auto-prepending {len(missing)} missing imports to EVOLVE replacement: {missing}")
        return "\n".join(missing) + "\n\n" + replacement

    @staticmethod
    def _ensure_expected_function_names(block, replacement: str) -> str:
        """Append aliases when the LLM renames a function that post-EVOLVE code depends on."""
        if block is None or not block.context_after or not block.original_content:
            return replacement

        original_top_funcs = re.findall(r"^def\s+(\w+)\s*\(", block.original_content, re.MULTILINE)
        if not original_top_funcs:
            return replacement

        expected = {fn for fn in original_top_funcs if fn in block.context_after}
        if not expected:
            return replacement

        replacement_top_funcs = re.findall(r"^def\s+(\w+)\s*\(", replacement, re.MULTILINE)
        replacement_func_set = set(replacement_top_funcs)

        missing = expected - replacement_func_set
        if not missing:
            return replacement

        candidate = replacement_top_funcs[-1] if replacement_top_funcs else None
        if not candidate:
            return replacement

        aliases = [f"{name} = {candidate}" for name in missing]
        logger.debug(f"Auto-aliasing missing function names: {aliases}")
        return replacement.rstrip() + "\n\n" + "\n".join(aliases) + "\n"

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """Remove markdown code fences from model output if present."""
        match = re.search(r"```[\w-]*\n(.*?)\n```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

    @staticmethod
    def _replace_evolve_block(content: str, replacement: str) -> str:
        """Replace the first EVOLVE block in a file."""
        patterns = [
            re.compile(r"(?P<start>#\s*EVOLVE[\s_-]+START.*?\n)(?P<body>.*?)(?P<end>\n#\s*EVOLVE[\s_-]+END)", re.DOTALL),
            re.compile(r"(?P<start>//\s*EVOLVE[\s_-]+START.*?\n)(?P<body>.*?)(?P<end>\n//\s*EVOLVE[\s_-]+END)", re.DOTALL),
        ]
        for pattern in patterns:
            match = pattern.search(content)
            if match:
                replaced = f"{match.group('start')}{replacement}{match.group('end')}"
                return content[:match.start()] + replaced + content[match.end():]
        raise ValueError("Could not find an EVOLVE block to replace in direct_code mode")
