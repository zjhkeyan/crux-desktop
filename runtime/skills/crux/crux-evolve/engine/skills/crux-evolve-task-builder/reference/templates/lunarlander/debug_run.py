"""Debug runner for LunarLander task package.

Run this script to test the complete CruxEvolve pipeline on the LunarLander task.
"""

import asyncio
import os
from pathlib import Path

from crux_evolve import CruxEvolve

# Set working directory to task root
TASK_DIR = Path(__file__).resolve().parent
os.chdir(TASK_DIR)


async def main():
    """Run the CruxEvolve pipeline with the LunarLander configuration."""
    crux_evolve = CruxEvolve("config.yaml")
    result = await crux_evolve.run()
    print(f"Pipeline completed. Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
