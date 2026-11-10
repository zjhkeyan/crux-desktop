r"""LLM Judge evaluator base class.

Provides a reusable evaluator that executes a generated script, captures its
output, and uses an LLM to judge the quality of that output. Subclasses only
need to define the judge prompt template and metrics.

Typical usage in an example::

    from crux_evolve.evaluator.llm_judge import LLMJudgeEvaluator

    @LLMJudgeEvaluator.register("my_evaluator")
    class MyEvaluator(LLMJudgeEvaluator):
        script_patterns = ["solve.py", "implementation.py"]
        judge_temperature = 0.2

        @property
        def name(self) -> str:
            return "my_evaluator"

        @property
        def metrics(self) -> list[Metric]:
            return [Metric(name="quality", type=MetricType.MAXIMIZE, weight=1.0)]

        def build_judge_prompt(self, data_content: str, script_output: str) -> str:
            return f"Score this output...\n{script_output}"
"""

import json
import os
import subprocess
import sys
import time
from abc import abstractmethod
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from openai import AsyncOpenAI

from crux_evolve.config.schema import EvalContext
from crux_evolve.evaluator.base import BaseEvaluator, EvaluationResult


class LLMJudgeEvaluator(BaseEvaluator):
    """Base evaluator: execute script -> LLM judge -> parse scores.

    Subclasses **must** override:
        - ``name`` property
        - ``metrics`` property
        - ``build_judge_prompt(data_content, script_output)``

    Subclasses **may** override:
        - ``script_patterns``: filenames to search for (default: implementation.py, plan.py)
        - ``script_timeout``: subprocess timeout in seconds (default: 300)
        - ``judge_temperature``: LLM temperature for judge call (default: 0.2)
        - ``judge_max_tokens``: max tokens for judge response (default: 4096)
        - ``prepare_data(data_path)``: convert data file for script input
        - ``parse_judge_response(response)``: custom JSON parsing
        - ``build_script_env(cfg)``: customize subprocess environment variables
    """

    # --- Class-level defaults (override in subclass) ---
    script_patterns: list[str] = ["implementation.py", "plan.py"]
    script_timeout: float = 300.0
    judge_temperature: float = 0.2
    judge_max_tokens: int = 4096

    def __init__(self, config: Any = None, provider_config: Any = None):
        """Initialize with optional config and provider for LLM API credentials.

        Args:
            config: Evaluator config object.
            provider_config: Resolved provider configuration (ProviderConfig)
                with base_url, api_key, and model fields.
        """
        super().__init__()
        base_url = ""
        api_key = ""
        model = ""

        if provider_config is not None:
            base_url = getattr(provider_config, "base_url", "") or ""
            api_key = getattr(provider_config, "api_key", "") or ""
            model = getattr(provider_config, "model", "") or ""

        if not (base_url and api_key) and config is not None:
            api_config: dict[str, str] = {}
            raw = getattr(config, "api_config", None)
            if isinstance(raw, dict):
                api_config = raw
            elif hasattr(config, "model_extra"):
                api_config = config.model_extra.get("api_config", {})
            base_url = base_url or api_config.get("base_url", "")
            api_key = api_key or api_config.get("api_key", "")
            model = model or api_config.get("model", "")

        self._base_url = base_url
        self._api_key = api_key
        self._model_name = model

        if self._base_url and self._api_key:
            self._client = AsyncOpenAI(
                api_key=self._api_key, base_url=self._base_url
            )
        else:
            self._client = None

    # ------------------------------------------------------------------
    # Abstract interface — subclass must implement
    # ------------------------------------------------------------------

    @abstractmethod
    def build_judge_prompt(
        self, data_content: str, script_output: str
    ) -> str:
        """Build the LLM judge prompt for this specific task.

        Args:
            data_content: Raw content of the data file (e.g. user profile YAML).
            script_output: Captured stdout from the executed script.

        Returns:
            Complete prompt string to send to the LLM judge.
        """

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def prepare_data(
        self, data_path: Path, project_root: Path
    ) -> tuple[Path, str]:
        """Prepare data file for script execution.

        Default: if YAML, convert to temp JSON; otherwise pass through.

        Args:
            data_path: Original data file path.
            project_root: Worktree root directory.

        Returns:
            Tuple of (path to pass to script, raw data content for judge).
        """
        raw_content = data_path.read_text(encoding="utf-8")

        if data_path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(raw_content)
            tmp_json = project_root / f"_data_tmp_{data_path.stem}.json"
            tmp_json.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            return tmp_json, raw_content

        return data_path, raw_content

    def build_script_env(self, cfg: EvalContext) -> dict[str, str]:
        """Build environment variables for the subprocess.

        Default: injects LLM_BASE_URL, LLM_API_KEY, LLM_MODEL and their
        OPENAI_* equivalents, plus encoding and proxy settings.

        Args:
            cfg: Evaluation context.

        Returns:
            Environment variable dict.
        """
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["NO_PROXY"] = "*"
        env["HTTP_PROXY"] = ""
        env["HTTPS_PROXY"] = ""
        if self._base_url:
            env["LLM_BASE_URL"] = self._base_url
            env["OPENAI_BASE_URL"] = self._base_url
        if self._api_key:
            env["LLM_API_KEY"] = self._api_key
            env["OPENAI_API_KEY"] = self._api_key
        if self._model_name:
            env["LLM_MODEL"] = self._model_name
        return env

    def parse_judge_response(self, response: str) -> dict[str, float]:
        """Parse metric scores from LLM judge response.

        Default: extract the first JSON object and read metric keys.

        Args:
            response: Raw LLM judge response text.

        Returns:
            Dict of metric name to float score.
        """
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start == -1 or json_end == 0:
            raise ValueError("No JSON object found in judge response")

        raw = response[json_start:json_end]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import re as _re

            cleaned = raw
            cleaned = cleaned.replace("{{", "{").replace("}}", "}")
            cleaned = _re.sub(r"//[^\n]*", "", cleaned)
            cleaned = _re.sub(r",\s*}", "}", cleaned)
            cleaned = _re.sub(r",\s*]", "]", cleaned)
            cleaned = _re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', cleaned)
            cleaned = cleaned.replace("'", '"')
            data = json.loads(cleaned)
        metric_names = [m.name for m in self.metrics]
        missing = [k for k in metric_names if k not in data]
        if missing:
            raise ValueError(f"Missing metric keys in judge response: {missing}")

        return {k: float(data[k]) for k in metric_names}

    # ------------------------------------------------------------------
    # Core evaluation pipeline
    # ------------------------------------------------------------------

    def _discover_script(self, project_root: Path) -> Path | None:
        """Find the executable script in the worktree.

        Args:
            project_root: Worktree root directory.

        Returns:
            Path to the script, or None if not found.
        """
        for pattern in self.script_patterns:
            candidate = project_root / pattern
            if candidate.exists():
                return candidate

        # Fallback: any .py file in root
        py_files = [f for f in project_root.glob("*.py") if f.is_file()]
        return py_files[0] if py_files else None

    async def evaluate(self, cfg: EvalContext) -> EvaluationResult:
        """Execute script and judge output with LLM.

        Args:
            cfg: Evaluation context with project_root and data_path.

        Returns:
            Evaluation result with scores from LLM judge.
        """
        start_time = time.time()

        def _fail(msg: str) -> EvaluationResult:
            return EvaluationResult(
                score=0.0,
                metrics={},
                success=False,
                error_message=msg,
                duration_ms=(time.time() - start_time) * 1000,
            )

        try:
            project_root = Path(cfg.project_root)

            # 1. Discover script
            script_path = self._discover_script(project_root)
            if script_path is None:
                return _fail("No Python script found in worktree.")

            # 2. Prepare data (skip if no data file configured)
            if cfg.data_path:
                data_path = Path(cfg.data_path)
                script_input_path, raw_data_content = self.prepare_data(
                    data_path, project_root
                )
                cmd = [sys.executable, str(script_path), str(script_input_path)]
                cache_stem = data_path.stem
            else:
                raw_data_content = ""
                cmd = [sys.executable, str(script_path)]
                cache_stem = "default"

            # 3. Execute script
            env = self.build_script_env(cfg)
            process = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.script_timeout,
                env=env,
            )

            if process.returncode != 0:
                return _fail(
                    f"Script execution failed (rc={process.returncode}):\n"
                    f"{process.stderr or ''}"
                )

            script_output = (process.stdout or "").strip()
            if not script_output:
                return _fail("Script ran but produced no output.")

            # Cache output for later inspection
            cache_file = project_root / f"_output_{cache_stem}.md"
            cache_file.write_text(script_output, encoding="utf-8")

            # 4. LLM judge
            if self._client is None:
                return _fail(
                    "No LLM client configured (missing api_config)."
                )

            judge_prompt = self.build_judge_prompt(
                raw_data_content, script_output
            )
            response = await self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": judge_prompt}],
                temperature=self.judge_temperature,
                max_tokens=self.judge_max_tokens,
            )

            judge_text = response.choices[0].message.content or ""
            if not judge_text.strip():
                return _fail("LLM judge returned empty response.")

            # 5. Parse scores
            metric_values = self.parse_judge_response(judge_text)
            score = self.compute_score(metric_values)

            return EvaluationResult(
                score=score,
                metrics=metric_values,
                success=True,
                duration_ms=(time.time() - start_time) * 1000,
            )

        except subprocess.TimeoutExpired:
            return _fail(
                f"Script execution timed out after {self.script_timeout}s."
            )
        except Exception as e:
            logger.error(f"[LLMJudgeEvaluator] {e}")
            return _fail(str(e))
