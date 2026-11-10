"""Renderer registry for deferred visualization of behavior data.

Provides a registry-based system for converting raw evaluation data
into rendered images on demand. This supports the "raw data" storage
strategy where evaluators return structured data instead of pre-rendered
images, allowing flexible frontend visualization.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from crux_evolve.evaluator.behavior import BehaviorVisualization
from crux_evolve.utils.registry import Registrable

logger = logging.getLogger(__name__)


class BaseRenderer(Registrable, ABC, registry_name="renderer"):
    """Abstract renderer that converts raw data to a base64 image.

    Implementations handle domain-specific rendering (e.g., TSP tour
    plots, trajectory visualizations). Register renderers using the
    ``@BaseRenderer.register("name")`` decorator.
    """

    @abstractmethod
    def render(self, raw_data: dict[str, Any], **kwargs: Any) -> str:
        """Render raw data to a base64-encoded image string.

        Args:
            raw_data: Domain-specific data to render.
            **kwargs: Additional rendering options (size, format, etc.).

        Returns:
            Base64-encoded image string (PNG or JPEG).
        """
        ...


def render_visualization(viz: BehaviorVisualization) -> str | None:
    """Lazily render a BehaviorVisualization to a base64 image.

    If the visualization already has a rendered image (``data_base64``),
    returns it directly. Otherwise, looks up the named renderer from the
    registry and uses it to convert ``raw_data`` to an image. The result
    is cached in ``viz.data_base64`` for subsequent calls.

    If the renderer is not registered (e.g. the evaluator module has not
    been imported), returns ``None`` with a warning so that the caller
    can fall back to re-evaluation.

    Args:
        viz: Visualization to render.

    Returns:
        Base64-encoded image string, or ``None`` if rendering is not
        possible (no data, no renderer, or renderer not registered).
    """
    if viz.data_base64 is not None:
        return viz.data_base64

    if viz.raw_data is None or viz.renderer is None:
        return None

    try:
        renderer = BaseRenderer.create(viz.renderer)
    except KeyError:
        logger.warning(
            "Renderer '%s' is not registered. Import the evaluator module "
            "that defines it (e.g. pass renderer_modules to "
            "VisualizationAPI), or the image will be produced via "
            "re-evaluation fallback.",
            viz.renderer,
        )
        return None

    rendered = renderer.render(viz.raw_data)
    viz.data_base64 = rendered
    return rendered
