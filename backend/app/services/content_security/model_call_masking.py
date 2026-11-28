"""The provider-bound copy of a model request and the released reply."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ..content_detection.findings import Finding
from ..content_detection.platform_detectors import credential_field
from ..content_detection.request_examination import strict_json
from ..content_detection.vocabulary import (
    CATEGORY_SECRETS,
    CONFIDENCE_MEDIUM,
    DETECTOR_CREDENTIAL_ASSIGNMENT,
)
from .transport import TransportRun

if TYPE_CHECKING:
    pass

#: The reply fields that carry model text: the answer and the reasoning some drivers return (Ollama,
#: OpenAI-compatible ``<think>`` blocks).
REPLY_TEXT_FIELDS: tuple[str, ...] = ("content", "thinking")


def credential_finding(value: str) -> Finding:
    return Finding(DETECTOR_CREDENTIAL_ASSIGNMENT, CATEGORY_SECRETS, CONFIDENCE_MEDIUM, 0, len(value))


def _parse(text: str) -> Any:
    return strict_json(text)


def _without_credential_fields(value: Any, found: list[Finding]) -> Any:
    if isinstance(value, dict):
        result: list[list[Any]] = []
        for key, item in value.items():
            if isinstance(item, str) and credential_field(str(key), item):
                found.append(credential_finding(item))
                result.append([key, ""])
            else:
                result.append([key, _without_credential_fields(item, found)])
        return result
    if isinstance(value, list):
        return [_without_credential_fields(item, found) for item in value]
    return value


def argument_text(arguments: Any, found: list[Finding]) -> str:
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
    released = dict(result)
    for field in REPLY_TEXT_FIELDS:
        if result.get(field) is not None:
            released[field] = run.text(result[field])
    return released


__all__ = ["REPLY_TEXT_FIELDS", "argument_text", "credential_finding", "released_reply"]
