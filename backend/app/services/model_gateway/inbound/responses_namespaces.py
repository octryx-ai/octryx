"""Codex's ``namespace`` tools as plain function tools for any upstream, mapped back transparently.

Codex 0.169 sends a Workspace's MCP tools as one Responses tool of type ``namespace`` (``{"type": "namespace",
"name": "mcp__octryx_knowledge", "tools": [{"type": "function", "name": "workflow_catalog", ...}]}``) and
expects a call as ``function_call`` with ``namespace`` and the inner ``name``. OpenAI's own models know that type;
models behind LiteLLM or llama.cpp do not, and never call those tools (e.g. LFM2.5 behind llama-server).
So the gateway stays model-independent and flattens them for every upstream.

- request (:func:`flatten_request`): every inner tool of a namespace becomes a top-level tool named
  ``<namespace>__<name>`` (at most 64 characters, else shortened with a stable hash); ``defer_loading`` is dropped
  (every tool is offered). Earlier calls in ``input`` (``function_call`` / ``custom_tool_call`` with ``namespace``)
  and their outputs get the same flat name, so the history matches the offered tools; a ``tool_choice`` naming a
  namespaced tool too;
- answer (:class:`NamespaceMap`): every call item whose name is a flat name gets its ``namespace`` and inner
  ``name`` back, in streamed events (``item``, ``response.output``, a top-level ``name``) and in a JSON answer.

Tools that are not in a namespace are forwarded unchanged. The content checks and the transcript see the request as
Codex sent it; only the upstream body is flattened.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SEPARATOR = "__"
MAX_TOOL_NAME = 64
_CALL_TYPES = frozenset({"function_call", "custom_tool_call"})
_OUTPUT_TYPES = frozenset({"function_call_output", "custom_tool_call_output"})
_FLATTENED_TYPES = frozenset({"function", "custom"})


def _type(item: Mapping[str, Any]) -> str | None:
    """An item's ``type`` only when it is a string (never hashed in another shape)."""
    kind = item.get("type")
    return kind if isinstance(kind, str) else None


def flat_name(namespace: str, name: str) -> str:
    joined = f"{namespace}{SEPARATOR}{name}"
    if len(joined) <= MAX_TOOL_NAME:
        return joined
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
    return f"{joined[:MAX_TOOL_NAME - 13]}_{digest}"


@dataclass
class NamespaceMap:
    """Flat name -> ``(namespace, inner name)`` of one request."""

    pairs: dict[str, tuple[str, str]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.pairs)

    def flat(self, namespace: str, name: str) -> str:
        flattened = flat_name(namespace, name)
        self.pairs[flattened] = (namespace, name)
        return flattened

    def restore_item(self, item: Any) -> Any:
        if not isinstance(item, Mapping) or _type(item) not in _CALL_TYPES:
            return item
        pair = self.pairs.get(str(item.get("name") or ""))
        if pair is None:
            return item
        return {**item, "namespace": pair[0], "name": pair[1]}

    def restore_payload(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """A streamed event or a JSON answer with every flat call name mapped back (the same object if none)."""
        if not self.pairs:
            return payload
        restored: dict[str, Any] | None = None
        if "item" in payload and (item := self.restore_item(payload["item"])) is not payload["item"]:
            restored = {**payload, "item": item}
        name = payload.get("name")
        if isinstance(name, str) and name in self.pairs:
            restored = {**(restored or payload), "namespace": self.pairs[name][0], "name": self.pairs[name][1]}
        response = payload.get("response")
        if isinstance(response, Mapping) and isinstance(response.get("output"), list):
            output = [self.restore_item(item) for item in response["output"]]
            if any(new is not old for new, old in zip(output, response["output"], strict=True)):
                restored = {**(restored or payload), "response": {**response, "output": output}}
        output = payload.get("output")
        if isinstance(output, list) and "response" not in payload:
            items = [self.restore_item(item) for item in output]
            if any(new is not old for new, old in zip(items, output, strict=True)):
                restored = {**(restored or payload), "output": items}
        return restored if restored is not None else payload


def _flatten_tools(tools: Any, names: NamespaceMap) -> Any:
    if not isinstance(tools, list):
        return tools
    flattened: list[Any] = []
    for tool in tools:
        if not isinstance(tool, Mapping) or tool.get("type") != "namespace":
            flattened.append(tool)
            continue
        namespace = str(tool.get("name") or "")
        if not isinstance(tool.get("tools"), list):
            flattened.append(tool)  # not a namespace the gateway can flatten: its gate reads it as it is (C12B-03)
            continue
        for inner in tool["tools"]:
            if not isinstance(inner, Mapping) or _type(inner) not in _FLATTENED_TYPES or not inner.get("name"):
                flattened.append(inner)  # never dropped silently: the gate reads (or refuses) it as it is
                continue
            plain = {key: value for key, value in inner.items() if key != "defer_loading"}
            plain["name"] = names.flat(namespace, str(inner["name"]))
            flattened.append(plain)
    return flattened


def _flatten_input(items: Any, names: NamespaceMap) -> Any:
    if not isinstance(items, list):
        return items
    out: list[Any] = []
    for item in items:
        if isinstance(item, Mapping) and _type(item) in _CALL_TYPES | _OUTPUT_TYPES and item.get("namespace"):
            plain = {key: value for key, value in item.items() if key != "namespace"}
            if item.get("name"):
                plain["name"] = names.flat(str(item["namespace"]), str(item["name"]))
            out.append(plain)
        else:
            out.append(item)
    return out


def flatten_request(body: Mapping[str, Any]) -> tuple[dict[str, Any], NamespaceMap]:
    """The upstream body with Codex's namespace tools flattened, and the map to restore the answer."""
    names = NamespaceMap()
    upstream = copy.copy(dict(body))
    if "tools" in upstream:
        upstream["tools"] = _flatten_tools(upstream["tools"], names)
    if "input" in upstream:
        upstream["input"] = _flatten_input(upstream["input"], names)
    choice = upstream.get("tool_choice")
    if isinstance(choice, Mapping) and choice.get("namespace") and choice.get("name"):
        upstream["tool_choice"] = {**{key: value for key, value in choice.items() if key != "namespace"},
                                   "name": names.flat(str(choice["namespace"]), str(choice["name"]))}
    return upstream, names


__all__ = ["MAX_TOOL_NAME", "NamespaceMap", "flat_name", "flatten_request"]
