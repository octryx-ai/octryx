"""AWS CLI gateway policy: operation names, the read/action allowlists and the allowed CLI arguments."""

from __future__ import annotations

import json
import re
from typing import Any

from ..context import ToolContext
from .common import _normalize_string_list, _string

_READ_PREFIXES = ("describe-", "list-", "lookup-", "filter-", "search-")
_AWS_OPERATION_ACRONYMS = ("DB", "EC2", "EKS", "ECS", "ELB", "RDS", "IAM", "VPC", "ACL", "WAF", "IP")
_DENIED_READ_OPERATIONS: set[tuple[str, str]] = {
    ("ecr", "get-login-password"),
    ("s3", "get-object"),
    ("secretsmanager", "get-secret-value"),
    ("ssm", "get-parameter"),
    ("ssm", "get-parameters"),
    ("ssm", "get-parameters-by-path"),
    ("sts", "get-session-token"),
}
_SENSITIVE_OPERATION_FRAGMENTS = ("secret-value", "password", "token")
_DEFAULT_ALLOWED_ACTIONS = {("codepipeline", "start-pipeline-execution")}
_FORBIDDEN_GLOBAL_ARGS = {
    "--profile",
    "--endpoint-url",
    "--cli-input-json",
    "--cli-input-yaml",
    "--generate-cli-skeleton",
    "--debug",
    "--output",
    "--no-cli-pager",
    "--pager",
}


def _normalize_service(value: Any) -> str:
    service = _string(value).lower()
    if not service:
        raise ValueError("service is required")
    if not service.replace("-", "").replace("_", "").isalnum():
        raise ValueError("service must be an AWS service identifier")
    return service.replace("_", "-")


def _normalize_operation(value: Any) -> str:
    raw_operation = _string(value)
    operation = raw_operation.lower()
    if not operation:
        raise ValueError("operation is required")
    if operation.startswith("-") or not operation.replace("-", "").isalnum():
        raise ValueError("operation must be an AWS CLI operation name")
    if "-" in operation:
        return operation
    dashed = raw_operation
    for acronym in _AWS_OPERATION_ACRONYMS:
        dashed = re.sub(rf"({acronym})(?=[A-Z][a-z])", r"\1-", dashed)
    dashed = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", dashed).lower()
    dashed = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "-", dashed).lower()
    return dashed


def _is_denied_read_operation(service: str, operation: str) -> bool:
    if (service, operation) in _DENIED_READ_OPERATIONS:
        return True
    return any(fragment in operation for fragment in _SENSITIVE_OPERATION_FRAGMENTS)


def _is_read_operation_allowed(service: str, operation: str) -> bool:
    if _is_denied_read_operation(service, operation):
        return False
    if operation.startswith(_READ_PREFIXES):
        return True
    if operation.startswith("get-"):
        return True
    return False


def _allowed_actions_from_config(context: ToolContext) -> set[tuple[str, str]]:
    allowed = set(_DEFAULT_ALLOWED_ACTIONS)
    configured = _normalize_string_list(context.project_config.get("aws_allowed_actions"))
    for entry in configured:
        if ":" not in entry:
            continue
        service, operation = entry.split(":", 1)
        allowed.add((_normalize_service(service), _normalize_operation(operation)))
    return allowed


def _append_cli_argument(command: list[str], key: str, value: Any) -> None:
    cli_key = "--" + key.strip().replace("_", "-").lstrip("-")
    if cli_key in _FORBIDDEN_GLOBAL_ARGS:
        raise ValueError(f"AWS CLI argument '{cli_key}' is not allowed")
    if value is None:
        return
    if isinstance(value, bool):
        if value:
            command.append(cli_key)
        return
    command.append(cli_key)
    if isinstance(value, (dict, list)):
        command.append(json.dumps(value, separators=(",", ":")))
    else:
        command.append(str(value))


def _append_arguments(command: list[str], arguments: Any) -> None:
    if arguments is None:
        return
    if isinstance(arguments, dict):
        for key, value in arguments.items():
            _append_cli_argument(command, str(key), value)
        return
    if isinstance(arguments, list):
        for value in arguments:
            text = str(value)
            if text in _FORBIDDEN_GLOBAL_ARGS or any(text.startswith(arg + "=") for arg in _FORBIDDEN_GLOBAL_ARGS):
                raise ValueError(f"AWS CLI argument '{text}' is not allowed")
            command.append(text)
        return
    raise ValueError("arguments must be an object or an array")
