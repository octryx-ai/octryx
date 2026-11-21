"""Recover tool calls a model emitted as plain text into the native shape.

Some runtimes return tool calls as text instead of the provider's native
tool-call channel: MiniMax-M3 emits ``<tool_call>``/``<invoke>`` blocks and
``toolname {json}`` lists (with ``]<]minimax[>[`` stream markers); Bedrock
Claude emits Anthropic ``<function_calls><invoke><parameter>`` XML; Bedrock
Nova emits a fenced ``[{"name": ..., "arguments": ...}]`` JSON array; Bedrock
Claude Sonnet also emits a fenced ````tool_use`` block (``name`` line, then a JSON
object). When the provider parsed NO native tool calls we
recover the model's evident intent so the turn actually runs the tool instead of
stalling on "standing by".

:func:`pseudo_tool_call_names` is the structural detector over the same grammars:
the loop uses it to refuse a reply that writes tool calls as text instead of
delivering that text as the answer (``agent/loops/response/_loop_pseudo_tool_calls``).

This module is provider-agnostic on purpose - both ``openai_compatible`` and
``bedrock`` import :func:`parse_inline_tool_calls`.
"""

from __future__ import annotations

import json
import re
from typing import Any

_INLINE_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_PROVIDER_STREAM_MARKER_PATTERN = re.compile(r"\]<\]minimax\[>\[")
_FUNCTION_CALLS_WRAPPER_PATTERN = re.compile(r"</?function_calls>", re.IGNORECASE)
_INVOKE_PATTERN = re.compile(r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>', re.DOTALL)
_PARAMETER_PATTERN = re.compile(r'<parameter\s+name="([^"]+)"\s*>(.*?)</parameter>', re.DOTALL)
# MiniMax also emits <tool name="X" ...>...</tool> and self-closing
# <tool name="X" arg="v" />; the args live in <parameter> tags AND/OR as XML
# attributes. Both `<tool>` and `<invoke>` are accepted here.
_TOOL_TAG_OPEN_CLOSE_PATTERN = re.compile(r"<(?:tool|invoke)\b([^>]*?)>(.*?)</(?:tool|invoke)>", re.DOTALL)
_TOOL_TAG_SELF_CLOSING_PATTERN = re.compile(r"<(?:tool|invoke)\b([^>]*?)/>", re.DOTALL)
_XML_ATTR_PATTERN = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
# Colon forms inside a <tool_call> block: `toolname: {json}` or
# `toolname: key="value" key2="value2"` (block-scoped, so prose "Note: x" is safe).
_COLON_JSON_TOOL_CALL = re.compile(r"\b([a-z][a-z0-9_]*)\s*:\s*(\{[^{}]*\})")
_COLON_KWARGS_TOOL_CALL = re.compile(r'\b([a-z][a-z0-9_]*)\s*:\s*((?:\s*\w+\s*=\s*"[^"]*")+)')
# Bare JSON tool call: guarded to a tool-name-shaped "name" so it never matches
# arbitrary JSON a model happens to include in a normal answer. MiniMax-M3 also
# emits the Anthropic-style "input" key (for example
# {"name": "select_workflow", "input": {"workflow_key": ...}}), so the argument
# key accepts the documented synonyms.
_BARE_JSON_TOOL_CALL = re.compile(
    r'\{\s*"name"\s*:\s*"([a-z][a-z0-9_]*)"\s*,\s*"(?:arguments|input|parameters)"\s*:\s*(\{.*?\}|null)\s*\}',
    re.DOTALL,
)
# A free-text list of "toolname {json args}" pairs (one or many per block, with
# optional `// comment`), another MiniMax-M3 malformation seen inside <tool_call>.
_NAME_JSON_TOOL_CALL = re.compile(r"\b([a-z][a-z0-9_]*)\s*(\{[^{}]*\})")
# MiniMax-M3 "Tool:/Args:" grammar inside a (often unterminated) <tool_call>
# block:
#   Tool: select_workflow
#   Args:
#   - workflow_key: diagram
# One block may carry several Tool groups; values parse as JSON when possible.
_TOOL_YAML_HEADER_PATTERN = re.compile(r"^\s*tool\s*:\s*([a-z][a-z0-9_]*)\s*$", re.IGNORECASE)
_TOOL_YAML_ARGS_PATTERN = re.compile(r"^\s*args\s*:\s*$", re.IGNORECASE)
_TOOL_YAML_ITEM_PATTERN = re.compile(r"^\s*-\s*([A-Za-z_]\w*)\s*:\s*(.*)$")
# An unterminated <tool_call> opener running to the end of the message — the
# closing tag never arrived (stream cut). Only used when the body parses.
_UNTERMINATED_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*)\Z", re.DOTALL)
# A ```json fenced block (Bedrock Nova wraps its tool-call ARRAY in one).
# Arrays only: a fenced lone JSON object is quoted material (models quote
# example calls in fences), not the Nova grammar.
_FENCED_JSON_PATTERN = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)
# A fence whose language tag names a tool call (Bedrock Claude Sonnet: ```tool_use,
# then the tool name on its own line, then a JSON object). The tag is the structural marker:
# ordinary markdown never labels a fence this way.
_TOOL_CALL_FENCE_PATTERN = re.compile(
    r"```[ \t]*(?:tool_use|tool_call|tool_calls|function_call|function_calls)[ \t]*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_FENCED_NAME_JSON_PATTERN = re.compile(r"\A([a-z][a-z0-9_]*)\s*(\{.*\})?\s*\Z", re.DOTALL)
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
# Documented argument-key synonyms models use for the payload of a tool call:
# OpenAI "arguments", Anthropic "input", generic "parameters" (MiniMax-M3 mixes
# them). Order is the lookup priority.
_ARGUMENT_KEYS = ("arguments", "input", "parameters")
# Markdown fence line: content inside fences is quoted material for the
# JSON-object-line recovery (a fenced tool-call ARRAY keeps its own dedicated
# Nova path above).
_FENCE_LINE_PATTERN = re.compile(r"^\s*(```|~~~)")
# Orphan <tool_call> wrappers left next to a successfully recovered call
# (for example a lone `</tool_call>`).
_TOOL_CALL_RESIDUE_PATTERN = re.compile(r"</?tool_call>")


def _payload_arguments(payload: dict[str, Any]) -> Any:
    """Return the argument object of a JSON tool-call payload, accepting the
    documented argument-key synonyms (``arguments``/``input``/``parameters``)."""
    for key in _ARGUMENT_KEYS:
        if key in payload:
            return payload.get(key)
    return None


def _strip_recovered_residue(text: str) -> str:
    return _TOOL_CALL_RESIDUE_PATTERN.sub("", text).strip()


def _fence_spans(text: str) -> list[tuple[int, int]]:
    """Spans of matched ``` fenced regions — quoted material for the text
    recovery stages (the dedicated Nova fenced-ARRAY stage is the exception)."""
    return [match.span() for match in re.finditer(r"```.*?```", text, re.DOTALL)]


def _matches_outside_fences(pattern: re.Pattern[str], text: str) -> tuple[list[re.Match[str]], str]:
    """Return the pattern matches lying outside fenced regions, plus the text
    with exactly those matches removed (fenced/quoted matches stay in place)."""
    spans = _fence_spans(text)
    kept: list[re.Match[str]] = []
    for match in pattern.finditer(text):
        start, end = match.span()
        if any(start < fence_end and end > fence_start for fence_start, fence_end in spans):
            continue
        kept.append(match)
    if not kept:
        return [], text
    parts: list[str] = []
    cursor = 0
    for match in kept:
        parts.append(text[cursor : match.start()])
        cursor = match.end()
    parts.append(text[cursor:])
    return kept, "".join(parts)


def _json_object_line_calls(text: str) -> tuple[list[tuple[str, Any]], str]:
    """Recover lines that are exactly one JSON tool-call object.

    Grammar: a line that parses as a JSON
    object with a tool-name-shaped ``name`` and one of the documented argument
    keys. Lines inside markdown fences are quoted material and are skipped.
    Returns the recovered calls and the text with recovered lines removed.
    """
    calls: list[tuple[str, Any]] = []
    kept_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_LINE_PATTERN.match(line):
            in_fence = not in_fence
            kept_lines.append(line)
            continue
        stripped = line.strip()
        if in_fence or not (stripped.startswith("{") and stripped.endswith("}")):
            kept_lines.append(line)
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            kept_lines.append(line)
            continue
        if not isinstance(payload, dict):
            kept_lines.append(line)
            continue
        name = str(payload.get("name") or "").strip()
        if not _TOOL_NAME_PATTERN.match(name) or not any(key in payload for key in _ARGUMENT_KEYS):
            kept_lines.append(line)
            continue
        calls.append((name, _payload_arguments(payload)))
    return calls, "\n".join(kept_lines)


def _attrs_to_args(attr_text: str) -> dict[str, Any]:
    """Parse XML attributes (name="v") into an arguments dict, dropping the
    ``name`` attribute (it is the tool name, not an argument). Values that parse
    as JSON keep their JSON type; everything else stays a string."""
    args: dict[str, Any] = {}
    for key, value in _XML_ATTR_PATTERN.findall(attr_text):
        if key == "name":
            continue
        try:
            args[key] = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            args[key] = value
    return args


def _tool_tag_calls(text: str) -> list[tuple[str, Any]]:
    """Recover <tool ...>/<invoke ...> calls (open/close and self-closing).

    Args come from <parameter> tags in the body merged with XML attributes, or
    from the attributes alone when the tag is self-closing.
    """
    calls: list[tuple[str, Any]] = []
    for attr_text, body in _TOOL_TAG_OPEN_CLOSE_PATTERN.findall(text):
        name = dict(_XML_ATTR_PATTERN.findall(attr_text)).get("name", "").strip()
        if not name:
            continue
        args = _attrs_to_args(attr_text)
        args.update({key: value.strip() for key, value in _PARAMETER_PATTERN.findall(body)})
        calls.append((name, args))
    for attr_text in _TOOL_TAG_SELF_CLOSING_PATTERN.findall(text):
        name = dict(_XML_ATTR_PATTERN.findall(attr_text)).get("name", "").strip()
        if not name:
            continue
        calls.append((name, _attrs_to_args(attr_text)))
    return calls


def _tool_yaml_calls(block: str) -> list[tuple[str, Any]]:
    """Recover the ``Tool: <name>`` / ``Args:`` / ``- key: value`` grammar.

    Values parse as JSON when possible (arrays, numbers, quoted strings) and
    stay plain strings otherwise. Several Tool groups per block are supported.
    """
    calls: list[tuple[str, Any]] = []
    current_name = ""
    current_args: dict[str, Any] = {}
    for line in block.splitlines():
        header = _TOOL_YAML_HEADER_PATTERN.match(line)
        if header:
            if current_name:
                calls.append((current_name, current_args))
            current_name = header.group(1).strip()
            current_args = {}
            continue
        if not current_name or _TOOL_YAML_ARGS_PATTERN.match(line):
            continue
        item = _TOOL_YAML_ITEM_PATTERN.match(line)
        if not item:
            continue
        key, raw_value = item.group(1), item.group(2).strip()
        try:
            current_args[key] = json.loads(raw_value)
        except (json.JSONDecodeError, ValueError):
            current_args[key] = raw_value
    if current_name:
        calls.append((current_name, current_args))
    return calls


def _colon_form_calls(block: str) -> list[tuple[str, Any]]:
    """Recover block-scoped ``toolname: {json}`` and ``toolname: k="v"`` forms."""
    calls: list[tuple[str, Any]] = []
    for name, raw_args in _COLON_JSON_TOOL_CALL.findall(block):
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {}
        calls.append((name.strip(), args if isinstance(args, dict) else {}))
    for name, kwargs_text in _COLON_KWARGS_TOOL_CALL.findall(block):
        args = {key: value for key, value in _XML_ATTR_PATTERN.findall(kwargs_text)}
        if args:
            calls.append((name.strip(), args))
    return calls


def _tool_calls_from_block(block: str, *, strict: bool = False) -> list[tuple[str, Any]]:
    """Extract (name, arguments) pairs from one inline tool-call block.

    Handles a whole-block JSON object; ``<invoke>``/``<tool>`` elements
    (open/close or self-closing, args from <parameter> tags or XML attributes);
    a free-text ``toolname {json}`` list; and ``toolname: ...`` colon forms - a
    block may carry several calls.
    """
    block = block.strip()
    try:
        payload = json.loads(block)
        if isinstance(payload, dict) and str(payload.get("name") or "").strip():
            # Argument-key synonyms (arguments/input/parameters) are honored;
            # dropping the payload silently would make the model retry
            # `select_workflow {}` in a loop.
            arguments = _payload_arguments(payload)
            if arguments is None:
                # Flattened form: the argument keys sit NEXT to "name" in the
                # same object ({"name": X, "workflow_key": ...}). Inside a
                # tool-call block the intent is unambiguous, so the remaining
                # keys are the arguments.
                flattened = {
                    key: value for key, value in payload.items() if key not in {"name", "id", "type"}
                }
                arguments = flattened or None
            return [(str(payload["name"]).strip(), arguments)]
    except json.JSONDecodeError:
        pass
    tag_calls = _tool_tag_calls(block)
    if tag_calls:
        return tag_calls
    line_calls, _remainder = _json_object_line_calls(block)
    if line_calls:
        return line_calls
    yaml_calls = _tool_yaml_calls(block)
    if yaml_calls:
        return yaml_calls
    if strict:
        # Unterminated blocks may contain trailing prose: only the exact
        # grammars above are trusted, never the loose fallback matchers.
        return []
    colon_calls = _colon_form_calls(block)
    if colon_calls:
        return colon_calls
    calls: list[tuple[str, Any]] = []
    for name, raw_args in _NAME_JSON_TOOL_CALL.findall(block):
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {}
        calls.append((name.strip(), args if isinstance(args, dict) else {}))
    return calls


def _as_tool_call(index: int, name: str, arguments: Any) -> dict[str, Any]:
    return {
        "id": f"inline_call_{index}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments if isinstance(arguments, dict) else {}),
        },
    }


def _tool_calls_from_json_payload(payload: Any) -> list[tuple[str, Any]]:
    """Recover tool calls from a parsed JSON array/object, but only when every
    element is a tool-name-shaped ``{"name": ..., "arguments": ...}`` dict, so a
    legitimate JSON array in an answer is never mistaken for tool calls."""
    items = payload if isinstance(payload, list) else [payload]
    if not items:
        return []
    calls: list[tuple[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            return []
        name = str(item.get("name") or "").strip()
        if not any(key in item for key in _ARGUMENT_KEYS) or not _TOOL_NAME_PATTERN.match(name):
            return []
        args = _payload_arguments(item)
        calls.append((name, args if isinstance(args, dict) else {}))
    return calls


def _tool_call_fence_calls(body: str) -> list[tuple[str, Any]]:
    """Recover the calls of one ```tool_use fence body.

    Grammars: a JSON tool-call object/array (``name`` plus ``input``/``arguments``), or
    the tool name alone on the first line followed by an optional JSON argument object
    (on the same or the following lines).
    """
    text = body.strip()
    try:
        return _tool_calls_from_json_payload(json.loads(text))
    except json.JSONDecodeError:
        pass
    match = _FENCED_NAME_JSON_PATTERN.match(text)
    if not match:
        return []
    raw_args = match.group(2)
    if not raw_args:
        return [(match.group(1), {})]
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        return []
    return [(match.group(1), args)] if isinstance(args, dict) else []


def pseudo_tool_call_names(content: str) -> list[str]:
    """Tool calls written as text in ``content``, by the known inline grammars; ``""`` when unnamed.

    A structural check of the reply's shape, never of its meaning: ````tool_use``-family
    fences anywhere, and ``<tool_call>`` blocks or ``<invoke>``/``<tool>`` tags or a
    ``<function_calls>`` wrapper outside quoted (fenced) material. An empty list means the
    reply carries no inline tool call.
    """
    text = _PROVIDER_STREAM_MARKER_PATTERN.sub("", str(content or ""))
    names: list[str] = []
    for match in _TOOL_CALL_FENCE_PATTERN.finditer(text):
        names.extend([name for name, _args in _tool_call_fence_calls(match.group(1))] or [""])
    outside_fences = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    for match in _INLINE_TOOL_CALL_PATTERN.finditer(outside_fences):
        names.extend([name for name, _args in _tool_calls_from_block(match.group(1))] or [""])
    if "<tool_call>" in outside_fences and not _INLINE_TOOL_CALL_PATTERN.search(outside_fences):
        names.append("")
    names.extend(name for name, _args in _tool_tag_calls(outside_fences))
    if not names and _FUNCTION_CALLS_WRAPPER_PATTERN.search(outside_fences):
        names.append("")
    return names


def parse_inline_tool_calls(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Recover inline-text tool calls into the native tool_calls shape.

    Only call this when the model returned NO native tool_calls, so recovering
    the model's evident intent cannot clobber a real call. Returns the cleaned
    text (recovered blocks removed) and the recovered tool calls.
    """
    normalized = _PROVIDER_STREAM_MARKER_PATTERN.sub("", content)
    tool_calls: list[dict[str, Any]] = []

    block_matches, block_cleaned = _matches_outside_fences(_INLINE_TOOL_CALL_PATTERN, normalized)
    if block_matches:
        for match in block_matches:
            for name, arguments in _tool_calls_from_block(match.group(1)):
                tool_calls.append(_as_tool_call(len(tool_calls), name, arguments))
        if tool_calls:
            return _strip_recovered_residue(block_cleaned), tool_calls

    # Unterminated <tool_call> opener running to the end of the message
    # (the closing tag never arrived). Recover ONLY when the
    # body parses into calls; otherwise the opener survives untouched so the
    # non-substantive guard can nudge a retry.
    if "</tool_call>" not in normalized:
        open_matches, open_cleaned = _matches_outside_fences(_UNTERMINATED_TOOL_CALL_PATTERN, normalized)
        if open_matches:
            for name, arguments in _tool_calls_from_block(open_matches[0].group(1), strict=True):
                tool_calls.append(_as_tool_call(len(tool_calls), name, arguments))
            if tool_calls:
                return _strip_recovered_residue(open_cleaned), tool_calls
            tool_calls = []

    # No <tool_call> wrapper: recover bare <invoke>/<tool> tags (optionally inside
    # an Anthropic <function_calls> wrapper) that the model emitted as plain text.
    for name, arguments in _tool_tag_calls(normalized):
        tool_calls.append(_as_tool_call(len(tool_calls), name, arguments))
    if tool_calls:
        cleaned = _TOOL_TAG_SELF_CLOSING_PATTERN.sub("", _TOOL_TAG_OPEN_CLOSE_PATTERN.sub("", normalized))
        cleaned = _FUNCTION_CALLS_WRAPPER_PATTERN.sub("", cleaned)
        return _strip_recovered_residue(cleaned), tool_calls

    # A line that is exactly one JSON tool-call object (MiniMax-M3, "input" key).
    line_calls, line_cleaned = _json_object_line_calls(normalized)
    for name, arguments in line_calls:
        tool_calls.append(_as_tool_call(len(tool_calls), name, arguments))
    if tool_calls:
        return _strip_recovered_residue(line_cleaned), tool_calls

    # A ```tool_use fence (Bedrock Claude Sonnet). Unknown or unoffered names are
    # rejected by the loop's text-derived call audit, never executed.
    for match in _TOOL_CALL_FENCE_PATTERN.finditer(normalized):
        for name, arguments in _tool_call_fence_calls(match.group(1)):
            tool_calls.append(_as_tool_call(len(tool_calls), name, arguments))
    if tool_calls:
        return _strip_recovered_residue(_TOOL_CALL_FENCE_PATTERN.sub("", normalized)), tool_calls

    # A fenced ```json [{"name": ..., "arguments": ...}] array/object (Nova).
    for match in _FENCED_JSON_PATTERN.finditer(normalized):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        for name, arguments in _tool_calls_from_json_payload(payload):
            tool_calls.append(_as_tool_call(len(tool_calls), name, arguments))
    if tool_calls:
        return _strip_recovered_residue(_FENCED_JSON_PATTERN.sub("", normalized)), tool_calls

    bare_matches, bare_cleaned = _matches_outside_fences(_BARE_JSON_TOOL_CALL, normalized)
    for match in bare_matches:
        name, raw_args = match.group(1), match.group(2)
        try:
            args = json.loads(raw_args) if raw_args != "null" else {}
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(_as_tool_call(len(tool_calls), name.strip(), args))
    if tool_calls:
        return _strip_recovered_residue(bare_cleaned), tool_calls

    # Nothing recovered: return the content untouched. A truncated lone
    # `<tool_call>` opener must survive so the
    # non-substantive response guard can see it and nudge a retry.
    return content, []
