#!/usr/bin/env python3
"""Crux Evolve Seam Adapter (`runtime/skills/crux/crux-evolve/crux_evolve_adapter.py`).

Bridges Crux Discovery with the evolutionary heuristic design & numerical parameter-search
algorithms in `runtime/skills/crux/crux-evolve/engine` under the unified **Crux Evolve** brand,
without reinventing any algorithm or requiring heavy web/cloud dependencies:

- `island-plan`: Reuses `build_island_strategy` (`orchestrator/island_diversity.py`) to assign
  continuous exploration/exploitation & memory policies across parallel Crux Discovery agents.
- `select-survivors`: Reuses `select_diverse_survivors`, `code_fingerprint`, `token_similarity`,
  and `population_similarity` (`orchestrator/island_diversity.py`) using real `Algorithm` + `CodeArtifact`.
- `operator-prompt`: Reuses `eoh_prompt_templates.py` (I1/E1/E2/M1/M2) and `reevo_samplers.py`
  (short-term & long-term verbal gradient reflection) to construct operator prompts.
- `tune-params`: Reuses `ParameterSpace` + `maximize_bounded_parameters` (Sobol QMC + pattern search
  in `evaluator/solver/parameter_search.py`) and `load_candidate` / `apply_candidate_patch` (`candidate.py`).
- `methods`: Lists and inspects all 10 **Crux Evolve** method specs (`eoh`, `reevo`, `mcts-ahd`,
  `meoh`, `diverse-island-ga`, `island-ga`, `funsearch`, `dyca`, `nsga2`, `moead`) and AlphaEvolve
  mathematical benchmark experiences, rebranded cleanly to **Crux Evolve**.
- `sync-views`: Projects evolution state into `.crux/public/views/{board,tree,archive}.json` for
  Crux Desktop's live Evolution Tree & Leaderboard pane (`crux screen add --discovery`).
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path, PurePosixPath
import random
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import types
from typing import Any

sys.dont_write_bytecode = True

import yaml
import numpy as np

_DEFAULT_UPSTREAM = (
    str(Path(__file__).resolve().parent / "engine")
    if (Path(__file__).resolve().parent / "engine").exists()
    else "/root/humannize/crux-evolve"
)
CRUX_EVOLVE_UPSTREAM_ROOT = Path(
    os.environ.get("CRUX_EVOLVE_UPSTREAM_ROOT", _DEFAULT_UPSTREAM)
).resolve()
UPSTREAM_SRC = CRUX_EVOLVE_UPSTREAM_ROOT / "src" / "crux_evolve"
UPSTREAM_SKILLS = CRUX_EVOLVE_UPSTREAM_ROOT / "skills"
UPSTREAM_BENCHMARKS = (
    CRUX_EVOLVE_UPSTREAM_ROOT / "examples" / "applications" / "alphaevolve_math_benchmark"
)


def _bootstrap_upstream_namespace() -> None:
    """Mount `crux_evolve` subpackages without triggering SDK-heavy `__init__.py`."""
    try:
        import loguru as _loguru  # type: ignore[import-not-found]
    except ImportError:
        log_mod = types.ModuleType("loguru")
        log_mod.logger = logging.getLogger("crux.evolve")  # type: ignore[attr-defined]
        sys.modules["loguru"] = log_mod

    packages = [
        ("crux_evolve", ""),
        ("crux_evolve.agent", "/agent"),
        ("crux_evolve.builder", "/builder"),
        ("crux_evolve.consultant", "/consultant"),
        ("crux_evolve.coder", "/coder"),
        ("crux_evolve.config", "/config"),
        ("crux_evolve.evaluator", "/evaluator"),
        ("crux_evolve.evaluator.solver", "/evaluator/solver"),
        ("crux_evolve.infra", "/infra"),
        ("crux_evolve.infra.provider", "/infra/provider"),
        ("crux_evolve.infra.repo_analyzer", "/infra/repo_analyzer"),
        ("crux_evolve.infra.version_control", "/infra/version_control"),
        ("crux_evolve.orchestrator", "/orchestrator"),
        ("crux_evolve.planner", "/planner"),
        ("crux_evolve.planner.sampler", "/planner/sampler"),
        ("crux_evolve.planner.selector", "/planner/selector"),
        ("crux_evolve.utils", "/utils"),
    ]
    for pkg, rel in packages:
        if pkg not in sys.modules:
            mod = types.ModuleType(pkg)
            mod.__path__ = [f"{UPSTREAM_SRC}{rel}"]  # type: ignore[attr-defined]
            sys.modules[pkg] = mod

    from crux_evolve.infra.provider.base import BaseProvider  # type: ignore[import-not-found]

    sys.modules["crux_evolve.infra.provider"].BaseProvider = BaseProvider  # type: ignore[attr-defined]
    from crux_evolve.infra.repo_analyzer.base import AnalyzedRepository
    sys.modules["crux_evolve.infra.repo_analyzer"].AnalyzedRepository = AnalyzedRepository


_bootstrap_upstream_namespace()

from crux_evolve.agent.skill import load_skill_body  # type: ignore[import-not-found]  # noqa: E402
from crux_evolve.agent.runner import estimate_evolution_cost, build_config_summary_md  # type: ignore[import-not-found]  # noqa: E402
from crux_evolve.config.schema import AppConfig, CustomEvaluatorConfig, DatasetConfig  # type: ignore[import-not-found]  # noqa: E402
from crux_evolve.consultant.config_builder import ConfigBuilder  # type: ignore[import-not-found]  # noqa: E402
from crux_evolve.infra.version_control.base import BaseVersionControl, WorktreeInfo  # type: ignore[import-not-found]  # noqa: E402

# Preserve public exports used by templates without executing package initializers.
sys.modules["crux_evolve.config"].AppConfig = AppConfig
sys.modules["crux_evolve.config"].CustomEvaluatorConfig = CustomEvaluatorConfig
sys.modules["crux_evolve.config"].DatasetConfig = DatasetConfig
sys.modules["crux_evolve.infra.version_control"].WorktreeInfo = WorktreeInfo
sys.modules["crux_evolve.infra.version_control"].BaseVersionControl = BaseVersionControl

_pack_spec = importlib.util.spec_from_file_location(
    "crux_evolve_pack", UPSTREAM_SKILLS / "crux-evolve-cloud-package/scripts/validate_and_pack.py"
)
assert _pack_spec is not None and _pack_spec.loader is not None
_pack = importlib.util.module_from_spec(_pack_spec)
_pack_spec.loader.exec_module(_pack)
package_files = _pack.package_files
contained_path = _pack.contained_path
dataset_files = _pack.dataset_files
check_requirements = _pack.check_requirements

from crux_evolve.evaluator.solver.candidate import (  # type: ignore[import-not-found]  # noqa: E402
    apply_candidate_patch,
    load_candidate,
)
from crux_evolve.evaluator.solver.parameter_search import (  # type: ignore[import-not-found]  # noqa: E402
    ParameterSpace,
    maximize_bounded_parameters,
)
from crux_evolve.orchestrator.island_diversity import (  # type: ignore[import-not-found]  # noqa: E402
    build_island_strategy,
    code_fingerprint,
    population_similarity,
    select_diverse_survivors,
)
from crux_evolve.planner.base import (  # type: ignore[import-not-found]  # noqa: E402
    Algorithm,
    CodeArtifact,
    EvaluationResult,
    InsightType,
)
from crux_evolve.planner.sampler.eoh_prompt_templates import (  # type: ignore[import-not-found]  # noqa: E402
    build_e1_unified_prompt,
    build_e2_unified_prompt,
    build_i1_unified_prompt,
    build_m1_unified_prompt,
    build_m2_unified_prompt,
)
from crux_evolve.planner.sampler.reevo_samplers import (  # type: ignore[import-not-found]  # noqa: E402
    build_long_term_reflection_prompt,
    build_reevo_crossover_prompt,
    build_reevo_mutation_prompt,
    build_short_term_reflection_prompt,
)


def rebrand_to_crux_evolve(text: str) -> str:
    """Replace upstream brand references with `Crux Evolve` / `crux-evolve`."""
    replaced = re.sub(r"\bOpenLoopX\b", "Crux Evolve", text)
    replaced = re.sub(r"\bcrux_evolve\b", "crux-evolve", replaced)
    return replaced


def list_crux_evolve_methods(method_name: str | None = None) -> dict[str, Any]:
    """List all 10 Crux Evolve heuristic design methods or inspect one method's SKILL + params."""
    algo_dir = UPSTREAM_SKILLS / "algo-design"
    methods: list[dict[str, Any]] = []
    for sub in sorted(algo_dir.iterdir()) if algo_dir.is_dir() else []:
        if not sub.is_dir() or sub.name == "use_example" or sub.name.startswith("."):
            continue
        skill_md = sub / "SKILL.md"
        params_yaml = sub / "params.yaml"
        if not skill_md.is_file():
            continue
        raw_md = rebrand_to_crux_evolve(skill_md.read_text(encoding="utf-8", errors="replace"))
        desc_match = re.search(r'(?m)^description:\s*"?([^"\n]+)"?$', raw_md)
        desc = desc_match.group(1).strip() if desc_match else sub.name
        params = (
            yaml.safe_load(params_yaml.read_text(encoding="utf-8"))
            if params_yaml.is_file()
            else {}
        )
        entry: dict[str, Any] = {
            "method": sub.name,
            "description": desc,
            "recommended_params": params.get("evolution", params) if isinstance(params, dict) else {},
        }
        if method_name and sub.name == method_name:
            entry["skill_guide"] = raw_md
            entry["task_package_contract"] = rebrand_to_crux_evolve(load_skill_body())
            return entry
        methods.append(entry)

    benchmarks: list[dict[str, str]] = []
    if UPSTREAM_BENCHMARKS.is_dir():
        for bdir in sorted(UPSTREAM_BENCHMARKS.iterdir()):
            exp_md = bdir / "results" / "best" / "experiences" / "README.md"
            solve_py = bdir / "results" / "best" / "solve.py"
            if exp_md.is_file() or solve_py.is_file():
                benchmarks.append(
                    {
                        "case": bdir.name,
                        "best_solver": f"alphaevolve_math_benchmark/{bdir.name}/results/best/solve.py"
                        if solve_py.is_file()
                        else "",
                        "experience_notes": f"alphaevolve_math_benchmark/{bdir.name}/results/best/experiences/README.md"
                        if exp_md.is_file()
                        else "",
                    }
                )
    return {
        "engine": "Crux Evolve",
        "method_count": len(methods),
        "math_benchmark_count": len(benchmarks),
        "algo_design_methods": methods,
        "methods": methods,
        "math_benchmarks": benchmarks,
    }


def generate_island_plan(
    num_islands: int,
    stagnation_generations: int = 0,
    stagnation_threshold: int = 2,
    strength: float = 1.0,
    generation: int = 0,
) -> dict[str, Any]:
    """Compute Diverse Island GA strategy profiles across N parallel Crux Discovery agents."""
    profiles = []
    for idx in range(max(1, num_islands)):
        prof = build_island_strategy(
            idx,
            num_islands,
            stagnation_generations=stagnation_generations,
            stagnation_threshold=stagnation_threshold,
            strength=strength,
            generation=generation,
        )
        profiles.append({"island_id": idx, **prof.as_dict()})
    return {
        "engine": "Crux Evolve · Diverse Island Strategy",
        "num_islands": num_islands,
        "generation": generation,
        "islands": profiles,
    }


def run_diversity_survivor_selection(
    candidates_json: Path,
    count: int,
    novelty_ratio: float = 0.25,
) -> dict[str, Any]:
    """Select quality + code-diverse survivors from candidate JSON records."""
    raw = json.loads(candidates_json.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("candidates", [])
    population: list[Algorithm] = []
    for idx, item in enumerate(items):
        code_str = str(item.get("code") or "")
        file_path = str(item.get("file_path") or "solve.py")
        score = float(item.get("score", 0.0))
        alg = Algorithm(
            id=str(item.get("id") or f"cand_{idx}"),
            insight_type=InsightType.INITIAL,
            name=str(item.get("name") or item.get("id") or f"cand_{idx}"),
            description=str(item.get("description") or "candidate heuristic"),
            code_artifacts=[
                CodeArtifact(
                    file_path=file_path,
                    content=code_str,
                    language="python",
                    content_mode="full",
                )
            ],
            evaluation=EvaluationResult(score=score, metrics={"score": score}),
        )
        population.append(alg)

    survivors = select_diverse_survivors(population, count=count, novelty_ratio=novelty_ratio)
    self_sim = population_similarity(survivors, survivors) if survivors else 0.0
    return {
        "engine": "Crux Evolve · Diversity Selector",
        "input_count": len(population),
        "selected_count": len(survivors),
        "novelty_ratio": novelty_ratio,
        "survivor_self_similarity": round(self_sim, 4),
        "survivors": [
            {
                "id": s.id,
                "name": s.name,
                "score": s.score,
                "fingerprint": code_fingerprint(s),
            }
            for s in survivors
        ],
    }


def build_evolution_operator_prompt(
    operator: str,
    task_description: str,
    parents_json: Path | None = None,
    reflection: str = "",
) -> dict[str, Any]:
    """Build an EoH (I1/E1/E2/M1/M2) or ReEvo (short/long reflection, crossover, mutation) prompt."""
    parents: list[dict[str, Any]] = []
    if parents_json and parents_json.is_file():
        loaded = json.loads(parents_json.read_text(encoding="utf-8"))
        parents = loaded if isinstance(loaded, list) else loaded.get("parents", [])

    alg_parents: list[Algorithm] = []
    for idx, p in enumerate(parents):
        code_str = str(p.get("code") or "def solve(x):\n    return x\n")
        score = float(p.get("score", 0.0))
        alg_parents.append(
            Algorithm(
                id=str(p.get("id") or f"p_{idx}"),
                insight_type=InsightType.INITIAL,
                name=str(p.get("name") or p.get("id") or f"p_{idx}"),
                description=str(p.get("description") or p.get("thought") or "heuristic candidate"),
                code_artifacts=[
                    CodeArtifact(
                        file_path="solve.py",
                        content=code_str,
                        language="python",
                        content_mode="full",
                    )
                ],
                evaluation=EvaluationResult(score=score, metrics={"score": score}),
            )
        )

    op = operator.lower().strip()
    if op == "i1":
        prompt = build_i1_unified_prompt(task_description, None)
    elif op == "e1":
        prompt = build_e1_unified_prompt(task_description, None, alg_parents)
    elif op == "e2":
        prompt = build_e2_unified_prompt(task_description, None, alg_parents)
    elif op == "m1":
        if not alg_parents:
            raise ValueError("Operator m1 requires at least 1 parent in --parents-json")
        prompt = build_m1_unified_prompt(task_description, None, alg_parents[0])
    elif op == "m2":
        if not alg_parents:
            raise ValueError("Operator m2 requires at least 1 parent in --parents-json")
        prompt = build_m2_unified_prompt(task_description, None, alg_parents[0])
    elif op == "reevo-short-reflection":
        if len(alg_parents) < 2:
            raise ValueError("reevo-short-reflection requires 2 parents (worse, better)")
        prompt = build_short_term_reflection_prompt(task_description, alg_parents[0], alg_parents[1])
    elif op == "reevo-long-reflection":
        prompt = build_long_term_reflection_prompt(
            task_description, reflection, [p.get("reflection", "") for p in parents]
        )
    elif op == "reevo-crossover":
        if len(alg_parents) < 2:
            raise ValueError("reevo-crossover requires 2 parents")
        prompt = build_reevo_crossover_prompt(
            task_description, None, alg_parents[0], alg_parents[1], reflection
        )
    elif op == "reevo-mutation":
        if not alg_parents:
            raise ValueError("reevo-mutation requires at least 1 parent")
        prompt = build_reevo_mutation_prompt(task_description, None, alg_parents[0], reflection)
    else:
        raise ValueError(f"Unsupported operator: {operator}")

    return {"engine": "Crux Evolve", "operator": op, "prompt": rebrand_to_crux_evolve(prompt)}


def advise_evolvable_blocks(source_file: Path) -> dict[str, Any]:
    """Scan a Python file for `# EVOLVE_START` / `# EVOLVE_END` markers or rank top candidate functions."""
    text = source_file.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    explicit_blocks: list[dict[str, Any]] = []
    start_line: int | None = None
    block_name: str = "evolve_block"
    for idx, line in enumerate(lines, start=1):
        if "EVOLVE_START" in line or "CRUX-EVOLVE-BLOCK-START" in line:
            start_line = idx
            after_colon = line.split(":", 1)[1].strip() if ":" in line else ""
            block_name = re.sub(r"=+$", "", after_colon).strip() or f"block_{idx}"
        elif ("EVOLVE_END" in line or "CRUX-EVOLVE-BLOCK-END" in line) and start_line is not None:
            explicit_blocks.append(
                {
                    "name": block_name,
                    "kind": "explicit_evolve_block",
                    "start_line": start_line,
                    "end_line": idx,
                    "snippet": "\n".join(lines[start_line - 1 : idx]),
                }
            )
            start_line = None

    candidates: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text, filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno:
                loc = node.end_lineno - node.lineno + 1
                loops = sum(1 for sub in ast.walk(node) if isinstance(sub, (ast.For, ast.While, ast.ListComp)))
                branches = sum(1 for sub in ast.walk(node) if isinstance(sub, ast.If))
                score = loops * 3 + branches * 2 + min(loc, 120) * 0.2
                candidates.append(
                    {
                        "function": node.name,
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "loc": loc,
                        "loops": loops,
                        "branches": branches,
                        "evolvability_score": round(score, 2),
                    }
                )
        candidates.sort(key=lambda c: c["evolvability_score"], reverse=True)
    except SyntaxError:
        pass

    return {
        "engine": "Crux Evolve · Block Advisor",
        "file": str(source_file),
        "has_explicit_evolve_blocks": len(explicit_blocks) > 0,
        "explicit_blocks": explicit_blocks,
        "explicit_evolve_blocks": explicit_blocks,
        "recommended_functions": candidates[:8],
    }


def tune_candidate_parameters(
    candidate_path: Path,
    eval_cmd: str | None = None,
    symbol: str = "MODEL_SPEC",
    max_evaluations: int = 32,
    seed: int = 42,
    apply_patch: bool = False,
) -> dict[str, Any]:
    """Run Sobol QMC + pattern search (`maximize_bounded_parameters`) on a candidate's `parameters` spec."""
    spec = load_candidate(candidate_path, symbol=symbol)
    if not isinstance(spec, dict):
        raise ValueError("Candidate symbol must be a mapping")

    uses_params_bounds = "params" in spec and "bounds" in spec
    if uses_params_bounds:
        p_map = spec["params"]
        b_map = spec["bounds"]
        raw_params: dict[str, Any] = {}
        for k, v in p_map.items():
            if k in b_map and isinstance(b_map[k], (list, tuple)) and len(b_map[k]) == 2:
                raw_params[k] = {
                    "initial": float(v),
                    "lower": float(b_map[k][0]),
                    "upper": float(b_map[k][1]),
                }
            else:
                raw_params[k] = float(v)
    else:
        raw_params = spec.get("parameters", spec)
        if not isinstance(raw_params, dict):
            raise ValueError("Candidate must contain a 'parameters' mapping")

    space = ParameterSpace.from_mapping(raw_params, max_dimensions=32)

    local_eval_fn = None
    if not eval_cmd and candidate_path.suffix == ".py":
        ns: dict[str, Any] = {}
        try:
            exec(compile(candidate_path.read_text(encoding="utf-8"), str(candidate_path), "exec"), ns)
            if callable(ns.get("evaluate_candidate")):
                local_eval_fn = ns["evaluate_candidate"]
        except Exception:
            local_eval_fn = None

    def objective_fn(params: dict[str, float]) -> float | None:
        if eval_cmd:
            env = {**os.environ, "CRUX_EVOLVE_PARAMS_JSON": json.dumps(params)}
            proc = subprocess.run(
                eval_cmd,
                shell=True,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            if proc.returncode != 0:
                return None
            try:
                out = json.loads(proc.stdout.strip().splitlines()[-1])
                return float(out["score"]) if isinstance(out, dict) else float(out)
            except Exception:
                return None
        if local_eval_fn is not None:
            return float(local_eval_fn(params))
        # Default concave test objective centered at midpoint when no external command is given
        total = 0.0
        for p in space.tunable:
            mid = 0.5 * (p.lower + p.upper)
            total -= (params[p.name] - mid) ** 2
        return total

    initial_params = {**space.fixed, **{p.name: p.initial for p in space.tunable}}
    initial_score = objective_fn(initial_params)

    result = maximize_bounded_parameters(
        space,
        objective_fn,
        max_evaluations=max_evaluations,
        seed=seed,
    )
    if result is None:
        return {"engine": "Crux Evolve · Parameter Search", "status": "infeasible", "feasible": False}

    if apply_patch:
        if uses_params_bounds:
            top_patch: dict[str, Any] = {
                "params": {k: float(result.parameters[k]) for k in spec["params"]},
                "bounds": spec["bounds"],
            }
        else:
            patch = space.initial_value_patch(result.parameters)
            top_patch = {"parameters": patch} if "parameters" in spec else patch
        apply_candidate_patch(candidate_path, top_patch, symbol=symbol)

    return {
        "engine": "Crux Evolve · Parameter Search",
        "status": "ok",
        "feasible": True,
        "initial_score": initial_score,
        "best_score": result.objective,
        "best_objective": result.objective,
        "best_parameters": result.parameters,
        "evaluations": result.evaluations,
        "stopped_reason": result.stopped_reason,
        "strategy": result.strategy,
        "patched": apply_patch,
    }


def classify_algorithm_category(name: str, explicit_category: str | None = None) -> str:
    """Classify an algorithm into `proposed`, `baseline`, or `ablation` per Stage 10/13 evolve_scope."""
    if explicit_category and explicit_category.strip().lower() in {"proposed", "baseline", "ablation"}:
        return explicit_category.strip().lower()
    lowered = name.strip().lower()
    if any(tok in lowered for tok in ("ablation", "no_", "without_", "w/o", "wo_")):
        return "ablation"
    if any(tok in lowered for tok in ("baseline", "random_search", "naive_baseline", "reference_baseline")):
        return "baseline"
    return "proposed"


def _extract_numeric_scores(payload: Any) -> tuple[list[float], int, int]:
    """Return (valid_scores, total_instances, lost_instances) from an evaluator payload or score value."""
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        val = float(payload)
        return ([val] if np.isfinite(val) else [], 1, 0 if np.isfinite(val) else 1)
    if isinstance(payload, dict):
        samples = payload.get("samples")
        if isinstance(samples, list):
            scores: list[float] = []
            lost = 0
            for item in samples:
                raw = item.get("score") if isinstance(item, dict) else item
                if isinstance(raw, (int, float)) and not isinstance(raw, bool) and np.isfinite(float(raw)):
                    scores.append(float(raw))
                else:
                    lost += 1
            return scores, len(samples), lost
        for key in ("score", "objective", "fitness", "mean_score"):
            raw = payload.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and np.isfinite(float(raw)):
                return [float(raw)], 1, 0
    if isinstance(payload, list):
        scores = [
            float(x)
            for x in payload
            if isinstance(x, (int, float)) and not isinstance(x, bool) and np.isfinite(float(x))
        ]
        return scores, len(payload), max(0, len(payload) - len(scores))
    return [], 0, 0


def build_comparison_entry(
    baseline_payload: Any,
    evolved_payload: Any,
    *,
    metric_direction: str = "maximize",
    n_instances_total: int | None = None,
    failed: bool = False,
) -> dict[str, Any]:
    """Compute a Stage 13 `crux_evolve_comparison.json` algorithm comparison & promotion gate entry."""
    direction = "minimize" if str(metric_direction).strip().lower() == "minimize" else "maximize"
    b_scores, b_total, _ = _extract_numeric_scores(baseline_payload)
    e_scores, e_total, e_lost = _extract_numeric_scores(evolved_payload)
    total = n_instances_total if n_instances_total is not None else max(b_total, e_total, len(b_scores), len(e_scores))
    compared = min(len(b_scores), len(e_scores)) if b_scores and e_scores else len(e_scores)
    lost = max(e_lost, max(0, len(b_scores) - len(e_scores))) if b_scores else e_lost

    baseline_val = float(np.mean(b_scores)) if b_scores else None
    evolved_val = float(np.mean(e_scores)) if e_scores else None
    is_failed = bool(failed or evolved_val is None or (total > 0 and compared == 0))

    delta_pct: float | None = None
    improved = False
    if baseline_val is not None and evolved_val is not None and not is_failed:
        denom = max(abs(baseline_val), 1e-9)
        raw_diff = (baseline_val - evolved_val) if direction == "minimize" else (evolved_val - baseline_val)
        delta_pct = round((raw_diff / denom) * 100.0, 4)
        improved = raw_diff > 1e-12

    full_coverage = total == 0 or (compared >= total and lost == 0)
    promoted = bool(not is_failed and improved and full_coverage)

    if is_failed:
        reason = "Retained baseline (fail_silently): candidate evaluation failed or produced no valid score"
    elif not full_coverage:
        reason = f"Retained baseline (fail_silently): incomplete instance coverage ({compared}/{total}, lost={lost})"
    elif promoted:
        sign = "+" if (delta_pct or 0.0) > 0 else ""
        reason = f"Promoted ({sign}{(delta_pct or 0.0):.2f}% vs baseline across {compared}/{total} instances)"
    else:
        reason = (
            f"Retained baseline (fail_silently): evolved {evolved_val:.6f} did not beat baseline {baseline_val:.6f}"
            if baseline_val is not None and evolved_val is not None
            else "Retained baseline (fail_silently)"
        )

    return {
        "baseline": baseline_val,
        "evolved": evolved_val,
        "delta_pct": delta_pct,
        "promoted": promoted,
        "failed": is_failed,
        "n_instances_compared": compared,
        "n_instances_total": total,
        "lost_instances": lost,
        "reason": reason,
    }


def sync_evolution_state_to_crux_views(state_file: Path, run_dir: Path) -> dict[str, Any]:
    """Project an evolution_state.json into `.crux/public/views/{board,tree,archive,comparison}.json`."""
    raw = json.loads(state_file.read_text(encoding="utf-8"))
    views_dir = run_dir / ".crux" / "public" / "views"
    views_dir.mkdir(parents=True, exist_ok=True)

    metric_direction = str(raw.get("metric_direction") or "maximize").strip().lower()
    allowed_categories = set(
        (raw.get("evolve_scope") or {}).get("categories") or ["proposed"]
    )
    individuals = raw.get("population") or raw.get("individuals") or raw.get("history") or []
    nodes: list[dict[str, Any]] = []
    for idx, ind in enumerate(individuals):
        cid = str(ind.get("id") or ind.get("commit") or f"gen_{idx}")
        parent = ind.get("parent_id") or ind.get("parent")
        parent_ids = ind.get("parent_ids")
        if not isinstance(parent_ids, list):
            parent_ids = [str(parent)] if parent else []
        island_id = int(ind.get("island_id", ind.get("island", 0)) or 0)
        algo_name = str(ind.get("algorithm") or ind.get("direction_id") or raw.get("algorithm") or "proposed_solver")
        category = classify_algorithm_category(algo_name, ind.get("category"))
        nodes.append(
            {
                "id": cid,
                "commit": cid,
                "name": str(ind.get("name") or cid),
                "parent": parent,
                "parent_ids": [str(p) for p in parent_ids if p],
                "island_id": island_id,
                "algorithm": algo_name,
                "category": category,
                "score": ind.get("score"),
                "generation": int(ind.get("generation", idx) or 0),
                "operator": ind.get("operator", "evolve"),
                "summary": ind.get("description") or ind.get("thought") or cid,
            }
        )

    scored_nodes = [n for n in nodes if isinstance(n.get("score"), (int, float))]
    ranked = sorted(
        scored_nodes,
        key=lambda x: float(x["score"]),
        reverse=metric_direction != "minimize",
    )

    by_algo: dict[str, list[dict[str, Any]]] = {}
    for n in nodes:
        if n["category"] not in allowed_categories:
            continue
        by_algo.setdefault(n["algorithm"], []).append(n)

    algorithms_comp: dict[str, dict[str, Any]] = {}
    for algo_name, group in by_algo.items():
        g_scored = [n for n in group if isinstance(n.get("score"), (int, float))]
        if not g_scored:
            algorithms_comp[algo_name] = build_comparison_entry(None, None, metric_direction=metric_direction, failed=True)
            continue
        seed_nodes = [n for n in g_scored if n["generation"] == 0] or [g_scored[0]]
        baseline_score = float(seed_nodes[0]["score"])
        best_node = (
            min(g_scored, key=lambda x: float(x["score"]))
            if metric_direction == "minimize"
            else max(g_scored, key=lambda x: float(x["score"]))
        )
        algorithms_comp[algo_name] = build_comparison_entry(
            baseline_score,
            float(best_node["score"]),
            metric_direction=metric_direction,
            n_instances_total=1,
        )

    comparison = {
        "generated": state_file.name,
        "metric_direction": metric_direction,
        "base": "generation_0_seed",
        "fail_silently": True,
        "evolve_scope": {"categories": sorted(allowed_categories)},
        "n_promoted": sum(1 for v in algorithms_comp.values() if v.get("promoted") is True),
        "algorithms": algorithms_comp,
    }

    board = {
        "engine": "Crux Evolve",
        "best": ranked[0] if ranked else None,
        "leaderboard": ranked[:25],
        "directions": [{"id": "crux-evolve", "count": len(nodes)}],
        "comparison": comparison,
    }
    tree = {"nodes": nodes}
    archive = {"members": ranked[:10], "nodes": nodes, "comparison": comparison}

    (views_dir / "board.json").write_text(json.dumps(board, indent=2), encoding="utf-8")
    (views_dir / "tree.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    (views_dir / "archive.json").write_text(json.dumps(archive, indent=2), encoding="utf-8")
    (views_dir / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    (run_dir / "crux_evolve_comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    return {
        "engine": "Crux Evolve",
        "views_dir": str(views_dir),
        "node_count": len(nodes),
        "best_score": ranked[0]["score"] if ranked else None,
        "n_promoted": comparison["n_promoted"],
        "comparison": comparison,
    }


def _read_config(project: Path) -> dict[str, Any]:
    config = yaml.safe_load((project / "config.yaml").read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a mapping")
    return config


def _self_test(project: Path) -> str:
    # Templates need the same light namespaces in their fresh Python interpreter.
    with tempfile.TemporaryDirectory(prefix="crux-evolve-imports-") as temporary:
        Path(temporary, "sitecustomize.py").write_text(
            "import os, runpy\n"
            "os.environ.pop('PYTHONPATH', None)\n"
            f"runpy.run_path({str(Path(__file__).resolve())!r})\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "test_evaluator.py"], cwd=project,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": temporary},
            capture_output=True, text=True, timeout=180,
        )
    if result.returncode or re.search(r"(?m)^Success:\s*False\b", result.stdout):
        raise ValueError(f"test_evaluator.py failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout + result.stderr


def scaffold_package(template: str, dest: Path, project_name: str | None, seed: int | None) -> dict[str, Any]:
    templates = {
        "tsp": UPSTREAM_SKILLS / "crux-evolve-task-builder/reference/templates/tsp",
        "lunarlander": UPSTREAM_SKILLS / "crux-evolve-task-builder/reference/templates/lunarlander",
        "knapsack": UPSTREAM_SKILLS / "crux-evolve-cloud-package/assets/knapsack",
    }
    dest = dest.resolve()
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError("Choose a new or empty destination; existing files are never overwritten")
    shutil.copytree(templates[template], dest, dirs_exist_ok=True)
    config = _read_config(dest)
    if project_name is not None:
        config["project_name"] = project_name
    if seed is not None:
        config["random_seed"] = seed
    config.setdefault("version_control", {}).update(type="git_worktree", enabled=True)
    (dest / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    if template == "lunarlander":
        # The upstream self-test points at the package root instead of its policy directory.
        test = dest / "test_evaluator.py"
        test.write_text(test.read_text(encoding="utf-8").replace("project_root=str(task_dir),", "project_root=str(task_dir / 'policy'),"), encoding="utf-8")
    files = package_files(dest)
    check_requirements(dest)
    cost = estimate_evolution_cost(config["evolution"])
    _self_test(dest)
    return {
        "engine": "Crux Evolve", "status": "ok", "template": template,
        "project_dir": str(dest), "project_name": config["project_name"],
        "random_seed": config.get("random_seed"), "files": [p.as_posix() for p in files],
        "cost_estimate": cost, "self_test_passed": True,
        "config_summary_md": rebrand_to_crux_evolve(build_config_summary_md(str(dest.parent), dest.name, "en")),
    }


def switch_method(project: Path, method: str, seed: int | None) -> dict[str, Any]:
    methods = {
        "island_ga": "llm_evolution", "diverse_island_ga": "llm_evolution",
        "dyca": "llm_evolution", "meoh": "meoh_evolution", "eoh": "eoh_evolution",
        "reevo": "reevo_evolution", "mcts_ahd": "mcts_ahd_evolution",
    }
    method = method.replace("-", "_")
    if method not in methods:
        raise ValueError(f"Unsupported method: {method}")
    config = _read_config(project)
    if seed is not None and seed != config.get("random_seed"):
        raise ValueError("random_seed is locked; use the package seed for fair method comparisons")
    if not config.get("version_control", {}).get("enabled") or config["version_control"].get("type") != "git_worktree":
        raise ValueError("Fair comparisons require enabled git_worktree version_control")
    params = yaml.safe_load((UPSTREAM_SKILLS / "algo-design" / method.replace("_", "-") / "params.yaml").read_text(encoding="utf-8"))
    config["evolution"] = {**params["evolution"], "type": method}
    config.setdefault("planner", {})["type"] = methods[method]
    _, errors = ConfigBuilder(config).build_partial()
    cost = estimate_evolution_cost(config["evolution"])
    if not errors:
        (project / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return {
        "engine": "Crux Evolve", "status": "invalid" if errors else "ok",
        "evolution_type": method, "planner_type": methods[method],
        "fair_evaluation_locked": {"evaluator": config["evaluator"], "random_seed": config.get("random_seed"), "version_control": "git_worktree"},
        "cost_estimate": cost, "validation_errors": errors,
    }


def evaluate_candidate(project: Path, worktree: Path | None, ssh_host: str | None,
                       remote_dir: str | None, checkpoint: Path | None) -> dict[str, Any]:
    project = project.resolve()
    config_dict = _read_config(project)
    config = AppConfig.from_dict(config_dict)
    # Upstream Python templates use an empty build mapping to mean no compilation.
    if config.planner.build is not None and not config.planner.build.script:
        config.planner.build = None
    if not config.version_control.enabled or config.version_control.type != "git_worktree":
        raise ValueError("Candidate evaluation requires enabled git_worktree version_control")
    files = package_files(project)
    check_requirements(project)
    instances = dataset_files(project, config.evaluator.dataset)
    fingerprint = hashlib.sha256(json.dumps({
        "evaluator": config_dict["evaluator"], "providers": config_dict.get("providers"),
        "random_seed": config.random_seed,
        "dataset": [(p.relative_to(project).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()) for p in instances],
    }, sort_keys=True).encode()).hexdigest()
    if checkpoint and checkpoint.exists():
        prior = json.loads(checkpoint.read_text(encoding="utf-8"))
        if prior.get("benchmark_fingerprint") != fingerprint:
            raise ValueError("Checkpoint benchmark or random_seed differs from this package")
    if remote_dir and not ssh_host:
        raise ValueError("--remote-dir requires --ssh-host")
    with tempfile.TemporaryDirectory(prefix="crux-evolve-evaluate-") as temporary:
        snapshot = Path(temporary) / "package"
        for relative in files:
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project / relative, target)
        candidate_path = contained_path(snapshot, config.version_control.local_path)
        if not candidate_path.is_dir() or candidate_path == snapshot:
            raise ValueError("version_control.local_path must name an included algorithm subdirectory")
        # Git lives entirely in the temporary snapshot, including dirty/untracked input files.
        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=snapshot, capture_output=True, text=True, check=True, timeout=30)
        git("init", "-q")
        git("add", "-f", ".")
        git("-c", "user.name=Crux Evolve", "-c", "user.email=crux-evolve@local", "-c", "commit.gpgsign=false", "commit", "-qm", "Evaluation snapshot")
        isolated = Path(temporary) / "worktree"
        git("worktree", "add", "--detach", str(isolated), "HEAD")
        source = contained_path(project, config.version_control.local_path)
        if not source.is_dir():
            raise ValueError("Candidate algorithm directory is missing")
        if worktree:
            worktree = worktree.resolve()
            if not worktree.is_dir():
                raise ValueError("--worktree must be an algorithm directory")
            # Reuse the package collector's link/secret checks for the external candidate.
            overlay = Path(temporary) / "candidate-input"
            shutil.copytree(worktree, overlay, symlinks=True, ignore=shutil.ignore_patterns(*_pack.EXCLUDED_DIRS))
            has_config = (overlay / "config.yaml").exists() or (overlay / "config.yaml").is_symlink()
            if not has_config:
                (overlay / "config.yaml").write_text("{}\n", encoding="utf-8")
            candidate_files = package_files(overlay)
        output = ""
        baseline = None
        if not ssh_host:
            output = _self_test(isolated)
            random.seed(config.random_seed)
            np.random.seed(config.random_seed)
            baseline = asyncio.run(_pack.evaluate_snapshot(isolated, config, dataset_files(isolated, config.evaluator.dataset)))
        if worktree:
            target_root = contained_path(isolated, config.version_control.local_path)
            shutil.rmtree(target_root)
            target_root.mkdir()
            for relative in candidate_files:
                if relative == Path("config.yaml") and not has_config:
                    continue
                target = target_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(overlay / relative, target)
        result: dict[str, Any] = {
            "engine": "Crux Evolve · Evaluator", "mode": "ssh_remote" if ssh_host else "local_worktree",
            "project_dir": str(project), "random_seed": config.random_seed,
            "benchmark_fingerprint": fingerprint,
        }
        if ssh_host:
            remote_dir = remote_dir or Path(temporary).name
            if PurePosixPath(remote_dir).is_absolute() or any(p in {"", ".", ".."} for p in remote_dir.split("/")) or any(c in remote_dir for c in "\\\n\r\0"):
                raise ValueError("--remote-dir must be relative to the remote workspace without parent traversal")
            bundle = Path(temporary) / "bundle"
            shutil.copytree(snapshot, bundle / "package", ignore=shutil.ignore_patterns(*_pack.EXCLUDED_DIRS))
            shutil.copytree(contained_path(isolated, config.version_control.local_path), bundle / "candidate")
            runtime = bundle / "upstream"
            shutil.copytree(UPSTREAM_SRC, runtime / "src/crux_evolve", ignore=shutil.ignore_patterns(*_pack.EXCLUDED_DIRS, ".env*"))
            validator = runtime / "skills/crux-evolve-cloud-package/scripts/validate_and_pack.py"
            validator.parent.mkdir(parents=True)
            shutil.copy2(Path(_pack.__file__), validator)
            shutil.copy2(Path(__file__), bundle / "adapter.py")
            (bundle / "test_evaluator.py").write_text(
                "import json, os, runpy\nfrom pathlib import Path\n"
                "root = Path(__file__).resolve().parent\n"
                "os.environ['CRUX_EVOLVE_UPSTREAM_ROOT'] = str(root / 'upstream')\n"
                "adapter = runpy.run_path(str(root / 'adapter.py'))\n"
                "result = adapter['evaluate_candidate'](root / 'package', root / 'candidate', None, None, None)\n"
                "print(json.dumps(result))\n", encoding="utf-8",
            )
            archive = Path(temporary) / "evaluation.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                stream.add(bundle, arcname=".")
            # crux remote transfers regular files within its local/remote workspace roots.
            transfer = subprocess.run(["crux", "remote", "put", ssh_host, archive.name, f"{remote_dir}.tar.gz"], cwd=temporary, capture_output=True, text=True, timeout=180)
            if transfer.returncode:
                raise ValueError(f"Remote transfer failed: {transfer.stdout}\n{transfer.stderr}")
            unpack = (
                "import os,tarfile; "
                f"os.makedirs({remote_dir!r}, exist_ok=False); "
                f"tarfile.open({(remote_dir + '.tar.gz')!r}).extractall({remote_dir!r}, filter='data'); "
                f"os.unlink({(remote_dir + '.tar.gz')!r})"
            )
            extracted = subprocess.run(["crux", "remote", "exec", ssh_host, "--", "python3", "-c", unpack], capture_output=True, text=True, timeout=180)
            if extracted.returncode:
                raise ValueError(f"Remote extraction failed: {extracted.stdout}\n{extracted.stderr}")
            execution = subprocess.run(["crux", "remote", "exec", ssh_host, "--", "python3", f"{remote_dir}/test_evaluator.py"], capture_output=True, text=True, timeout=360)
            if execution.returncode:
                raise ValueError(f"Remote evaluator failed: {execution.stdout}\n{execution.stderr}")
            remote_result = json.loads(execution.stdout)
            if remote_result.get("status") != "passed" or not remote_result.get("test_evaluator_passed"):
                raise ValueError(f"Remote evaluator did not pass: {remote_result}")
            result.update(baseline=remote_result["baseline"], candidate=remote_result["candidate"])
            output = remote_result["output"] + execution.stderr
            result["remote_dir"] = remote_dir
        else:
            result["baseline"] = baseline
            random.seed(config.random_seed)
            np.random.seed(config.random_seed)
            result["candidate"] = asyncio.run(_pack.evaluate_snapshot(isolated, config, dataset_files(isolated, config.evaluator.dataset)))
        metric_direction = str(
            config_dict.get("metric_direction")
            or (config_dict.get("evaluator") or {}).get("metric_direction")
            or ("minimize" if (config_dict.get("evaluator") or {}).get("lower_is_better") else "maximize")
        )
        algo_key = str(config_dict.get("project_name") or project.name)
        comp_entry = build_comparison_entry(
            result.get("baseline"),
            result.get("candidate"),
            metric_direction=metric_direction,
            n_instances_total=len(instances),
        )
        comparison = {
            "generated": worktree.name if worktree else "candidate",
            "metric_direction": metric_direction,
            "base": "package_seed_baseline",
            "fail_silently": True,
            "evolve_scope": {"categories": ["proposed"]},
            "n_promoted": 1 if comp_entry["promoted"] else 0,
            "algorithms": {algo_key: comp_entry},
        }
        result.update(
            status="passed",
            test_evaluator_passed=True,
            output=output,
            promoted=comp_entry["promoted"],
            comparison=comparison,
        )
        if checkpoint:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=checkpoint.parent, delete=False, encoding="utf-8") as stream:
                staging = Path(stream.name)
                json.dump(result, stream, indent=2)
            try:
                staging.replace(checkpoint)
            finally:
                staging.unlink(missing_ok=True)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crux Evolve — Evolutionary Algorithm & Heuristic Optimization CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_m = sub.add_parser("methods", help="List all 10 Crux Evolve methods or inspect one method's guide")
    p_m.add_argument("--name", default=None, help="Specific method name (e.g. eoh, reevo, mcts-ahd, diverse-island-ga)")

    p_ip = sub.add_parser("island-plan", help="Generate Diverse Island GA strategy spectrum for parallel Crux agents")
    p_ip.add_argument("--islands", type=int, default=3)
    p_ip.add_argument("--stagnation", type=int, default=0)
    p_ip.add_argument("--generation", type=int, default=0)

    p_sel = sub.add_parser("select-survivors", help="Select quality + code-diverse survivors from candidates JSON")
    p_sel.add_argument("--candidates", required=True, help="Path to JSON file with candidates")
    p_sel.add_argument("--count", type=int, default=4)
    p_sel.add_argument("--novelty-ratio", type=float, default=0.25)

    p_op = sub.add_parser("operator-prompt", help="Generate structured EoH or ReEvo operator prompt")
    p_op.add_argument("--operator", required=True, help="i1 | e1 | e2 | m1 | m2 | reevo-short-reflection | reevo-crossover | reevo-mutation")
    p_op.add_argument("--task", required=True, help="Problem / task description")
    p_op.add_argument("--parents-json", default=None, help="JSON file of parent candidates")
    p_op.add_argument("--reflection", default="", help="Reflection text for ReEvo operators")

    p_adv = sub.add_parser("advise-blocks", help="Scan a source file for # EVOLVE_START/END or recommend evolvable functions")
    p_adv.add_argument("--file", required=True, help="Source file path")

    p_tune = sub.add_parser("tune-params", help="Run Sobol QMC + pattern search on bounded candidate parameters")
    p_tune.add_argument("--candidate", required=True, help="Path to candidate .py / .json / .yaml")
    p_tune.add_argument("--eval-cmd", default=None, help="Shell command reading CRUX_EVOLVE_PARAMS_JSON and printing JSON score")
    p_tune.add_argument("--symbol", default="MODEL_SPEC")
    p_tune.add_argument("--max-evals", type=int, default=32)
    p_tune.add_argument("--apply", action="store_true")

    p_sync = sub.add_parser("sync-views", help="Project evolution_state.json into .crux/public/views/{board,tree,archive}.json")
    p_sync.add_argument("--state-file", required=True)
    p_sync.add_argument("--run-dir", required=True)

    p_scaffold = sub.add_parser("scaffold-package", help="Copy and self-test an upstream task template without model calls")
    p_scaffold.add_argument("--template", choices=["tsp", "knapsack", "lunarlander"], required=True)
    p_scaffold.add_argument("--dest", type=Path, required=True)
    p_scaffold.add_argument("--project-name")
    p_scaffold.add_argument("--seed", type=int)

    p_switch = sub.add_parser("switch-method", help="Switch upstream method parameters with the benchmark locked")
    p_switch.add_argument("--project-dir", type=Path, required=True)
    p_switch.add_argument("--method", required=True)
    p_switch.add_argument("--seed", type=int)

    p_evaluate = sub.add_parser("evaluate-candidate", help="Evaluate an isolated candidate locally or over SSH")
    p_evaluate.add_argument("--project-dir", type=Path, required=True)
    p_evaluate.add_argument("--worktree", type=Path)
    p_evaluate.add_argument("--ssh-host")
    p_evaluate.add_argument("--remote-dir")
    p_evaluate.add_argument("--resume-checkpoint", type=Path)

    args = parser.parse_args(argv)
    if args.cmd == "scaffold-package":
        out = scaffold_package(args.template, args.dest, args.project_name, args.seed)
    elif args.cmd == "switch-method":
        out = switch_method(args.project_dir, args.method, args.seed)
    elif args.cmd == "evaluate-candidate":
        out = evaluate_candidate(args.project_dir, args.worktree, args.ssh_host, args.remote_dir, args.resume_checkpoint)
    elif args.cmd == "methods":
        out = list_crux_evolve_methods(args.name)
    elif args.cmd == "island-plan":
        out = generate_island_plan(args.islands, stagnation_generations=args.stagnation, generation=args.generation)
    elif args.cmd == "select-survivors":
        out = run_diversity_survivor_selection(Path(args.candidates), args.count, args.novelty_ratio)
    elif args.cmd == "operator-prompt":
        pjson = Path(args.parents_json) if args.parents_json else None
        out = build_evolution_operator_prompt(args.operator, args.task, pjson, args.reflection)
    elif args.cmd == "advise-blocks":
        out = advise_evolvable_blocks(Path(args.file))
    elif args.cmd == "tune-params":
        out = tune_candidate_parameters(
            Path(args.candidate),
            eval_cmd=args.eval_cmd,
            symbol=args.symbol,
            max_evaluations=args.max_evals,
            apply_patch=args.apply,
        )
    elif args.cmd == "sync-views":
        out = sync_evolution_state_to_crux_views(Path(args.state_file), Path(args.run_dir))
    else:
        return 1

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        failure = {"engine": "Crux Evolve", "status": "failed", "error": rebrand_to_crux_evolve(str(exc))}
        if sys.argv[1:2] == ["evaluate-candidate"]:
            failure.update(engine="Crux Evolve · Evaluator", mode="ssh_remote" if "--ssh-host" in sys.argv else "local_worktree")
        print(json.dumps(failure))
        raise SystemExit(1)
