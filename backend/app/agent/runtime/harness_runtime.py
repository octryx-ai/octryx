"""``HarnessRuntime``: one governed tool-calling run over the Octryx model and tool closures."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.models.json_text import safe_json_dict

EXECUTION_PROFILE_STATUS_ALLOWED = "allowed"
# A correction for an answer with neither text nor a tool call, once per run (pydantic-ai-slim 2.51.0 default).
OUTPUT_RETRIES = 1

# A model call: Octryx messages and tool definitions in, the Octryx response dict out.
ModelCall = Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], Awaitable[dict[str, Any]]]
# A tool call in the Octryx shape in, the content the model sees as the tool result out.
ToolCall = Callable[[dict[str, Any]], Awaitable[str]]


class HarnessPreconditionError(RuntimeError):
    pass


class HarnessProtocolError(RuntimeError):
    pass


class HarnessLimitError(RuntimeError):
    pass


def _tool_name(definition: Mapping[str, Any]) -> str:
    function = definition.get("function") if isinstance(definition, Mapping) else None
    return str(function.get("name") or "").strip() if isinstance(function, Mapping) else ""


class HarnessRuntime:
    def __init__(
        self,
        *,
        execution_profile: Mapping[str, Any] | None,
        model_call: ModelCall,
        base_messages: list[dict[str, Any]],
        tool_definitions: list[dict[str, Any]],
        tool_call: ToolCall,
        request_limit: int,
    ) -> None:
        status = str((execution_profile or {}).get("status") or "").strip().lower()
        if status != EXECUTION_PROFILE_STATUS_ALLOWED:
            raise HarnessPreconditionError(f"execution profile status '{status or 'missing'}' is not allowed")
        self._model_call = model_call
        self._base_messages = [dict(message) for message in base_messages]
        self._definitions: list[dict[str, Any]] = []
        names: set[str] = set()
        for definition in tool_definitions:
            name = _tool_name(definition)
            if name and name not in names:
                names.add(name)
                self._definitions.append(definition)
        self.tool_names = [_tool_name(definition) for definition in self._definitions]
        self._tool_call = tool_call
        self._request_limit = max(1, int(request_limit))

    async def run(self, user_prompt: str) -> str:
        del user_prompt
        messages = [dict(message) for message in self._base_messages]
        refused_tools: set[str] = set()
        empty_answers = 0
        for _ in range(self._request_limit):
            response = await self._model_call(messages, self._definitions or None)
            content = str(response.get("content") or "")
            calls = [call for call in response.get("tool_calls") or [] if call]
            if not calls:
                if content.strip():
                    return content
                empty_answers += 1
                if empty_answers > OUTPUT_RETRIES:
                    raise HarnessProtocolError("the model answered with neither text nor a tool call")
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": self._empty_answer_correction()})
                continue
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            for call in calls:  # one at a time: the governed executor shares one database session
                messages.append(await self._tool_message(call, refused_tools))
        raise HarnessLimitError(f"no final answer within {self._request_limit} model requests")

    async def _tool_message(self, call: Mapping[str, Any], refused_tools: set[str]) -> dict[str, Any]:
        function = call.get("function") if isinstance(call, Mapping) else None
        function = function if isinstance(function, Mapping) else {}
        name = str(function.get("name") or "").strip()
        call_id = str(call.get("id") or "") if isinstance(call, Mapping) else ""
        if name not in self.tool_names:
            if name in refused_tools:
                raise HarnessProtocolError(f"tool '{name or '?'}' is not offered to this run")
            refused_tools.add(name)
            return {"role": "tool", "tool_call_id": call_id, "content": self._unknown_tool_correction(name)}
        result = await self._tool_call({
            "id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(_arguments(function.get("arguments")),
                                                                ensure_ascii=False)},
        })
        return {"role": "tool", "tool_call_id": call_id, "content": result}

    def _unknown_tool_correction(self, name: str) -> str:
        offered = ", ".join(repr(tool) for tool in sorted(self.tool_names))
        available = f"Available tools: {offered}" if offered else "No tools available."
        return f"Unknown tool name: {name!r}. {available}\n\nFix the errors and try again."

    def _empty_answer_correction(self) -> str:
        ask = "return text or call a tool" if self.tool_names else "return text"
        return f"Validation feedback:\nPlease {ask}.\n\nFix the errors and try again."


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    return safe_json_dict(raw if isinstance(raw, str) else None)


__all__ = ["HarnessLimitError", "HarnessPreconditionError", "HarnessProtocolError", "HarnessRuntime", "ModelCall",
           "OUTPUT_RETRIES", "ToolCall"]
