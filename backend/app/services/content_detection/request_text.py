"""The one text a content check reads of a whole JSON request."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .findings import Finding
from .platform_detectors import credential_field
from .request_examination import strict_json
from .vocabulary import CATEGORY_SECRETS, CONFIDENCE_MEDIUM, DETECTOR_CREDENTIAL_ASSIGNMENT

#: The opaque keys whose string value is never read: provider state the detectors cannot read.
OPAQUE_KEYS = frozenset({"signature", "encrypted_content"})
#: ``data`` is opaque in an object of one of these types.
OPAQUE_DATA_TYPES = frozenset({"base64", "redacted_thinking"})
#: These keys are opaque when their value is a ``data:`` URL.
DATA_URL_KEYS = frozenset({"image_url", "url", "file_data"})


class UnreadableRequestError(ValueError):
    pass


def opaque(holder: Mapping[str, Any], key: Any, value: Any) -> bool:
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
        return ""  # a skipped value is read as empty, like an opaque one; the request itself is never rewritten
    return value


def request_text(value: Any, skip: Callable[[str], bool] | None = None) -> str:
    try:
        return json.dumps(_readable(value, skip), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise UnreadableRequestError("the request cannot be read as JSON text") from None


def _embedded(text: str) -> Any:
    if not text.lstrip().startswith(("{", "[")):
        return None
    try:
        parsed = strict_json(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict | list) else None


# Serialized JSON inside a string value is parsed too: tool arguments and structured tool results travel that way.
def credential_values(value: Any, skip: Callable[[str], bool] | None = None) -> list[str]:
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
    # One finding per structured credential field the text detector did not already find: the gateway and the final
    # check classify alike.
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
