"""Config builder that accumulates stage data into a valid AppConfig.

Handles the mapping from conversation stages to AppConfig fields,
incremental validation, and YAML serialization.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import ValidationError

from crux_evolve.config.schema import AppConfig

# Mapping from stage name to how its collected_data merges into AppConfig dict.
# None means merge at top level; a string means nest under that key.
_STAGE_FIELD_MAP: dict[str, str | None] = {
    "project_basics": None,  # top-level fields: project_name, background, base_dir
    "version_control": None,  # top-level key: version_control
    "provider_setup": "providers",
    "evaluator_setup": "evaluator",
    "evolution_setup": "evolution",
    "coder_setup": "coder",
    "planner_setup": "planner",
    "memory_setup": "memory",
    "logging_setup": "logging",
    "workspace_setup": "workspace",
    "repo_analyzer_setup": "repo_analyzer",
}


class ConfigBuilder:
    """Accumulates configuration data from conversation stages.

    Each stage contributes a dict of config values. The builder merges
    them into a single dict that can be validated as an AppConfig.
    """

    def __init__(self, template_data: dict[str, Any] | None = None) -> None:
        """Initialize the builder.

        Args:
            template_data: Optional starting config dict from a template.
        """
        self._data: dict[str, Any] = copy.deepcopy(template_data) if template_data else {}

    @property
    def data(self) -> dict[str, Any]:
        """Return a copy of the current accumulated data."""
        return copy.deepcopy(self._data)

    def set_stage_data(self, stage_name: str, data: dict[str, Any]) -> None:
        """Merge data from a completed stage.

        Args:
            stage_name: The stage that produced this data.
            data: Config fragment to merge.
        """
        target = _STAGE_FIELD_MAP.get(stage_name)

        if target is None:
            # Merge directly at top level
            self._data.update(data)
        else:
            # Nest under the target key
            self._data[target] = data

    def build(self) -> AppConfig:
        """Build and validate the final AppConfig.

        Returns:
            Validated AppConfig instance.

        Raises:
            ValidationError: If the accumulated data is invalid.
        """
        return AppConfig.from_dict(self._data)

    def build_partial(self) -> tuple[dict[str, Any], list[str]]:
        """Attempt to build, returning validation errors if any.

        Returns:
            Tuple of (current data dict, list of error messages).
            If no errors, the list is empty.
        """
        errors: list[str] = []
        try:
            AppConfig.from_dict(self._data)
        except ValidationError as e:
            for err in e.errors():
                loc = " -> ".join(str(x) for x in err["loc"])
                errors.append(f"{loc}: {err['msg']}")
        except Exception as e:
            errors.append(str(e))

        return copy.deepcopy(self._data), errors

    def to_yaml(self) -> str:
        """Serialize current data to YAML string.

        Returns:
            YAML-formatted string.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required for YAML output. Install with: pip install pyyaml"
            ) from None

        result: str = yaml.dump(
            self._data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        return result

    def save_yaml(self, path: str) -> None:
        """Write YAML config file to disk.

        Args:
            path: Output file path.
        """
        from pathlib import Path

        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.to_yaml(), encoding="utf-8")
