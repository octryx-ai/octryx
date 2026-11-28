"""Fixed results for connector connection tests."""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..outbound_egress import EgressRefusedError

REASON_HTTP_STATUS = "http_status_error"
REASON_COMMAND_FAILED = "command_failed"
REASON_EGRESS_REFUSED = "egress_refused"
REASON_TIMEOUT = "timeout"
REASON_TRANSPORT = "transport_error"
REASON_UNEXPECTED = "unexpected_error"

CONNECTION_TEST_FAILURE_REASONS = frozenset(
    {
        REASON_HTTP_STATUS,
        REASON_COMMAND_FAILED,
        REASON_EGRESS_REFUSED,
        REASON_TIMEOUT,
        REASON_TRANSPORT,
        REASON_UNEXPECTED,
    }
)

RERUN_HINT = "Check the connector configuration, then run the connection test again."

_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_SAFE_FACT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Digits and dots only, with an optional leading ``v`` (``v1.30.0``); nothing else passes.
_STRICT_VERSION = re.compile(r"^v?(\d{1,6}(?:\.\d{1,6}){0,3})$")


def _safe_name(value: str, fallback: str) -> str:
    return value if _SAFE_NAME.match(value or "") else fallback


def _failure(
    summary: str,
    *,
    reason: str,
    error_type: str | None = None,
    http_status: int | None = None,
    exit_code: int | None = None,
) -> dict[str, Any]:
    facts = [f"reason={reason}"]
    if error_type:
        facts.append(f"error_type={error_type}")
    if http_status is not None:
        facts.append(f"http_status={http_status}")
    if exit_code is not None:
        facts.append(f"exit_code={exit_code}")
    result: dict[str, Any] = {
        "ok": False,
        "summary": summary,
        "reason": reason,
        "error_type": error_type,
        "http_status": http_status,
        "details": f"{' '.join(facts)}. {RERUN_HINT}",
    }
    if exit_code is not None:
        result["exit_code"] = exit_code
    return result


def http_status_failure(service: str, status_code: int) -> dict[str, Any]:
    status = int(status_code)
    return _failure(f"{service} returned HTTP {status}.", reason=REASON_HTTP_STATUS, http_status=status)


def command_failure(service: str, exit_code: int) -> dict[str, Any]:
    code = int(exit_code)
    return _failure(f"{service} probe command failed.", reason=REASON_COMMAND_FAILED, exit_code=code)


def runtime_facts(metadata: Any) -> dict[str, Any]:
    meta = metadata if isinstance(metadata, dict) else {}
    return {
        "provider": _safe_name(str(meta.get("provider") or ""), "unknown"),
        "containerized": bool(meta.get("containerized")),
        "host_fallback": bool(meta.get("host_fallback")),
    }


def _exception_reason(exc: BaseException) -> str:
    if isinstance(exc, EgressRefusedError):
        return REASON_EGRESS_REFUSED
    if isinstance(exc, httpx.HTTPStatusError):
        return REASON_HTTP_STATUS
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return REASON_TIMEOUT
    if isinstance(exc, httpx.TransportError | ConnectionError):
        return REASON_TRANSPORT
    return REASON_UNEXPECTED


def exception_failure(service: str, exc: BaseException) -> dict[str, Any]:
    http_status = None
    if isinstance(exc, httpx.HTTPStatusError):
        http_status = int(exc.response.status_code)
    return _failure(
        f"{_safe_name(service, 'Connector')} connection test failed.",
        reason=_exception_reason(exc),
        error_type=_safe_name(type(exc).__name__, "Exception"),
        http_status=http_status,
    )


def strict_version(value: Any) -> str | None:
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        return None
    match = _STRICT_VERSION.fullmatch(str(value).strip())
    return match.group(1) if match else None


def closed_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def connection_success(
    summary: str,
    *,
    version: Any = None,
    counts: dict[str, Any] | None = None,
    execution_runtime: Any = None,
) -> dict[str, Any]:
    facts: list[str] = []
    checked_version = strict_version(version)
    if checked_version:
        facts.append(f"version={checked_version}")
    checked_counts: dict[str, int] = {}
    for name, value in (counts or {}).items():
        count = closed_count(value)
        if _SAFE_FACT_NAME.match(name) and count is not None:
            checked_counts[name] = count
            facts.append(f"{name}={count}")
    result: dict[str, Any] = {
        "ok": True,
        "summary": summary,
        "version": checked_version,
        "counts": checked_counts,
        "details": f"{' '.join(facts)}." if facts else None,
    }
    if execution_runtime is not None:
        result["execution_runtime"] = runtime_facts(execution_runtime)
    return result
