"""Shared building blocks for the configured-web-URL source linkers (``web_url_sources``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from ...services.tool_config.web_url import normalize_web_url

Linker = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _web(config: dict[str, Any], field: str) -> str | None:
    return normalize_web_url(config.get(field))


def _items(result: dict[str, Any], key: str, link: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    values = result.get(key)
    if isinstance(values, list):
        result[key] = [link(item) if isinstance(item, dict) else item for item in values]
    return result


def _one(result: dict[str, Any], key: str, link: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    value = result.get(key)
    if isinstance(value, dict):
        result[key] = link(value)
    return result


def _query(**values: object) -> str:
    return urlencode({key: str(value) for key, value in values.items() if str(value or "").strip()})
