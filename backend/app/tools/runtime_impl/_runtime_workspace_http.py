"""HTTP runtime tool implementation."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.tools.context import ToolContext

from ...services.approval import ensure_approval_request
from ...services.change_preview import (
    build_change_request_fingerprint,
    consume_change_preview_grant,
    upsert_change_preview,
)
from ...services.outbound_egress.public_web import public_web_client
from ...services.outbound_url_policy import OutboundURLPolicyError
from ._runtime_cli_helpers import _truncate

_HTTP_METHODS_REQUIRING_APPROVAL = {"POST", "PUT", "PATCH", "DELETE"}


def _safe_http_request_url(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _hash_value(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        payload = str(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_mapping(mapping: dict[str, Any]) -> dict[str, str]:
    hashed: dict[str, str] = {}
    for key, value in sorted(mapping.items(), key=lambda item: str(item[0])):
        normalized_key = str(key).strip().lower()
        if not normalized_key:
            continue
        hashed[normalized_key] = _hash_value(value)
    return hashed


def _http_request_approval_payload(
    method: str,
    url: str,
    headers: dict[str, Any],
    query: dict[str, Any],
    body: Any,
) -> dict[str, Any]:
    safe_url = _safe_http_request_url(url)
    return {
        "method": method,
        "url": safe_url,
        "header_names": sorted(str(key).strip().lower() for key in headers if str(key).strip()),
        "header_value_hashes": _hash_mapping(headers),
        "query_names": sorted(str(key).strip().lower() for key in query if str(key).strip()),
        "query_value_hashes": _hash_mapping(query),
        "body_hash": _hash_value(body) if body is not None else "",
        "has_body": body is not None,
    }


def _http_request_preview_payload(
    method: str,
    url: str,
    headers: dict[str, Any],
    query: dict[str, Any],
    body: Any,
) -> dict[str, Any]:
    parsed = urlsplit(str(url or "").strip())
    safe_url = _safe_http_request_url(url)
    details = [
        f"Outbound request target: `{safe_url}`",
        f"Headers supplied: {len(headers)}",
        f"Query parameters supplied: {len(query)}",
    ]
    if body is not None:
        details.append("Request body supplied.")
    return {
        "kind": "http_request",
        "title": f"{method} outbound HTTP request",
        "summary": f"{method} {safe_url}",
        "method": method,
        "url": safe_url,
        "host": parsed.hostname or "",
        "details": details,
    }


async def _maybe_block_http_request_with_approval(
    method: str,
    url: str,
    headers: dict[str, Any],
    query: dict[str, Any],
    body: Any,
    context: ToolContext,
) -> dict[str, Any] | None:
    if method not in _HTTP_METHODS_REQUIRING_APPROVAL:
        return None
    db = getattr(context, "db", None)
    user_id = getattr(context, "user_id", None)
    session_id = getattr(context, "session_id", None)
    if db is None or not user_id or not session_id:
        return None

    approval_payload = _http_request_approval_payload(method, url, headers, query, body)
    if await consume_change_preview_grant(
        db,
        session_id=session_id,
        tool_name="http_request",
        payload=approval_payload,
    ):
        return None

    preview_payload = _http_request_preview_payload(method, url, headers, query, body)
    approval = await ensure_approval_request(
        db,
        requested_by=user_id,
        session_id=session_id,
        action="Approve outbound HTTP request for http_request",
        reason=preview_payload["summary"],
    )
    preview = await upsert_change_preview(
        db,
        tool_name="http_request",
        preview_payload=preview_payload,
        request_fingerprint=build_change_request_fingerprint("http_request", approval_payload),
        session_id=session_id,
        approval_id=approval.id,
    )
    return {
        "error": "Execution blocked pending outbound HTTP approval.",
        "approval_required": True,
        "approval_id": approval.id,
        "approval_status": approval.status,
        "change_preview_id": preview.id,
        "change_preview": preview_payload,
        "tool_name": "http_request",
    }


class HttpRequestTool:
    """Execute a basic outbound HTTP request and return status, headers, and body preview."""

    name = "http_request"
    description = (
        "Execute a basic outbound HTTP request and return status, headers, and body preview. "
        "Mutating requests require approval when the runtime can track a session."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        method = (params.get("method") or "GET").upper()
        url = params.get("url")
        if not url:
            return {"error": "url is required"}

        headers = params.get("headers") or {}
        query = params.get("query") or {}
        body = params.get("body")
        timeout_sec = int(params.get("timeout_sec") or 30)

        blocked = await _maybe_block_http_request_with_approval(
            method,
            str(url),
            headers,
            query,
            body,
            context,
        )
        if blocked is not None:
            return blocked

        try:
            async with public_web_client(timeout=timeout_sec) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=query,
                    content=body if isinstance(body, str) else json.dumps(body) if body is not None else None,
                )
        except (OutboundURLPolicyError, httpx.HTTPError) as exc:
            return {"error": f"Request failed: {exc}", "method": method, "url": url}

        return {
            "method": method,
            "url": str(response.url),
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": _truncate(response.text),
        }
