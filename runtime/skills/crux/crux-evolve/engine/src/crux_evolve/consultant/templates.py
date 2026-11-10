"""Built-in configuration templates for the Consultant.

Three configuration levels are available:

- **minimal** — only the fields that must be filled in
- **standard** — common fields (currently same as minimal; customise later)
- **complete** — every available field with descriptions

Templates are bundled as YAML files inside the package (``_templates/``
directory) so they are available even after ``pip install`` from a wheel.
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TemplateInfo:
    """Metadata about a configuration template."""

    name: str
    display_name: str
    description: str
    filename: str


# Only three levels are registered.
_TEMPLATE_REGISTRY: list[TemplateInfo] = [
    TemplateInfo(
        name="minimal",
        display_name="Minimal",
        description="Essential fields only — quickest way to get started",
        filename="minimal.yaml",
    ),
    TemplateInfo(
        name="standard",
        display_name="Standard",
        description="Common configuration fields with sensible defaults",
        filename="standard.yaml",
    ),
    TemplateInfo(
        name="complete",
        display_name="Complete",
        description="All available fields — full control over every setting",
        filename="complete.yaml",
    ),
]


def _read_template_file(filename: str) -> str:
    """Read a bundled template YAML file via importlib.resources.

    Args:
        filename: File name inside ``_templates/``.

    Returns:
        File contents as string.

    Raises:
        FileNotFoundError: If the file is not bundled in the package.
    """
    pkg = importlib.resources.files("crux_evolve.consultant") / "_templates" / filename
    try:
        return pkg.read_text(encoding="utf-8")
    except (FileNotFoundError, TypeError) as exc:
        raise FileNotFoundError(f"Bundled template not found: {filename}") from exc


def list_templates() -> list[TemplateInfo]:
    """List all available templates.

    Returns:
        List of TemplateInfo for templates whose YAML files exist in the package.
    """
    available: list[TemplateInfo] = []
    for tmpl in _TEMPLATE_REGISTRY:
        try:
            _read_template_file(tmpl.filename)
            available.append(tmpl)
        except FileNotFoundError:
            continue
    return available


def load_template(name: str) -> dict[str, Any]:
    """Load a template's YAML config as a dict.

    Args:
        name: Template name (``"minimal"``, ``"standard"``, or ``"complete"``).

    Returns:
        Configuration dict parsed from the YAML file.

    Raises:
        ValueError: If template name is not found.
        FileNotFoundError: If the YAML file is not bundled.
    """
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "PyYAML is required for template loading. Install with: pip install pyyaml"
        ) from None

    tmpl = _get_registry_entry(name)
    text = _read_template_file(tmpl.filename)

    # Load without env var expansion (consultant will fill in real values)
    data: dict[str, Any] = yaml.safe_load(text)
    return data


def get_template_info(name: str) -> TemplateInfo:
    """Get template metadata by name.

    Args:
        name: Template name.

    Returns:
        TemplateInfo for the template.

    Raises:
        ValueError: If template name is not found.
    """
    return _get_registry_entry(name)


def _get_registry_entry(name: str) -> TemplateInfo:
    """Look up a template by name in the registry.

    Args:
        name: Template name.

    Returns:
        Matching TemplateInfo.

    Raises:
        ValueError: If not found.
    """
    for t in _TEMPLATE_REGISTRY:
        if t.name == name:
            return t
    raise ValueError(
        f"Unknown template: {name}. "
        f"Available: {[t.name for t in _TEMPLATE_REGISTRY]}"
    )
