"""Debug entry point for TSP benchmark pipeline.

Usage:
    Run from any directory — the script auto-chdir to the task folder
    so that relative paths in the YAML resolve correctly.

This runs the full CruxEvolve pipeline and requires LLM credentials:
- LLM_BASE_URL
- LLM_API_KEY
- LLM_MODEL
"""

import asyncio
import os
from pathlib import Path

from crux_evolve import CruxEvolve

# Ensure CWD is the task directory so YAML relative paths resolve correctly
TASK_DIR = Path(__file__).resolve().parent
os.chdir(TASK_DIR)


async def main():
    """Run the full CruxEvolve pipeline for the TSP task."""
    crux_evolve = CruxEvolve("config.yaml")
    result = await crux_evolve.run()

    if result.best_individual:
        print(f"\n[OK] Best score: {result.best_individual.score:.4f}")
        print(f"[OK] Best algorithm: {result.best_individual.name}")
    else:
        print("\n[FAIL] No valid individual found.")


if __name__ == "__main__":
    asyncio.run(main())
