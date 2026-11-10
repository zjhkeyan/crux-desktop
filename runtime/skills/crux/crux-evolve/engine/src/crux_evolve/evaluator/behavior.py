"""Behavior data models for multimodal algorithm evaluation.

This module defines the data structures for capturing, storing, and
accessing algorithm behavior data (visualizations, observations) from
evaluation. Supports three storage strategies:

1. Rendered figure: evaluator returns pre-rendered base64 image
2. Raw data: evaluator returns data for deferred rendering
3. Nothing stored: visualization requires re-running the algorithm
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class BehaviorVisualization(BaseModel):
    """A single visualization artifact from algorithm evaluation.

    Represents one visual snapshot of algorithm behavior (e.g., a TSP tour
    plot, a car trajectory, a lander descent path). Supports both
    pre-rendered images and raw data for deferred rendering.

    Attributes:
        label: Human-readable name for this visualization.
        media_type: MIME type of the rendered image.
        data_base64: Pre-rendered image as base64 string (Case 1).
        raw_data: Raw data for deferred rendering (Case 2).
        renderer: Registry name of the renderer to convert raw_data to image.
    """

    label: str
    media_type: str = "image/png"
    data_base64: str | None = None
    raw_data: dict[str, Any] | None = None
    renderer: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def has_rendered_image(self) -> bool:
        """Check if a pre-rendered image is available."""
        return self.data_base64 is not None

    def has_raw_data(self) -> bool:
        """Check if raw data is available for deferred rendering."""
        return self.raw_data is not None and self.renderer is not None

    def is_renderable(self) -> bool:
        """Check if this visualization can produce an image (rendered or raw)."""
        return self.has_rendered_image() or self.has_raw_data()


class BehaviorData(BaseModel):
    """Container for all behavior data from one evaluation instance.

    Groups together text observations and visual artifacts produced
    by evaluating an algorithm on a single problem instance.

    Attributes:
        observation: Text description of algorithm behavior (LLM-readable).
        visualizations: Zero or more visual artifacts.
        instance_id: Identifier of the problem instance that produced this data.
    """

    observation: str = ""
    visualizations: list[BehaviorVisualization] = []
    instance_id: str = ""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def has_images(self) -> bool:
        """Check if any visualization has or can produce a rendered image."""
        return any(v.is_renderable() for v in self.visualizations)

    def get_images_base64(self) -> list[str]:
        """Get all available base64-encoded images, rendering raw data if needed.

        Returns:
            List of base64 image strings from visualizations that have
            pre-rendered data or can be rendered from raw data.
        """
        from crux_evolve.evaluator.renderer import render_visualization

        images = []
        for v in self.visualizations:
            rendered = render_visualization(v)
            if rendered is not None:
                images.append(rendered)
        return images

    def get_raw_data_entries(self) -> list[BehaviorVisualization]:
        """Get visualizations that have raw data for deferred rendering.

        Returns:
            List of BehaviorVisualization instances with raw_data populated.
        """
        return [v for v in self.visualizations if v.has_raw_data()]
