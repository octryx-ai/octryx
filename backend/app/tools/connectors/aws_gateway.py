"""Controlled AWS CLI gateway tools backed by IRSA/runtime AWS credentials."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from ...services.process_output_redaction import redact_process_output
from ..context import ToolContext
from .aws_core import _aws_env
from .aws_gateway_policy import (
    _allowed_actions_from_config,
    _append_arguments,
    _is_read_operation_allowed,
    _normalize_operation,
    _normalize_service,
)
from .cloud_common import _aws_allowed, _maybe_block_connector_action_with_approval, _run_subprocess
from .common import _string

_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_TIMEOUT_SECONDS = 120
_DEFAULT_MAX_ITEMS = 100
_MAX_ITEMS = 500
_MAX_STRING_CHARS = 4000


def _bounded_int(raw: Any, *, default: int, maximum: int) -> int:
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(1, min(value, maximum))


def _truncate(value: Any, *, max_items: int, depth: int = 0) -> Any:
    if depth > 8:
        return {"truncated": True, "reason": "max_depth"}
    if isinstance(value, dict):
        return {str(key): _truncate(item, max_items=max_items, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        result = [_truncate(item, max_items=max_items, depth=depth + 1) for item in value[:max_items]]
        if len(value) > max_items:
            result.append({"truncated": True, "remaining_items": len(value) - max_items})
        return result
    if isinstance(value, str):
        # The CLI result is the product the agent asked for; string leaves go through the redactor.
        return redact_process_output(value, max_chars=_MAX_STRING_CHARS)
    return value


def _parse_stdout(stdout: str, *, max_items: int) -> Any:
    if not stdout.strip():
        return {}
    try:
        return _truncate(json.loads(stdout), max_items=max_items)
    except json.JSONDecodeError:
        return {
            "text": redact_process_output(stdout[:_MAX_STRING_CHARS]),
            "truncated": len(stdout) > _MAX_STRING_CHARS,
        }


async def _run_aws_cli(
    context: ToolContext,
    service: str,
    operation: str,
    arguments: Any,
    *,
    timeout_seconds: int,
    max_items: int,
) -> dict[str, Any]:
    if not _aws_allowed(context, service):
        return {"error": f"AWS service '{service}' is not allowed"}
    command = ["aws", service, operation]
    try:
        _append_arguments(command, arguments)
    except ValueError as exc:
        return {"error": str(exc), "service": service, "operation": operation}
    command.extend(["--output", "json", "--no-cli-pager"])
    env = os.environ.copy()
    env.update(await _aws_env(context))
    if env.get("HOME") in (None, "", "/"):
        env["HOME"] = "/tmp"
    env.setdefault("AWS_PAGER", "")

    try:
        return_code, stdout, stderr = await asyncio.wait_for(
            _run_subprocess(command, env=env),
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return {"error": "AWS CLI is not installed in the runtime image"}
    except TimeoutError:
        return {
            "error": "AWS CLI command timed out",
            "service": service,
            "operation": operation,
            "timeout_seconds": timeout_seconds,
        }

    if return_code != 0:
        return {
            "error": "AWS CLI command failed",
            "service": service,
            "operation": operation,
            "return_code": return_code,
            # Kept for the agent to debug its own call (AccessDenied, bad argument); redacted first.
            "stderr": redact_process_output(stderr[-_MAX_STRING_CHARS:]),
        }
    return {
        "service": service,
        "operation": operation,
        "timeout_seconds": timeout_seconds,
        "result": _parse_stdout(stdout, max_items=max_items),
    }


class AwsReadOperationTool:
    name = "aws_read_operation"
    description = (
        "Run a constrained read-only AWS CLI operation using runtime IRSA credentials. "
        "Allowed operations include list/describe/lookup/filter/search and safe get operations; secret-value reads and "
        "mutating actions are blocked."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            service = _normalize_service(params.get("service"))
            operation = _normalize_operation(params.get("operation"))
        except ValueError as exc:
            return {"error": str(exc)}
        if not _is_read_operation_allowed(service, operation):
            return {
                "error": "AWS operation is not allowed for read-only execution",
                "service": service,
                "operation": operation,
            }
        return await _run_aws_cli(
            context,
            service,
            operation,
            params.get("arguments"),
            timeout_seconds=_bounded_int(
                params.get("timeout_seconds"),
                default=_DEFAULT_TIMEOUT_SECONDS,
                maximum=_MAX_TIMEOUT_SECONDS,
            ),
            max_items=_bounded_int(params.get("max_items"), default=_DEFAULT_MAX_ITEMS, maximum=_MAX_ITEMS),
        )


class AwsActionOperationTool:
    name = "aws_action_operation"
    description = (
        "Run an explicitly allowed AWS mutating operation using runtime IRSA credentials after Octryx approval. "
        "Default allowed action: codepipeline:start-pipeline-execution."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            service = _normalize_service(params.get("service"))
            operation = _normalize_operation(params.get("operation"))
        except ValueError as exc:
            return {"error": str(exc)}
        allowed_actions = _allowed_actions_from_config(context)
        if (service, operation) not in allowed_actions:
            return {
                "error": "AWS action is not in the explicit action allowlist",
                "service": service,
                "operation": operation,
                "allowed_actions": [f"{svc}:{op}" for svc, op in sorted(allowed_actions)],
            }
        blocked = await _maybe_block_connector_action_with_approval(
            self.name,
            params,
            context,
            title="AWS action execution",
            summary=f"Run AWS action {service}:{operation}",
            details=[_string(params.get("reason") or "No reason supplied")],
        )
        if blocked:
            return blocked
        return await _run_aws_cli(
            context,
            service,
            operation,
            params.get("arguments"),
            timeout_seconds=_bounded_int(
                params.get("timeout_seconds"),
                default=_DEFAULT_TIMEOUT_SECONDS,
                maximum=_MAX_TIMEOUT_SECONDS,
            ),
            max_items=_bounded_int(params.get("max_items"), default=_DEFAULT_MAX_ITEMS, maximum=_MAX_ITEMS),
        )
