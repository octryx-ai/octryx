"""The Agent Designer document vocabulary: node types, limits, refusal issues and the translated definition."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

DOCUMENT_KIND = "octryx.agent_designer.document"
DOCUMENT_VERSION = 1

INPUT_NODE = "InputNode"
OUTPUT_NODE = "OutputNode"
LLM_NODE = "SingleLLMCallNode"
AGENT_NODE = "AgentNode"
STEP_NODE_TYPES = frozenset({LLM_NODE, AGENT_NODE})

INPUT_NODE_ID = "octryx-input"
OUTPUT_NODE_ID = "octryx-output"
DESIGNER_CONFIG_KEY = "designer"

_MAX_NODES = 200
_MAX_NAME = 200
_MAX_TEXT = 100_000
_MAX_DOCUMENT_BYTES = 2_000_000
_MAX_DESIGNER_SETTINGS_BYTES = 20_000
_X_START, _X_GAP, _Y = 80.0, 360.0, 200.0
# Designer-only node settings that round-trip through ``step_config["designer"]``.
_ROUND_TRIP_CONFIG_KEYS = (
    "user_message",
    "few_shot_examples",
    "llm_info",
    "enable_thinking",
    "thinking_budget_tokens",
    "enable_message_history",
    "message_history_variable",
    "max_iterations",
)


@dataclass(frozen=True, slots=True)
class DesignerIssue:
    code: str
    node_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "node_ids": list(self.node_ids)}


class DesignerDocumentError(ValueError):
    def __init__(self, issues: list[DesignerIssue]) -> None:
        super().__init__("designer document refused")
        self.issues = issues


@dataclass(frozen=True, slots=True)
class DesignerStep:
    step_id: str
    name: str
    instructions: str
    designer_config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DesignerDefinition:
    name: str
    description: str
    steps: list[DesignerStep] = field(default_factory=list)


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _json_size(value: Any) -> int:
    return len(json.dumps(value, default=str, ensure_ascii=False).encode("utf-8"))


def _coordinates(node: dict[str, Any], index: int) -> dict[str, float]:
    raw = node.get("coordinates") if isinstance(node.get("coordinates"), dict) else {}
    try:
        return {"x": float(raw.get("x")), "y": float(raw.get("y"))}
    except (TypeError, ValueError):
        return {"x": _X_START + index * _X_GAP, "y": _Y}


def _config(node: dict[str, Any]) -> dict[str, Any]:
    return node.get("config") if isinstance(node.get("config"), dict) else {}


def _designer_settings(config: dict[str, Any]) -> dict[str, Any]:
    return {key: config[key] for key in _ROUND_TRIP_CONFIG_KEYS if key in config}
