"""Export the best individual(s) of a run into a stable ``best/`` directory.

After an evolution run finishes, the best individual is persisted in three
places: as a Pydantic object inside :class:`EvolutionResult` (in-memory
only), as a serialized record inside the latest checkpoint JSON, and as
the working tree of a temporary git worktree under ``worktrees/``. None
of these are easy for a frontend to consume directly: the in-memory copy
is gone once the CLI exits, the checkpoint requires JSON parsing and
schema knowledge, and the worktree is a git worktree (not a plain copy)
whose name has to be looked up first.

This module copies the best worktree into ``{run_dir}/best/code/``, writes
a self-describing ``metadata.json`` with score / generation / lineage
data, and a one-line ``summary.txt`` for humans. For multi-objective
runs (MEoH), every entry in the elitist archive is exported under
``{run_dir}/best/pareto/<index>/``.

The exporter is best-effort: failures are logged and swallowed so a
late-run snapshot bug never blocks the user from seeing their results.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from crux_evolve.orchestrator.base import EvolutionResult
    from crux_evolve.planner.base import Algorithm


def export_best(result: EvolutionResult, best_dir: Path) -> None:
    """Export the best individual (and Pareto archive, if any) to ``best_dir``.

    Behaviour:
    - Single-objective runs (``best_individual`` set, no archive of length
      > 1): write ``best_dir/code/`` + ``metadata.json`` + ``summary.txt``.
    - Multi-objective runs (MEoH-style ``elitist_archive`` with multiple
      entries): write ``best_dir/pareto/<idx>/code/`` + ``metadata.json``
      per archive member, plus a top-level ``summary.txt`` listing them.
    - Single-best is also written when an archive exists, so the frontend
      always has a canonical "the one block to look at" location.

    Args:
        result: The :class:`EvolutionResult` returned by ``orchestrator.run()``.
        best_dir: Absolute path of the run's ``best/`` directory.
            ``CruxEvolve.run()`` passes ``state_tracker.best_dir``.
    """
    best_dir.mkdir(parents=True, exist_ok=True)

    archive = _extract_elitist_archive(result)

    try:
        if result.best_individual is not None:
            _export_one(result.best_individual, best_dir, role="best")
        if len(archive) > 1:
            pareto_dir = best_dir / "pareto"
            pareto_dir.mkdir(exist_ok=True)
            for idx, member in enumerate(archive):
                _export_one(
                    member,
                    pareto_dir / str(idx),
                    role=f"pareto[{idx}]",
                )
            _write_summary(
                best_dir / "summary.txt",
                _format_summary(result, archive=archive),
            )
        elif result.best_individual is not None:
            _write_summary(
                best_dir / "summary.txt",
                _format_summary(result, archive=None),
            )
    except Exception as exc:  # noqa: BLE001 - never block the user on export
        logger.warning("Failed to export best individual: {}", exc)


def _extract_elitist_archive(result: EvolutionResult) -> list[Algorithm]:
    """Return the multi-objective elitist archive, if present.

    MEoH stores its non-dominated front in
    ``result.metadata['elitist_archive']`` and also in
    ``result.final_population`` (per [meoh.py:137-157]). Single-objective
    orchestrators (Island GA, DyCA) leave both empty.
    """
    archive: list = list(result.final_population or [])
    if archive:
        return archive
    raw = (result.metadata or {}).get("elitist_archive")
    if isinstance(raw, list):
        return raw
    return []


def _export_one(individual: Algorithm, dest: Path, *, role: str) -> None:
    """Copy ``individual``'s worktree into ``dest/code/`` and write metadata.

    The worktree is a real git worktree on disk; we copy its tracked
    contents into a plain directory so the user does not need git tooling
    to read the result. ``.git`` and Python caches are filtered out.

    Args:
        individual: The :class:`Algorithm` whose code we want to snapshot.
        dest: Target directory; will be created.
        role: Human-readable label printed if copying fails (e.g.
            ``"best"`` or ``"pareto[3]"``).
    """
    dest.mkdir(parents=True, exist_ok=True)
    code_dir = dest / "code"

    if individual.worktree is not None and individual.worktree.path:
        src = Path(individual.worktree.path)
        if src.exists() and src.is_dir():
            if code_dir.exists():
                shutil.rmtree(code_dir)
            shutil.copytree(
                src,
                code_dir,
                ignore=shutil.ignore_patterns(
                    ".git", "__pycache__", "*.pyc", ".pytest_cache"
                ),
            )
        else:
            logger.warning(
                "Worktree path for {} does not exist on disk: {}", role, src
            )
            code_dir.mkdir(exist_ok=True)
    else:
        # No worktree (e.g. coder failed to materialize one). Fall back to
        # whatever code artifacts the algorithm carries directly.
        code_dir.mkdir(exist_ok=True)
        for artifact in individual.code_artifacts:
            target = code_dir / artifact.file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(artifact.content, encoding="utf-8")

    metadata_path = dest / "metadata.json"
    metadata_path.write_text(
        json.dumps(_metadata_for(individual), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _metadata_for(individual: Algorithm) -> dict[str, Any]:
    """Return a JSON-ready snapshot of every interesting field on ``Algorithm``."""
    evaluation: dict[str, Any] | None = None
    if individual.evaluation is not None:
        ev = individual.evaluation
        evaluation = {
            "score": ev.score,
            "metrics": dict(ev.metrics or {}),
            "evaluation_time_ms": getattr(ev, "evaluation_time_ms", None),
            "error": ev.error,
        }
    worktree: dict[str, Any] | None = None
    if individual.worktree is not None:
        worktree = {
            "name": individual.worktree.name,
            "path": individual.worktree.path,
            "branch": individual.worktree.branch,
            "commit_hash": individual.worktree.commit_hash,
        }
    return {
        "id": individual.id,
        "name": individual.name,
        "description": individual.description,
        "key_innovations": list(individual.key_innovations or []),
        "design_notes": individual.design_notes,
        "domain": individual.domain,
        "insight_type": getattr(individual.insight_type, "value", str(individual.insight_type)),
        "generation": individual.generation,
        "island_id": individual.island_id,
        "parent_ids": list(individual.parent_ids or []),
        "tags": list(individual.tags or []),
        "score": individual.score,
        "metrics": dict(individual.metrics or {}),
        "evaluation": evaluation,
        "worktree": worktree,
        "lines_added": individual.lines_added,
        "lines_removed": individual.lines_removed,
        "lines_modified": individual.lines_modified,
        "custom_metadata": dict(individual.custom_metadata or {}),
        "created_at": individual.created_at,
        "updated_at": individual.updated_at,
    }


def _format_summary(
    result: EvolutionResult,
    *,
    archive: list[Algorithm] | None,
) -> str:
    """Render a small human-readable summary for ``best/summary.txt``."""
    best = result.best_individual
    lines = ["CruxEvolve run summary", "==================="]
    if best is not None:
        lines.append(f"Best score:       {best.score:.6g}")
        lines.append(f"Best generation:  {best.generation}")
        if best.island_id is not None:
            lines.append(f"Best island_id:   {best.island_id}")
        lines.append(f"Best id:          {best.id}")
        if best.worktree is not None:
            lines.append(f"Source worktree:  {best.worktree.name}")
    lines.append(f"Final generation: {result.final_generation}")
    lines.append(f"Total evaluations: {result.total_evaluations}")
    lines.append(f"Duration (s):     {result.duration_seconds:.2f}")
    if archive is not None:
        lines.append("")
        lines.append(f"Pareto archive ({len(archive)} members):")
        for idx, member in enumerate(archive):
            score = getattr(member, "score", float("nan"))
            metrics = getattr(member, "metrics", {}) or {}
            metric_str = ", ".join(
                f"{k}={v:.4g}" for k, v in metrics.items()
            ) if metrics else ""
            lines.append(
                f"  [{idx}] id={member.id} score={score:.6g}"
                + (f"  metrics=({metric_str})" if metric_str else "")
            )
    return "\n".join(lines) + "\n"


def _write_summary(path: Path, content: str) -> None:
    """Write ``summary.txt`` (small helper isolated for testability)."""
    path.write_text(content, encoding="utf-8")
