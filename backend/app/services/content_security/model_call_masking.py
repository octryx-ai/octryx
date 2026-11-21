"""The provider-bound copy of a model request and the released reply (see ``model_call``, ``examination``).

- :func:`provider_messages` — every message's text (string content, text parts, text documents, tool results)
  and every other field but its structure (``name`` and any field a caller added), the name and arguments of
  every replayed tool call (``tool_calls[].function``, the arguments a JSON string or a structure; a masked name is
  masked alike in the offered tool definitions, one numbering) and every system message that is not exactly a
  shipped seed text (authored and untrusted, ``message_trust``), each with its disposition
  (``examination.TransportRun``: masked, withheld, media, unreadable); the trust marker is removed. The caller's
  messages and their tool calls are never changed: the loop executes the tool calls it holds, the provider gets
  the copy.
- Every recognized block (text, tool result, document, image and file parts) is read whole: its text or content
  and every sibling field (a citation, a title, ``cache_control``, an image's ``detail``) under its disposition;
  only the values under the opaque key list (``content_detection.request_text``: base64 media data, ``data:``
  URLs) are left as they are. A block of another type is unreadable.
- Serialized arguments are parsed as JSON (``request_examination.strict_json``): a repeated key is unreadable (the
  call is refused before dispatch: readers would disagree on its value); a field whose name assigns a credential
  has its whole value masked (``platform_detectors.credential_field``), every pair is examined, and the copy carries
  the re-serialized examined structure. A text that is not a JSON object or array is examined as text.
- Message fields other than the structure (``name`` and any field a caller added) are the ``message_extras``
  surface. Each message is disposed in its context (``RecordedRun.message``): new content (a system message, or
  after the last assistant message) or older history, with its trust.
- Replayed tool-call arguments and the offered tool definitions (:func:`provider_tools`) are structures: each
  gets the aggregate field-aware examination (``model_call_fields.structure_examination``) before its leaves. An
  unfinished aggregate withholds the whole structure from
  the copy (arguments become :data:`WITHHELD_STRUCTURE`, a tool definition is not offered), even when every leaf
  finishes.
  The run is ``model_call_fields.RecordedRun``: it keeps every examination the copy was disposed by (aggregates and
  leaves), so the call's decision record carries their completion.
- Every disposition is attributed to its surface (``model_call_record``): message texts, replayed tool-call
  arguments (``replay_arguments``), message extras (``message_extras``) and offered tool definitions
  (``offered_tools``), so the record names where an action was applied.
- :func:`released_reply` — the reply's ``content`` and ``thinking`` (reasoning) under the same dispositions; the
  reply's tool calls are what the platform executes and stay as the model wrote them (they reach a provider only
  through the next request, examined there).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ..content_detection.findings import Finding
from ..content_detection.masking import WITHHELD_TEXT
from ..content_detection.platform_detectors import credential_field
from ..content_detection.request_examination import DuplicateKeyError, strict_json
from ..content_detection.request_text import opaque
from ..content_detection.vocabulary import (
    CATEGORY_SECRETS,
    CONFIDENCE_MEDIUM,
    DETECTOR_CREDENTIAL_ASSIGNMENT,
    SOURCE_HISTORY,
    SOURCE_PROMPT,
    SOURCE_SYSTEM,
    SOURCE_TOOL_RESULT,
)
from .message_trust import CONTENT_TRUST_KEY, TRUST_UNTRUSTED, checked_trust, is_platform_instruction
from .model_call_record import SURFACE_MESSAGE_EXTRAS, SURFACE_OFFERED_TOOLS, SURFACE_REPLAY_ARGUMENTS
from .transport import TransportRun

if TYPE_CHECKING:
    from .model_call_fields import RecordedRun

#: The reply fields that carry model text: the answer and the reasoning some drivers return (Ollama,
#: OpenAI-compatible ``<think>`` blocks).
REPLY_TEXT_FIELDS: tuple[str, ...] = ("content", "thinking")
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
    """Every field of ``holder`` but ``skip`` under its disposition; a value under the opaque key list is left as
    it is."""
    for key in [key for key in holder if key not in skip]:
        if opaque(holder, key, holder[key]):
            continue
        holder[key] = masked_structure(run, holder[key])


def _mask_source(run: TransportRun, block: dict[str, Any]) -> None:
    """An image's or document's ``source``: text read, base64 data opaque, a URL or file reference read; a source of
    another shape is unreadable."""
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
    """``holder[key]``: text, a list of blocks, or nothing; any other shape is unreadable."""
    content = holder.get(key)
    if isinstance(content, str):
        holder[key] = run.text(content)
    elif isinstance(content, list):
        for block in content:
            _mask_block(run, block)
    elif content is not None:
        run.unreadable += 1


def _credential_finding(value: str) -> Finding:
    return Finding(DETECTOR_CREDENTIAL_ASSIGNMENT, CATEGORY_SECRETS, CONFIDENCE_MEDIUM, 0, len(value))


def _parse(text: str) -> Any:
    """Serialized arguments as JSON: a repeated key raises :class:`DuplicateKeyError`, anything else
    ``ValueError``."""
    return strict_json(text)


def masked_structure(run: TransportRun, value: Any) -> Any:
    """``value`` (text, list or object) with every string under its disposition; a field whose name assigns a
    credential has its whole value masked."""
    if isinstance(value, str):
        return run.text(value)
    if isinstance(value, dict):
        masked: dict[Any, Any] = {}
        for key, item in value.items():
            name = str(key)
            if isinstance(item, str) and credential_field(name, item):
                examined = run.text(item)  # every kind and injection read in it, like any value
                whole = run.whole(item, _credential_finding(item))
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
    """Tool-call arguments as a structure or as a JSON string (see the module doc)."""
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
    """Serialized arguments that repeat a key: refused as unreadable before anything else reads them."""
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
    """Every replayed call whole: its envelope (id, type), its function's name, arguments and other fields. A
    carrier of another shape is unreadable."""
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
    """The provider-bound copy of the offered tool definitions (newly offered on every call): each examined as a
    structure and masked like arguments; a definition whose aggregate examination did not finish is not offered.
    ``tools`` is not changed."""
    with run.at(SURFACE_OFFERED_TOOLS), run.message(new=True, trust=TRUST_UNTRUSTED):
        return [masked_structure(run, tool) for tool in tools if run.structure(tool)]


def _source(role: Any, new: bool) -> str:
    """Where a message's text is recorded: system text, and the newest turn's prompt and tool results."""
    if role == "system":
        return SOURCE_SYSTEM
    if new and role == "user":
        return SOURCE_PROMPT
    return SOURCE_TOOL_RESULT if new and role == "tool" else SOURCE_HISTORY


def _last_assistant(messages: list[Any]) -> int:
    return max((index for index, item in enumerate(messages)
                if isinstance(item, Mapping) and item.get("role") == "assistant"), default=-1)


def provider_messages(messages: list[Any], run: RecordedRun) -> list[Any]:
    """The provider-bound copy of ``messages`` (see the module doc); ``messages`` is not changed. Each message's
    fields are disposed with its context: new (a system message, or after the last assistant message) or older
    history, and its trust."""
    changed = copy.deepcopy([dict(item) if isinstance(item, Mapping) else item for item in messages])
    last = _last_assistant(changed)
    for index, message in enumerate(changed):
        role = message.get("role") if isinstance(message, dict) else None
        if not isinstance(role, str) or role not in _ROLES:
            run.unreadable += 1
            continue
        trusted = is_platform_instruction(message)
        trust = checked_trust(message)
        if not run.keep_trust:
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


def _without_credential_fields(value: Any, found: list[Finding]) -> Any:
    """``value`` with each credential field's value blanked; one finding per such field in ``found``."""
    if isinstance(value, dict):
        result: list[list[Any]] = []
        for key, item in value.items():
            if isinstance(item, str) and credential_field(str(key), item):
                found.append(_credential_finding(item))
                result.append([key, ""])
            else:
                result.append([key, _without_credential_fields(item, found)])
        return result
    if isinstance(value, list):
        return [_without_credential_fields(item, found) for item in value]
    return value


def argument_text(arguments: Any, found: list[Finding]) -> str:
    """Tool arguments (structure or JSON text) as the text the detectors read, every credential field's value
    blanked and counted in ``found`` (one finding each)."""
    if isinstance(arguments, str):
        try:
            parsed = _parse(arguments)
        except ValueError:  # not JSON, or a repeated key (refused before dispatch): the text as it is
            return arguments
        if not isinstance(parsed, dict | list):
            return arguments
        arguments = parsed
    try:
        return json.dumps(_without_credential_fields(arguments, found), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return ""


def released_reply(result: dict[str, Any], run: TransportRun) -> dict[str, Any]:
    """``result`` with its text fields under their dispositions (a new dict; the tool calls are the same
    objects). A text field of another shape is counted unreadable."""
    released = dict(result)
    for field in REPLY_TEXT_FIELDS:
        if result.get(field) is not None:
            released[field] = run.text(result[field])
    return released


__all__ = ["REPLY_TEXT_FIELDS", "WITHHELD_STRUCTURE", "argument_text", "masked_arguments", "masked_structure",
           "provider_messages", "provider_tools", "released_reply"]
