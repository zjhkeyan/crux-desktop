"""Visualization API for frontend access to algorithm behavior data.

Provides a high-level interface for web frontends and CLI tools to
query, render, and display algorithm behavior visualizations. Supports
all three behavior storage strategies: pre-rendered images, raw data
with deferred rendering, and re-running algorithms for fresh output.

Supports both in-memory population access (live during evolution) and
disk-based retrieval from saved JSON files (post-run or across restarts).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from crux_evolve.evaluator.behavior import BehaviorData, BehaviorVisualization
from crux_evolve.evaluator.renderer import render_visualization
from crux_evolve.orchestrator.embedding_utils import (
    aggregate_embedding_algorithm_nodes,
    generate_algorithm_evaluation_trace_map,
    get_algorithm_evaluation_config,
)
from crux_evolve.planner.base import Algorithm


class VisualizationAPI:
    """API for frontend access to algorithm behavior data.

    Wraps a population of algorithms (typically from the orchestrator)
    and provides convenient methods for querying behavior data,
    rendering images, and building dashboard summaries.

    Supports two retrieval modes:
    - **In-memory**: via ``get_algorithms`` callable (live during evolution)
    - **Disk-based**: via ``generated_dir`` path (post-run retrieval by ID)

    Args:
        get_algorithms: Callable or list that provides the current
            population of algorithms to query.
        generated_dir: Optional path to the directory where
            ``Algorithm.write()`` saved JSON + PNG files. Enables
            disk-based retrieval by algorithm ID.
        evaluator_script: Optional path to the evaluator Python script
            for re-running evaluations (scenario 3).
        dataset_dir: Optional path to the dataset directory for
            discovering instance files when behavior_data is empty.
        embedding_dir: Optional path to the directory where algorithm
            embeddings are stored. When set, enables HTML evolution trajectory map generation and automatic browser opening.

    """

    def __init__(
            self,
            get_algorithms: Any = None,
            generated_dir: Path | None = None,
            evaluator_script: Path | None = None,
            dataset_dir: Path | None = None,
            embedding_dir: Path | None = None,
            project_root: Path | None = None,
            renderer_modules: list[str | Path] | None = None,
    ):
        """Initialize the VisualizationAPI.

        Args:
            get_algorithms: A callable that returns ``list[Algorithm]``
                (e.g., ``orchestrator._get_global_population``), or a
                static list. If ``None``, methods will return empty results
                unless ``generated_dir`` is set for disk-based retrieval.
            generated_dir: Path to the directory containing saved algorithm
                JSON files (from ``Algorithm.write()``). When set, algorithms
                not found in memory will be loaded from disk.
            evaluator_script: Path to the evaluator Python script for
                subprocess-based re-evaluation.
            dataset_dir: Path to the dataset directory containing instance
                JSON files (e.g., ``data/train/``).
            embedding_dir: Optional path to the directory where algorithm
                embeddings are stored.
            project_root: Path to the project root directory containing
                the algorithm code (e.g., the version control local_path
                such as ``policy/`` or ``tsp_algorithm/``).  Used as a
                fallback when the algorithm's worktree has been cleaned up.
            renderer_modules: Optional list of renderer modules to import.
                Each entry can be a dotted module path (e.g.,
                ``"myapp.renderers"``) or a ``Path`` to a .py file.
                Importing these modules triggers their
                ``@BaseRenderer.register()`` decorators, making deferred
                renderers available for ``get_algorithm_image()``.
        """
        self._get_algorithms = get_algorithms
        self._generated_dir = generated_dir
        self._evaluator_script = evaluator_script
        self._dataset_dir = dataset_dir
        self._project_root = project_root
        self._embedding_dir = embedding_dir

        # Auto-import the evaluator script to register any renderers it
        # defines (e.g. @BaseRenderer.register("tsp_tour")).  This makes
        # deferred rendering work without requiring callers to also pass
        # renderer_modules explicitly.
        if evaluator_script is not None:
            self._import_renderer_module(evaluator_script)

        # Import additional renderer modules if specified
        if renderer_modules:
            for mod in renderer_modules:
                self._import_renderer_module(mod)

    @staticmethod
    def _import_renderer_module(mod: str | Path) -> None:
        """Import a renderer module to trigger its @register decorators.

        Args:
            mod: Dotted module path or filesystem Path to a .py file.
        """
        if isinstance(mod, Path) or (
                isinstance(mod, str) and (mod.endswith(".py") or "/" in mod or "\\" in mod)
        ):
            path = Path(mod).resolve()
            if not path.exists():
                logger.warning(f"Renderer module not found: {path}")
                return
            spec = importlib.util.spec_from_file_location(path.stem, str(path))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
        else:
            importlib.import_module(mod)

    def _resolve_algorithms(self) -> list[Algorithm]:
        """Resolve the current algorithm population."""
        if self._get_algorithms is None:
            return []
        if callable(self._get_algorithms):
            result: list[Algorithm] = list(self._get_algorithms())
            return result
        algorithms: list[Algorithm] = list(self._get_algorithms)
        return algorithms

    def _find_algorithm(self, algorithm_id: str) -> Algorithm | None:
        """Find an algorithm by ID (in-memory first, then disk fallback).

        Args:
            algorithm_id: Unique identifier of the algorithm.

        Returns:
            Algorithm instance, or ``None`` if not found.
        """
        # Try in-memory first
        for alg in self._resolve_algorithms():
            if alg.id == algorithm_id:
                return alg

        # Fallback: search on disk
        if self._generated_dir and self._generated_dir.exists():
            for json_file in self._generated_dir.glob("*.json"):
                if algorithm_id in json_file.stem:
                    try:
                        return Algorithm.load(json_file)
                    except Exception:
                        logger.debug(f"Failed to load algorithm from {json_file}")
                        continue

        return None

    # ------------------------------------------------------------------
    # Listing and detail endpoints
    # ------------------------------------------------------------------

    def list_algorithms(
            self,
            island_id: int | None = None,
            generation: int | None = None,
    ) -> list[dict[str, Any]]:
        """List all algorithms with lightweight summary info.

        Scans ``generated_dir`` for JSON files (disk mode) or iterates
        the in-memory population. Returns summary dicts without loading
        image data, suitable for rendering a table/list view.

        Args:
            island_id: Optional filter by island ID.
            generation: Optional filter by generation number.

        Returns:
            List of summary dicts, each containing: ``id``, ``name``,
            ``score``, ``generation``, ``island_id``, ``operator``,
            ``n_images``, ``has_behavior``.
        """
        results: list[dict[str, Any]] = []

        # Prefer disk-based listing (lightweight — parse JSON without loading images)
        if self._generated_dir and self._generated_dir.exists():
            for json_path in sorted(self._generated_dir.glob("*.json")):
                try:
                    with open(json_path, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue

                alg_island = data.get("island_id")
                alg_gen = data.get("generation")
                if island_id is not None and alg_island != island_id:
                    continue
                if generation is not None and alg_gen != generation:
                    continue

                n_images = sum(
                    len(bd.get("visualizations", []))
                    for bd in data.get("behavior_data", [])
                )
                results.append({
                    "id": data.get("id", ""),
                    "name": data.get("name", ""),
                    "score": (data.get("evaluation") or {}).get("score"),
                    "generation": alg_gen,
                    "island_id": alg_island,
                    "operator": (data.get("generation_meta") or {}).get("operator", ""),
                    "n_images": n_images,
                    "has_behavior": len(data.get("behavior_data", [])) > 0,
                })
            return results

        # Fallback: in-memory population
        for alg in self._resolve_algorithms():
            if island_id is not None and alg.island_id != island_id:
                continue
            if generation is not None and alg.generation != generation:
                continue
            results.append({
                "id": alg.id,
                "name": alg.name,
                "score": alg.score,
                "generation": alg.generation,
                "island_id": alg.island_id,
                "operator": alg.generation_meta.operator if alg.generation_meta else "",
                "n_images": sum(len(bd.visualizations) for bd in alg.behavior_data),
                "has_behavior": alg.has_behavior(),
            })
        return results

    def get_algorithm_detail(self, algorithm_id: str) -> dict[str, Any]:
        """Get full detail for one algorithm (metadata + behavior summary).

        Combines algorithm metadata, observation texts, and image
        availability into a single response. Frontend calls this when
        a user clicks on an algorithm row.

        Args:
            algorithm_id: Unique identifier of the algorithm.

        Returns:
            Dict with keys: ``id``, ``name``, ``description``, ``score``,
            ``generation``, ``island_id``, ``operator``, ``parent_ids``,
            ``observations`` (list of text strings), ``images`` (list of
            dicts with ``index``, ``label``, ``available``, ``media_type``).
            Returns ``{"error": "..."}`` if not found.
        """
        alg = self._find_algorithm(algorithm_id)
        if alg is None:
            return {"error": f"Algorithm {algorithm_id} not found"}

        # Collect observation texts
        observations = [bd.observation for bd in alg.behavior_data if bd.observation]

        # Collect image metadata (without actual image data)
        images: list[dict[str, Any]] = []
        idx = 0
        for bd in alg.behavior_data:
            for viz in bd.visualizations:
                images.append({
                    "index": idx,
                    "label": viz.label,
                    "available": viz.has_rendered_image() or viz.has_raw_data(),
                    "media_type": viz.media_type,
                    "instance_id": bd.instance_id,
                })
                idx += 1

        return {
            "id": alg.id,
            "name": alg.name,
            "description": alg.description,
            "score": alg.score,
            "generation": alg.generation,
            "island_id": alg.island_id,
            "operator": alg.generation_meta.operator if alg.generation_meta else "",
            "parent_ids": alg.parent_ids,
            "observations": observations,
            "images": images,
        }

    # ------------------------------------------------------------------
    # Image retrieval
    # ------------------------------------------------------------------

    def get_algorithm_behavior(self, algorithm_id: str) -> dict[str, Any]:
        """Return behavior data for an algorithm.

        Args:
            algorithm_id: Unique identifier of the algorithm.

        Returns:
            Dict with keys ``has_behavior``, ``observations``,
            ``visualizations`` (list of metadata dicts), and
            ``score``.
        """
        alg = self._find_algorithm(algorithm_id)
        if alg is None:
            return {"has_behavior": False, "error": "Algorithm not found"}

        viz_list = []
        for bd in alg.behavior_data:
            for viz in bd.visualizations:
                viz_list.append({
                    "label": viz.label,
                    "media_type": viz.media_type,
                    "has_rendered_image": viz.has_rendered_image(),
                    "has_raw_data": viz.has_raw_data(),
                    "renderer": viz.renderer,
                })

        return {
            "has_behavior": alg.has_behavior(),
            "observations": alg.get_observation_text(),
            "visualizations": viz_list,
            "score": alg.score,
        }

    def get_algorithm_image(
            self, algorithm_id: str, viz_index: int = 0
    ) -> str | None:
        """Return a base64-encoded image for an algorithm's behavior.

        Attempts lazy rendering if the visualization has raw data but
        no pre-rendered image.

        Args:
            algorithm_id: Unique identifier of the algorithm.
            viz_index: Index of the visualization to retrieve.

        Returns:
            Base64 image string, or ``None`` if not available.
        """
        alg = self._find_algorithm(algorithm_id)
        if alg is None:
            return None

        idx = 0
        for bd in alg.behavior_data:
            for viz in bd.visualizations:
                if idx == viz_index:
                    return render_visualization(viz)
                idx += 1
        return None

    def render_from_raw_data(
            self, algorithm_id: str, renderer_name: str
    ) -> str | None:
        """Lazily render a visualization from stored raw data.

        Args:
            algorithm_id: Unique identifier of the algorithm.
            renderer_name: Registry name of the renderer to use.

        Returns:
            Base64 image string, or ``None`` if rendering failed.
        """
        alg = self._find_algorithm(algorithm_id)
        if alg is None:
            return None

        for bd in alg.behavior_data:
            for viz in bd.visualizations:
                if viz.renderer == renderer_name and viz.has_raw_data():
                    return render_visualization(viz)
        return None

    def generate_and_open_trace_map(self, *args, **kwargs) -> str | None:
        """Generate an HTML evolution trajectory map and open it in the browser.

        If an embedding directory is configured, renders the algorithm evaluation
        trace map as an HTML file and automatically launches it using the system's
        default web browser.

        Returns:
            The absolute path to the generated HTML file if successful, otherwise None.
        """
        if self._embedding_dir:
            return generate_algorithm_evaluation_trace_map(self._embedding_dir, *args, **kwargs)
        return None

    def generate_evaluation_trace_echarts_config(self, metrics: list[str] | None = None,
                                                 dark_mode: bool = False) -> str | None:
        """Generate Echarts config for evaluation trace map."""
        if self._embedding_dir:
            if not metrics:
                metrics = ["score"]
            primary_metric = metrics[0]
            node_data = aggregate_embedding_algorithm_nodes(
                self._embedding_dir,
                z_metric_key=primary_metric
            )
            nodes, links = node_data["nodes"], node_data["links"]
            all_options = get_algorithm_evaluation_config(nodes, links, metrics, dark_mode)
            if primary_metric in all_options:
                return json.dumps(all_options[primary_metric], ensure_ascii=False)
        return None

    def get_population_behavior_summary(
            self, island_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Return a summary of behavior data for all algorithms.

        Useful for rendering a dashboard view showing which algorithms
        have behavior data, their scores, and available visualizations.

        Args:
            island_id: Optional island filter. If ``None``, returns
                all algorithms.

        Returns:
            List of summary dicts, one per algorithm.
        """
        summaries = []
        for alg in self._resolve_algorithms():
            if island_id is not None and alg.island_id != island_id:
                continue
            summaries.append({
                "id": alg.id,
                "name": alg.name,
                "score": alg.score,
                "generation": alg.generation,
                "island_id": alg.island_id,
                "has_behavior": alg.has_behavior(),
                "num_visualizations": sum(
                    len(bd.visualizations) for bd in alg.behavior_data
                ),
                "has_observation": bool(alg.get_observation_text()),
            })
        return summaries

    # ------------------------------------------------------------------
    # Re-evaluation (scenario 3)
    # ------------------------------------------------------------------

    def rerun_and_visualize(
            self,
            algorithm_id: str,
            timeout: float = 120.0,
    ) -> list[BehaviorData]:
        """Re-run algorithm evaluation to generate fresh visualizations.

        Loads the algorithm's policy from its worktree, discovers the
        evaluation instances, and spawns the evaluator subprocess for
        each instance to produce fresh behavior data with trajectory
        images.

        Requires ``evaluator_script`` to be set in the constructor.
        If the algorithm has existing ``behavior_data`` with
        ``instance_id`` references, those instances are re-used.
        Otherwise falls back to discovering instances from
        ``dataset_dir``.

        Args:
            algorithm_id: Unique identifier of the algorithm.
            timeout: Maximum seconds per subprocess evaluation.

        Returns:
            List of fresh ``BehaviorData`` objects with visualizations.
            Empty list if re-evaluation is not possible.
        """
        if self._evaluator_script is None:
            logger.warning(
                "rerun_and_visualize requires evaluator_script to be set. "
                "Pass evaluator_script=Path(...) to VisualizationAPI()."
            )
            return []

        alg = self._find_algorithm(algorithm_id)
        if alg is None:
            logger.warning(f"Algorithm {algorithm_id} not found")
            return []

        # Find policy directory
        policy_dir = self._resolve_policy_dir(alg)
        if policy_dir is None:
            logger.warning(
                f"Cannot find project root for algorithm {algorithm_id}. "
                "Set project_root=Path(...) in VisualizationAPI() constructor."
            )
            return []

        # Discover instances to evaluate
        instance_paths = self._resolve_instances(alg)
        if not instance_paths:
            logger.warning(f"No evaluation instances found for {algorithm_id}")
            return []

        # Run evaluator subprocess for each instance
        behavior_list: list[BehaviorData] = []
        for inst_path in instance_paths:
            with open(inst_path, encoding="utf-8") as f:
                instance = json.load(f)

            # Build generic input: instance data + project_root + mode.
            # Each evaluator's _subprocess_main() extracts the fields it
            # needs (e.g. LunarLander reads "policy_dir"/"seed"/"max_steps",
            # TSP reads "project_root"/"nodes").
            input_data = dict(instance)
            input_data["project_root"] = str(policy_dir)
            input_data["policy_dir"] = str(policy_dir)
            input_data["behavior_storage"] = "rendered"

            input_json = json.dumps(input_data)

            try:
                proc = subprocess.run(
                    [sys.executable, str(self._evaluator_script), input_json],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                logger.warning(f"Evaluation timed out for instance {inst_path}")
                continue

            if proc.returncode != 0:
                logger.warning(
                    f"Evaluator failed for {inst_path}: {proc.stderr[:200]}"
                )
                continue

            try:
                result = json.loads(proc.stdout.strip())
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from evaluator: {proc.stdout[:200]}")
                continue

            if "error" in result:
                logger.warning(f"Evaluation error: {result['error']}")
                continue

            image_b64 = result.get("image_base64")
            obs_text = result.get("observation_text", "")

            if image_b64:
                behavior_list.append(BehaviorData(
                    observation=obs_text,
                    visualizations=[
                        BehaviorVisualization(
                            label=result.get("label", "Behavior"),
                            media_type="image/png",
                            data_base64=image_b64,
                        ),
                    ],
                    instance_id=str(inst_path),
                ))

        logger.info(
            f"Re-evaluated {algorithm_id}: {len(behavior_list)} instances"
        )
        return behavior_list

    def _resolve_policy_dir(self, alg: Algorithm) -> Path | None:
        """Find the project_root directory for running the evaluator.

        Searches for the algorithm's code in:
        1. The algorithm's worktree path (if it still exists)
        2. The ``project_root`` fallback (base version-control directory)

        The evaluator's ``evaluate()`` receives ``project_root`` and is
        responsible for finding the entrypoint script within it, so this
        method only needs to return a directory that contains the code.

        Args:
            alg: Algorithm with optional worktree information.

        Returns:
            Path to the project root directory, or ``None`` if not found.
        """
        # 1. Try worktree (may still exist during evolution)
        if alg.worktree is not None:
            worktree_path = Path(alg.worktree.path)
            if worktree_path.exists():
                return worktree_path

        # 2. Fallback to project_root from constructor
        if self._project_root is not None and self._project_root.exists():
            return self._project_root

        return None

    def _resolve_instances(self, alg: Algorithm) -> list[Path]:
        """Discover evaluation instance files for an algorithm.

        First tries ``behavior_data[].instance_id`` references.
        Falls back to scanning ``dataset_dir`` if no references exist.

        Args:
            alg: Algorithm to find instances for.

        Returns:
            List of paths to instance JSON files.
        """
        # Try existing instance references from behavior_data
        instances: list[Path] = []
        for bd in alg.behavior_data:
            if bd.instance_id:
                p = Path(bd.instance_id)
                if p.exists():
                    instances.append(p)

        if instances:
            return instances

        # Fallback: discover from dataset_dir
        if self._dataset_dir and self._dataset_dir.exists():
            return sorted(self._dataset_dir.glob("*.json"))

        return []
