"""TaskWriter: write a validated TaskBlueprint to disk as a complete application directory."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from crux_evolve.builder.blueprint import TaskBlueprint


def write_task_directory(blueprint: TaskBlueprint, output_dir: str | Path) -> Path:
    """Write a complete CruxEvolve application directory from a TaskBlueprint.

    Args:
        blueprint: Validated TaskBlueprint with all artifacts.
        output_dir: Parent directory where the project folder will be created.

    Returns:
        Path to the created application directory.
    """
    output_dir = Path(output_dir)
    task_dir = output_dir / blueprint.project_name
    task_dir.mkdir(parents=True, exist_ok=True)

    # Write config
    _write_file(task_dir / "config.yaml", blueprint.config_yaml)

    # Write evaluator
    _write_file(task_dir / blueprint.evaluator_file_name, blueprint.evaluator_code)

    # Write algorithm
    algo_dir = task_dir / blueprint.algorithm_dir_name
    algo_dir.mkdir(parents=True, exist_ok=True)
    _write_file(algo_dir / blueprint.algorithm_file_name, blueprint.algorithm_code)

    # Write debug runner
    _write_file(task_dir / "debug_run.py", blueprint.debug_run_code)

    # Write test_evaluator
    if blueprint.test_evaluator_code:
        _write_file(task_dir / "test_evaluator.py", blueprint.test_evaluator_code)

    # Write requirements.txt (LLM-suggested third-party deps)
    if blueprint.requirements_txt.strip():
        _write_file(task_dir / "requirements.txt", blueprint.requirements_txt)

    # Write dataset files
    if blueprint.dataset_files:
        for rel_path, content in blueprint.dataset_files.items():
            data_file = task_dir / rel_path
            data_file.parent.mkdir(parents=True, exist_ok=True)
            _write_file(data_file, content)

    # Save blueprint metadata
    blueprint.save(task_dir)

    logger.info("Task directory written to: {}", task_dir)
    return task_dir


def _write_file(path: Path, content: str) -> None:
    """Write content to a file, ensuring parent directory exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.debug("Wrote {}", path)
