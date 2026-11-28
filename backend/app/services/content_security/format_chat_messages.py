"""The platform's chat-messages format: its masking walk over messages, blocks, extras, tool calls and offered tools."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..content_detection.examination import RequestBudget
from ..content_detection.masking import WITHHELD_TEXT, PlaceholderSpans
from ..content_detection.platform_detectors import credential_field
from ..content_detection.request_examination import DuplicateKeyError
from ..content_detection.request_text import opaque
from ..content_detection.scanner import DetectorSet
from ..content_detection.vocabulary import (
    SOURCE_HISTORY,
    SOURCE_PROMPT,
    SOURCE_SYSTEM,
    SOURCE_TOOL_RESULT,
)
from .message_trust import CONTENT_TRUST_KEY, TRUST_UNTRUSTED, checked_trust, is_platform_instruction
from .model_call_masking import _parse, credential_finding
from .model_call_record import SURFACE_MESSAGE_EXTRAS, SURFACE_OFFERED_TOOLS, SURFACE_REPLAY_ARGUMENTS
from .transport import TransportRun, mask_run

if TYPE_CHECKING:
    from .model_call_fields import RecordedRun

#: The fields of a message that are its structure, not text: the role, the platform's cache scope, and the content
#: and tool calls (each with its own disposition). Every other field is examined (the call a tool message answers
#: included: its id is masked like the replayed call's, one numbering).
_MESSAGE_STRUCTURE = frozenset({"role", "cache_scope", "content", "tool_calls"})


_ROLES = frozenset({"system", "user", "assistant", "tool"})


#: What a structure whose aggregate examination did not finish becomes in a provider-bound copy.
WITHHELD_STRUCTURE = {"withheld": WITHHELD_TEXT}


#: Per block type: the fields read elsewhere (its discriminator, its text or content).
_BLOCKS: dict[str, frozenset[str]] = {
    "text": frozenset({"type", "text"}),
    "tool_result": frozenset({"type", "content"}),
    "document": frozenset({"type", "source"}),
    "image": frozenset({"type", "source"}),
    "image_url": frozenset({"type"}),
    "input_image": frozenset({"type"}),
    "file": frozenset({"type"}),
}


#: A media block's nested object.
_NESTED = {"image_url": "image_url", "file": "file"}


def _mask_fields(run: TransportRun, holder: dict[str, Any], skip: frozenset[str]) -> None:
    for key in [key for key in holder if key not in skip]:
        if opaque(holder, key, holder[key]):
            continue
        holder[key] = masked_structure(run, holder[key])


def _mask_source(run: TransportRun, block: dict[str, Any]) -> None:
    source = block.get("source")
    kind = source.get("type") if isinstance(source, dict) else None
    if kind == "text" and isinstance(source.get("data"), str):
        source["data"] = run.text(source["data"])
        _mask_fields(run, source, frozenset({"type", "data"}))
    elif kind in ("base64", "url", "file"):
        _mask_fields(run, source, frozenset({"type"}))
    else:
        run.unreadable += 1


def _mask_block(run: TransportRun, block: Any) -> None:
    kind = block.get("type") if isinstance(block, dict) else None
    if not isinstance(kind, str) or kind not in _BLOCKS:
        run.unreadable += 1
        return
    skip = _BLOCKS[kind]
    if kind == "text":
        block["text"] = run.text(block.get("text"))
    elif kind == "tool_result":
        _mask_content(run, block, "content")
    elif kind in ("document", "image"):
        _mask_source(run, block)
    elif kind in _NESTED and isinstance(block.get(_NESTED[kind]), dict):
        _mask_fields(run, block[_NESTED[kind]], frozenset())
        skip = skip | {_NESTED[kind]}
    _mask_fields(run, block, skip)


def _mask_content(run: TransportRun, holder: dict[str, Any], key: str) -> None:
    content = holder.get(key)
    if isinstance(content, str):
        holder[key] = run.text(content)
    elif isinstance(content, list):
        for block in content:
            _mask_block(run, block)
    elif content is not None:
        run.unreadable += 1


def masked_structure(run: TransportRun, value: Any) -> Any:
    if isinstance(value, str):
        return run.text(value)
    if isinstance(value, dict):
        masked: dict[Any, Any] = {}
        for key, item in value.items():
            name = str(key)
            if isinstance(item, str) and credential_field(name, item):
                examined = run.text(item)  # every kind and injection read in it, like any value
                whole = run.whole(item, credential_finding(item))
                if whole != item:
                    run.withdraw_last()  # the value is replaced whole: nothing found in it is sent
                masked[run.text(name)] = whole if whole != item else examined
            else:
                masked[run.text(name) if isinstance(key, str) else key] = masked_structure(run, item)
        return masked
    if isinstance(value, list):
        return [masked_structure(run, item) for item in value]
    return value


def masked_arguments(run: TransportRun, arguments: Any) -> Any:
    if not isinstance(arguments, str):
        return masked_structure(run, arguments)
    try:
        parsed = _parse(arguments)
    except DuplicateKeyError:  # readers would disagree on the value: refused before dispatch (unreadable)
        run.unreadable += 1
        return arguments
    except ValueError:
        return run.text(arguments)
    if not isinstance(parsed, dict | list):  # a JSON scalar: the text itself is examined
        return run.text(arguments)
    return json.dumps(masked_structure(run, parsed), ensure_ascii=False)


def _repeats_a_key(arguments: Any) -> bool:
    if not isinstance(arguments, str):
        return False
    try:
        _parse(arguments)
    except DuplicateKeyError:
        return True
    except ValueError:
        return False
    return False


def _mask_tool_calls(run: RecordedRun, tool_calls: Any) -> None:
    if tool_calls is None:
        return
    if not isinstance(tool_calls, list):
        run.unreadable += 1
        return
    for tool_call in tool_calls:
        holder = tool_call.get("function") if isinstance(tool_call, dict) else None
        if not isinstance(holder, dict) or "arguments" not in holder or _repeats_a_key(holder["arguments"]):
            run.unreadable += 1
            continue
        with run.at(SURFACE_REPLAY_ARGUMENTS):
            _mask_fields(run, tool_call, frozenset({"function"}))
            arguments = holder["arguments"]
            if run.structure(arguments):
                holder["arguments"] = masked_arguments(run, arguments)
            else:
                holder["arguments"] = (json.dumps(WITHHELD_STRUCTURE) if isinstance(arguments, str)
                                       else dict(WITHHELD_STRUCTURE))
            _mask_fields(run, holder, frozenset({"arguments"}))


def provider_tools(tools: list[Any], run: RecordedRun) -> list[Any]:
    with run.at(SURFACE_OFFERED_TOOLS), run.message(new=True, trust=TRUST_UNTRUSTED):
        return [masked_structure(run, tool) for tool in tools if run.structure(tool)]


def _source(role: Any, new: bool) -> str:
    if role == "system":
        return SOURCE_SYSTEM
    if new and role == "user":
        return SOURCE_PROMPT
    return SOURCE_TOOL_RESULT if new and role == "tool" else SOURCE_HISTORY


def _last_assistant(messages: list[Any]) -> int:
    return max((index for index, item in enumerate(messages)
                if isinstance(item, Mapping) and item.get("role") == "assistant"), default=-1)


def provider_messages(messages: list[Any], run: RecordedRun) -> list[Any]:
    changed = copy.deepcopy([dict(item) if isinstance(item, Mapping) else item for item in messages])
    last = _last_assistant(changed)
    for index, message in enumerate(changed):
        role = message.get("role") if isinstance(message, dict) else None
        if not isinstance(role, str) or role not in _ROLES:
            run.unreadable += 1
            continue
        trusted = is_platform_instruction(message)
        trust = checked_trust(message)
        if not run.keep_trust:  # the trust marker is request metadata, not message content
            message.pop(CONTENT_TRUST_KEY, None)
        if trusted:
            continue
        new = message.get("role") == "system" or index > last
        with run.message(new=new, trust=trust, source=_source(message.get("role"), new)):
            _mask_content(run, message, "content")
            extras = [key for key in message if key not in _MESSAGE_STRUCTURE and key != CONTENT_TRUST_KEY]
            with run.at(SURFACE_MESSAGE_EXTRAS):  # each extra with its key: a credential named by it is read too
                masked = masked_structure(run, {key: message.pop(key) for key in extras})
            message.update(masked)
            if message.get("role") == "assistant":
                _mask_tool_calls(run, message.get("tool_calls"))
            elif message.get("tool_calls") is not None:
                run.unreadable += 1
    return changed


@dataclass(frozen=True, slots=True)
class MaskedRequest:
    body: Any
    masked: int
    withheld: int
    placeholders: PlaceholderSpans = field(default_factory=PlaceholderSpans)


def _blocks(content: Any, apply: Callable[[dict[str, Any]], None]) -> Any:
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                apply(block)
    return content


# A policy's mask obligation over the messages' text and text blocks, one numbering for the whole request.
def mask_chat_messages(messages: list[Mapping[str, Any]], detectors: DetectorSet, mask: frozenset[str],
                       style: str | None, budget: RequestBudget | None = None) -> MaskedRequest:
    run = mask_run(detectors, mask, style, budget=budget)
    changed = copy.deepcopy([dict(item) for item in messages])

    def part(block: dict[str, Any]) -> None:
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            block["text"] = run.text(block["text"])

    for message in changed:
        if isinstance(message.get("content"), str):
            message["content"] = run.text(message["content"])
        else:
            _blocks(message.get("content"), part)
    return MaskedRequest(changed, run.masked, run.withheld, run.placeholders)


__all__ = ["WITHHELD_STRUCTURE", "MaskedRequest", "mask_chat_messages", "masked_arguments", "masked_structure",
           "provider_messages", "provider_tools"]
