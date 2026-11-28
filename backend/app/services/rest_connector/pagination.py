"""Pagination, one page per call: the answer carries ``next_cursor`` and the model passes it back."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Any

import httpx

from .response import get_path

KINDS = ("none", "cursor", "offset", "next_url", "link_header")
_LINK_NEXT_RE = re.compile(r'<([^>]+)>\s*;[^,]*\brel="?next"?', re.IGNORECASE)


class CursorError(ValueError):
    pass


def normalize_pagination(raw: Any) -> dict[str, Any]:
    config = dict(raw) if isinstance(raw, dict) else {}
    kind = str(config.get("type") or "none")
    if kind not in KINDS:
        raise ValueError(f"pagination type must be one of {', '.join(KINDS)}")
    normalized: dict[str, Any] = {"type": kind}
    if kind == "cursor":
        normalized["cursor_path"] = str(config.get("cursor_path") or "next_cursor")
        normalized["cursor_param"] = str(config.get("cursor_param") or "cursor")
    elif kind == "offset":
        normalized["offset_param"] = str(config.get("offset_param") or "offset")
        normalized["limit_param"] = str(config.get("limit_param") or "limit")
        normalized["page_size"] = max(1, int(config.get("page_size") or 50))
    elif kind == "next_url":
        normalized["next_path"] = str(config.get("next_path") or "next")
    return normalized


def _key() -> bytes:
    from ...config import get_settings

    return hashlib.sha256(f"rest-cursor:{get_settings().jwt_secret}".encode()).digest()


def sign_url(url: str, operation_id: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"u": url, "o": operation_id}).encode()).decode().rstrip("=")
    signature = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"u.{payload}.{signature}"


def open_url_cursor(cursor: str, operation_id: str, base_url: str) -> str:
    try:
        _, payload, signature = str(cursor).split(".")
        expected = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, TypeError):
        raise CursorError("The cursor is not one this operation returned; pass next_cursor unchanged.") from None
    url = str(data.get("u") or "")
    if data.get("o") != operation_id or httpx.URL(url).host != httpx.URL(base_url).host:
        raise CursorError("The cursor is not one this operation returned; pass next_cursor unchanged.")
    return url


def next_cursor(
    config: dict[str, Any],
    *,
    body: Any,
    response: httpx.Response,
    operation_id: str,
    offset: int,
    record_count: int,
) -> str | None:
    kind = config.get("type")
    if kind == "cursor":
        value = get_path(body, config["cursor_path"])
        return str(value) if isinstance(value, str | int) and str(value) else None
    if kind == "offset":
        return str(offset + record_count) if record_count >= config["page_size"] else None
    url = None
    if kind == "next_url":
        value = get_path(body, config["next_path"])
        url = str(value) if isinstance(value, str) and value else None
    elif kind == "link_header":
        match = _LINK_NEXT_RE.search(response.headers.get("link", ""))
        url = match.group(1) if match else None
    if url is None:
        return None
    return sign_url(str(response.request.url.join(url)), operation_id)


__all__ = ["KINDS", "CursorError", "next_cursor", "normalize_pagination", "open_url_cursor", "sign_url"]
