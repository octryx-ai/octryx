"""A test-bench question checked: "may <user> do <action> on <resource> in <Workspace>?" (``test_bench.ask``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .schema import (
    ACTION_CALL_MODEL,
    ACTION_CALL_TOOL,
    ACTION_READ_CONNECTOR,
    ACTION_READ_PATH,
    ACTION_RUN_COMMAND,
    ACTION_RUN_ON_DEVICE,
    ACTION_USE_REMOTE_EMBEDDINGS,
    ACTION_USE_RERANKER,
    ACTION_WRITE_CONNECTOR,
    ACTION_WRITE_PATH,
    ACTIONS,
)

TOOL_ACTIONS = frozenset({ACTION_CALL_TOOL, ACTION_READ_CONNECTOR, ACTION_WRITE_CONNECTOR})
PATH_ACTIONS = frozenset({ACTION_READ_PATH, ACTION_WRITE_PATH})
MAX_TEXT = 4000

ERROR_INVALID = "policy_bench_request_invalid"
ERROR_WORKSPACE = "policy_bench_workspace_not_found"
ERROR_NO_DRAFT = "policy_bench_no_draft"


class BenchError(ValueError):
    def __init__(self, code: str, status: int = 422, path: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.path = path


@dataclass(frozen=True, slots=True)
class BenchQuestion:
    workspace_id: str
    user_id: str | None
    action: str
    resource: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"workspace_id": self.workspace_id, "user_id": self.user_id, "action": self.action,
                "resource": dict(self.resource)}


def _text(value: Any, path: str, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > MAX_TEXT or (required and not value.strip()):
        raise BenchError(ERROR_INVALID, path=path)
    return value


def parse_question(raw: Any) -> BenchQuestion:
    if not isinstance(raw, Mapping):
        raise BenchError(ERROR_INVALID, path="")
    action = raw.get("action")
    if action not in ACTIONS:
        raise BenchError(ERROR_INVALID, path="action")
    workspace_id = _text(raw.get("workspace_id"), "workspace_id")[:64]
    user_id = raw.get("user_id")
    if user_id is not None and (not isinstance(user_id, str) or len(user_id) > 64):
        raise BenchError(ERROR_INVALID, path="user_id")
    resource = raw.get("resource") or {}
    if not isinstance(resource, Mapping):
        raise BenchError(ERROR_INVALID, path="resource")
    checked: dict[str, Any] = {}
    if action == ACTION_CALL_MODEL:
        checked["alias"] = _text(resource.get("alias", ""), "resource.alias", required=False)
    elif action in (ACTION_USE_RERANKER, ACTION_USE_REMOTE_EMBEDDINGS):
        checked["data_policy_class"] = _text(resource.get("data_policy_class"), "resource.data_policy_class",
                                             required=False)
    elif action in TOOL_ACTIONS:
        checked["tool"] = _text(resource.get("tool"), "resource.tool")
        params = resource.get("params")
        if params is not None and not isinstance(params, Mapping):
            raise BenchError(ERROR_INVALID, path="resource.params")
        if params is not None:
            checked["params"] = dict(params)
        connections = resource.get("connections")  # named-connection ids the call would run on
        if connections is not None:
            if not isinstance(connections, list) or not all(isinstance(item, str) for item in connections):
                raise BenchError(ERROR_INVALID, path="resource.connections")
            checked["connections"] = [item.strip() for item in connections if item.strip()][:20]
    elif action == ACTION_RUN_COMMAND:
        checked["command"] = _text(resource.get("command"), "resource.command")
    elif action == ACTION_RUN_ON_DEVICE:
        checked["profile"] = _text(resource.get("profile") or "governed", "resource.profile")
        checked["folder_allowlisted"] = resource.get("folder_allowlisted", True) is not False
    elif action in PATH_ACTIONS:
        checked["path"] = _text(resource.get("path"), "resource.path")
        checked["tool"] = _text(resource.get("tool") or ("Edit" if action == ACTION_WRITE_PATH else "Read"),
                                "resource.tool")
    return BenchQuestion(workspace_id, user_id or None, action, checked)


__all__ = ["BenchError", "BenchQuestion", "parse_question"]
