"""CruxEvolve: LLM for Algorithm Design.

A platform that uses Large Language Models with evolutionary algorithms
to automatically design and improve algorithms.
"""

__version__ = "1.1.0"

from crux_evolve.crux_evolve import CruxEvolve
from crux_evolve.utils.registry import Registrable, Registry

__all__ = [
    "__version__",
    "Registry",
    "Registrable",
    "CruxEvolve",
]
