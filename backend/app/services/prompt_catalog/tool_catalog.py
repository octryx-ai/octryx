"""Built-in tool descriptions as prompt catalog keys, seeded by the code tool definitions."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from .contract import RISK_HIGH, RISK_STANDARD, PromptKeySpec

TOOL_AREA = "tool"
ARRAY_ITEM_SEGMENT = "_item"


def tool_description_key(tool_name: str) -> str:
    return f"tool.{tool_name}.description"


def tool_param_key(tool_name: str, path: tuple[str, ...]) -> str:
    return f"tool.{tool_name}.param." + ".".join(path)


def iter_param_descriptions(
    schema: Mapping[str, Any] | None, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    if not isinstance(schema, Mapping):
        return
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            continue
        prop_path = (*path, str(name))
        if isinstance(prop.get("description"), str):
            yield prop_path, prop
        yield from iter_param_descriptions(prop, prop_path)
        items = prop.get("items")
        if isinstance(items, Mapping):
            yield from iter_param_descriptions(items, (*prop_path, ARRAY_ITEM_SEGMENT))


def tool_description_specs() -> tuple[PromptKeySpec, ...]:
    from ...tools.definitions import get_all_definitions

    specs: list[PromptKeySpec] = []
    for name, definition in sorted(get_all_definitions().items()):
        function = definition.get("function") if isinstance(definition, dict) else None
        if not isinstance(function, dict):
            continue
        description = function.get("description")
        if isinstance(description, str) and description:
            specs.append(
                PromptKeySpec(
                    key=tool_description_key(name),
                    area=TOOL_AREA,
                    title=f"{name}: description",
                    seed=description,
                    risk=RISK_HIGH,
                    description="Description of the built-in tool as the model sees it in the tool schema.",
                    literal=True,
                )
            )
        for path, prop in iter_param_descriptions(function.get("parameters")):
            if not prop["description"]:
                continue
            specs.append(
                PromptKeySpec(
                    key=tool_param_key(name, path),
                    area=TOOL_AREA,
                    title=f"{name}: parameter {'.'.join(path)}",
                    seed=prop["description"],
                    risk=RISK_STANDARD,
                    description="Description of one parameter of the built-in tool schema.",
                    literal=True,
                )
            )
    return tuple(specs)


__all__ = [
    "ARRAY_ITEM_SEGMENT",
    "TOOL_AREA",
    "iter_param_descriptions",
    "tool_description_key",
    "tool_description_specs",
    "tool_param_key",
]
