"""Tool descriptions as the model sees them: the code schema with the catalog's versions applied."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

from .contract import REASON_PROMPT_SET_UNBOUND, PromptTemplateUnavailableError
from .prompt_set import SOURCE_SEED, PromptSet, bound_prompt_set
from .registry import static_prompt_key_registry
from .tool_catalog import iter_param_descriptions, tool_description_key, tool_param_key

CITATION_RULE_KEY = "evidence.citation_rule"
# Read from the seed modules only: the tool definitions import this at module load.
CITATION_RULE = static_prompt_key_registry()[CITATION_RULE_KEY].seed

#: Tools whose description ends with the citation rule.
CITATION_RULE_TOOLS = frozenset({"knowledge_search", "knowledge_changes"})


def catalog_override(prompt_set: PromptSet, key: str) -> str | None:
    if key not in prompt_set.prompts and key not in prompt_set.refusals:
        return None
    if prompt_set.resolved(key).source == SOURCE_SEED:
        return None
    return prompt_set.render(key)


def resolved_tool_description(prompt_set: PromptSet, tool_name: str, code_description: str) -> str:
    text = catalog_override(prompt_set, tool_description_key(tool_name)) or code_description
    if tool_name in CITATION_RULE_TOOLS:
        rule = prompt_set.render(CITATION_RULE_KEY)
        if rule != CITATION_RULE and text.endswith(CITATION_RULE):
            text = text[: -len(CITATION_RULE)] + rule
    return text


def apply_tool_descriptions(prompt_set: PromptSet, tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function") if isinstance(tool, dict) else None
    if not isinstance(function, dict):
        return tool
    name = str(function.get("name") or "")
    if not name:
        return tool
    updated = dict(function)
    description = function.get("description")
    if isinstance(description, str):
        updated["description"] = resolved_tool_description(prompt_set, name, description)
    overrides = {
        path: text
        for path, _prop in iter_param_descriptions(function.get("parameters"))
        if (text := catalog_override(prompt_set, tool_param_key(name, path))) is not None
    }
    if overrides:
        parameters = copy.deepcopy(function["parameters"])
        targets = dict(iter_param_descriptions(parameters))
        for path, text in overrides.items():
            targets[path]["description"] = text
        updated["parameters"] = parameters
    if updated == function:
        return tool
    return {**tool, "function": updated}


def _bound() -> PromptSet:
    prompt_set = bound_prompt_set()
    if prompt_set is None:
        raise PromptTemplateUnavailableError("tool", REASON_PROMPT_SET_UNBOUND)
    return prompt_set


def catalog_tool_descriptions(tools: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return tools if tools is None else list(tools)
    prompt_set = _bound()
    return [apply_tool_descriptions(prompt_set, tool) for tool in tools]


def catalog_tool_description(tool_name: str, code_description: str) -> str:
    return resolved_tool_description(_bound(), tool_name, code_description)


__all__ = [
    "CITATION_RULE",
    "CITATION_RULE_KEY",
    "CITATION_RULE_TOOLS",
    "apply_tool_descriptions",
    "catalog_override",
    "catalog_tool_description",
    "catalog_tool_descriptions",
    "resolved_tool_description",
]
