"""The text a content check reads of a whole JSON request: every key and value but the exact opaque key list.

Both checks of an outgoing request read it this way: the gateway the body an external coding agent sent
(``content_routing.gateway``; it is forwarded unchanged, so the text read is the text sent) and the provider wrapper
the final request object a driver hands to its transport or SDK (``final_check``). The request is serialized to JSON
(keys, strings with their escapes, numbers; no non-finite number) and read as one text, except the values under the
opaque key list — provider state and inline media the detectors cannot read. They are skipped by key, without any
validation of their content (README "Sensitive content handling": the threat model is accidental leakage, not a
deliberately evasive client):

- ``signature`` — a string: a thinking block's signed state;
- ``encrypted_content`` — a string: encrypted reasoning, compaction or web-search state;
- ``data`` — a string in an object whose ``type`` is ``base64`` (a media source) or ``redacted_thinking``;
- ``image_url``, ``url``, ``file_data`` — a string that is a ``data:`` URL (an inline image or file).

The text is never rewritten: a string value the caller skips (``skip``: the provider wrapper's exact shipped seed
texts) is read as an empty string, like an opaque value. The structured credential assignments of the request
(:func:`credential_values`) are read from the same parsed values, honoring the same opaque list and the same skipped
values; both checks add them to their text examination the same way (:func:`credential_findings`).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .findings import Finding
from .platform_detectors import credential_field
from .request_examination import strict_json
from .vocabulary import CATEGORY_SECRETS, CONFIDENCE_MEDIUM, DETECTOR_CREDENTIAL_ASSIGNMENT

#: The opaque keys whose string value is never read (see the module doc).
OPAQUE_KEYS = frozenset({"signature", "encrypted_content"})
#: ``data`` is opaque in an object of one of these types.
OPAQUE_DATA_TYPES = frozenset({"base64", "redacted_thinking"})
#: These keys are opaque when their value is a ``data:`` URL.
DATA_URL_KEYS = frozenset({"image_url", "url", "file_data"})


class UnreadableRequestError(ValueError):
    """The request cannot be read as JSON text: a value JSON has no form for, a non-finite number, a cycle or a
    nesting beyond the interpreter's bound."""


def opaque(holder: Mapping[str, Any], key: Any, value: Any) -> bool:
    """Whether ``holder[key]`` is on the opaque key list."""
    if not isinstance(value, str):
        return False
    if key in OPAQUE_KEYS:
        return True
    if key == "data":
        kind = holder.get("type")
        return isinstance(kind, str) and kind in OPAQUE_DATA_TYPES
    return key in DATA_URL_KEYS and value.startswith("data:")


def _readable(value: Any, skip: Callable[[str], bool] | None) -> Any:
    if isinstance(value, Mapping):
        return {key: "" if opaque(value, key, item) else _readable(item, skip) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_readable(item, skip) for item in value]
    if isinstance(value, str) and skip is not None and skip(value):
        return ""
    return value


def request_text(value: Any, skip: Callable[[str], bool] | None = None) -> str:
    """``value`` as the one text a check reads (see the module doc); a string value (never a key) ``skip`` names is
    read as empty. Raises :class:`UnreadableRequestError`."""
    try:
        return json.dumps(_readable(value, skip), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise UnreadableRequestError("the request cannot be read as JSON text") from None


def _embedded(text: str) -> Any:
    """A string value that is itself a JSON object or array (serialized tool arguments, a structured tool
    result), parsed strictly; ``None`` for any other text."""
    if not text.lstrip().startswith(("{", "[")):
        return None
    try:
        parsed = strict_json(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict | list) else None


def credential_values(value: Any, skip: Callable[[str], bool] | None = None) -> list[str]:
    """Every value of ``value`` that a structured field assigns as a literal credential
    (``platform_detectors.credential_field``: the name ends in a credential name, the whole value is the
    credential) — in objects at any depth and in string values that are themselves serialized JSON — except the
    values under the opaque key list and the string values ``skip`` names."""
    found: list[str] = []
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, Mapping):
            for key, child in item.items():
                if opaque(item, key, child) or (isinstance(child, str) and skip is not None and skip(child)):
                    continue
                if isinstance(key, str) and isinstance(child, str) and credential_field(key, child):
                    found.append(child)
                else:
                    pending.append(child)
        elif isinstance(item, list | tuple):
            pending += list(item)
        elif isinstance(item, str):
            embedded = _embedded(item)
            if embedded is not None:
                pending.append(embedded)
    return found


def credential_findings(text: str, findings: Iterable[Iterable[Finding]], value: Any,
                        skip: Callable[[str], bool] | None = None) -> tuple[Finding, ...]:
    """One ``credential_assignment`` finding per structured credential field of ``value`` (:func:`credential_values`)
    whose value the text detector did not already find in ``text`` (``value`` read by :func:`request_text` with
    ``skip``; ``findings``: that text's) — the one structured classification of both checks."""
    seen = {text[item.start:item.end] for found in findings for item in found
            if item.detector == DETECTOR_CREDENTIAL_ASSIGNMENT}
    return tuple(Finding(DETECTOR_CREDENTIAL_ASSIGNMENT, CATEGORY_SECRETS, CONFIDENCE_MEDIUM, 0, len(item))
                 for item in credential_values(value, skip) if json.dumps(item, ensure_ascii=False)[1:-1] not in seen)


__all__ = [
    "DATA_URL_KEYS",
    "OPAQUE_DATA_TYPES",
    "OPAQUE_KEYS",
    "UnreadableRequestError",
    "credential_findings",
    "credential_values",
    "opaque",
    "request_text",
]
