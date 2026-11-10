"""Monitor implementations for evolution progress tracking.

This module provides different monitor implementations:
- ConsoleMonitor: Simple console-based logging with rich output
- PrometheusMonitor: Prometheus metrics export (optional)
- TensorBoardMonitor: TensorBoard logging (optional)
"""

from .console import ConsoleMonitor

__all__ = [
    "ConsoleMonitor",
]
