"""Shared AWS connector helpers – boto3 based (no CLI dependency)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import boto3

from ..context import ToolContext
from .cloud_common import _aws_allowed
from .common import _string


def _aws_credential_kwargs(config: dict[str, Any]) -> dict[str, str]:
    access_key_id = _string(config.get("aws_access_key_id"))
    secret_access_key = _string(config.get("aws_secret_access_key"))
    session_token = _string(config.get("aws_session_token"))
    if not access_key_id and not secret_access_key:
        return {}
    if not access_key_id or not secret_access_key:
        raise ValueError("AWS access key id and secret access key must be configured together")
    credentials = {
        "aws_access_key_id": access_key_id,
        "aws_secret_access_key": secret_access_key,
    }
    if session_token:
        credentials["aws_session_token"] = session_token
    return credentials


def _get_boto_session(context: ToolContext) -> boto3.Session:
    """Create a boto3 session respecting connector config and IRSA env vars."""
    region = (
        _string(context.project_config.get("aws_region"))
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )
    profile = _string(context.project_config.get("aws_profile"))
    credential_kwargs = _aws_credential_kwargs(context.project_config)
    kwargs: dict[str, Any] = dict(credential_kwargs)
    if region:
        kwargs["region_name"] = region
    if profile and not credential_kwargs:
        kwargs["profile_name"] = profile
    return boto3.Session(**kwargs)


async def _assume_role_if_needed(context: ToolContext, session: boto3.Session) -> boto3.Session:
    """If aws_role_arn is configured, assume that role and return a new session."""
    role_arn = _string(context.project_config.get("aws_role_arn"))
    if not role_arn:
        return session
    region = _string(context.project_config.get("aws_region")) or os.environ.get("AWS_REGION")
    sts = session.client("sts")
    response = await asyncio.to_thread(
        sts.assume_role,
        RoleArn=role_arn,
        RoleSessionName="octryx-session",
    )
    credentials = response.get("Credentials", {})
    kwargs: dict[str, Any] = {
        "aws_access_key_id": credentials["AccessKeyId"],
        "aws_secret_access_key": credentials["SecretAccessKey"],
        "aws_session_token": credentials["SessionToken"],
    }
    if region:
        kwargs["region_name"] = region
    return boto3.Session(**kwargs)


async def _aws_env(context: ToolContext) -> dict[str, str]:
    """Return the AWS environment (region, credentials) for tools that run the AWS CLI in a subprocess."""
    env: dict[str, str] = {}
    region = _string(context.project_config.get("aws_region")) or os.environ.get("AWS_REGION", "")
    if region:
        env["AWS_REGION"] = region
        env["AWS_DEFAULT_REGION"] = region
    if _string(context.project_config.get("aws_role_arn")):
        # The CLI paths assume the configured role like the boto paths do: never the host's own
        # credentials in its place.
        session = await _assume_role_if_needed(context, _get_boto_session(context))
        credentials = await asyncio.to_thread(session.get_credentials)
        if credentials is None:
            # botocore returns None when no credential resolves; never continue with the host's env instead.
            raise ValueError("The configured AWS role yielded no credentials; nothing ran.")
        frozen = credentials.get_frozen_credentials()
        env["AWS_ACCESS_KEY_ID"] = frozen.access_key
        env["AWS_SECRET_ACCESS_KEY"] = frozen.secret_key
        if frozen.token:
            env["AWS_SESSION_TOKEN"] = frozen.token
        return env
    credential_kwargs = _aws_credential_kwargs(context.project_config)
    if credential_kwargs:
        env["AWS_ACCESS_KEY_ID"] = credential_kwargs["aws_access_key_id"]
        env["AWS_SECRET_ACCESS_KEY"] = credential_kwargs["aws_secret_access_key"]
        session_token = credential_kwargs.get("aws_session_token")
        if session_token:
            env["AWS_SESSION_TOKEN"] = session_token
        return env
    # When IRSA is active, the env vars are already set by the pod
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_ROLE_ARN",
    ):
        val = os.environ.get(key, "")
        if val:
            env[key] = val
    return env


# Mapping from CLI service name to boto3 service name
_SERVICE_MAP: dict[str, str] = {
    "acm": "acm",
    "bedrock": "bedrock",
    "ce": "ce",
    "cloudtrail": "cloudtrail",
    "cloudwatch": "cloudwatch",
    "config": "config",
    "configservice": "config",
    "codepipeline": "codepipeline",
    "dynamodb": "dynamodb",
    "ec2": "ec2",
    "eks": "eks",
    "elasticache": "elasticache",
    "elbv2": "elbv2",
    "lambda": "lambda",
    "logs": "logs",
    "rds": "rds",
    "s3": "s3",
    "secretsmanager": "secretsmanager",
    "sts": "sts",
    "support": "support",
    "wafv2": "wafv2",
}

# Mapping from CLI subcommand to boto3 method name (kebab-case → snake_case)
def _cli_to_method(subcommand: str) -> str:
    return subcommand.replace("-", "_")


def _pascal_key(option: str) -> str:
    """``--metric-name`` becomes boto3's ``MetricName``."""
    return "".join(part.capitalize() for part in option[2:].split("-"))


def _kv_pairs(value: str) -> dict[str, str]:
    """``Name=DBInstanceIdentifier,Value=mydb`` becomes ``{"Name": ..., "Value": ...}``."""
    pairs: dict[str, str] = {}
    for part in value.split(","):
        if "=" in part:
            key, item = part.split("=", 1)
            pairs[key] = item
    return pairs


def _store_option(params: dict[str, Any], pascal_key: str, args: list[str], index: int) -> int:
    """Store the value(s) starting at ``args[index]``; returns the index of the last value consumed."""
    value = args[index]
    if "=" in value and "," in value:
        if pascal_key in ("Dimensions", "GroupBy"):
            params.setdefault(pascal_key, []).append(_kv_pairs(value))
        elif pascal_key == "TimePeriod":
            params[pascal_key] = _kv_pairs(value)
        else:
            params[pascal_key] = value
        return index
    if "=" in value and pascal_key in ("LookupAttributes",):
        params.setdefault(pascal_key, []).append(_kv_pairs(value))
        return index
    # Collect multiple values for the same key (e.g. --instance-ids i-1 i-2)
    values = [value]
    while index + 1 < len(args) and not args[index + 1].startswith("--"):
        index += 1
        values.append(args[index])
    if len(values) > 1:
        params[pascal_key] = values
        return index
    try:
        params[pascal_key] = int(values[0])
    except ValueError:
        params[pascal_key] = values[0]
    return index


def _parse_cli_args(args: list[str]) -> tuple[str, dict[str, Any]]:
    """Parse CLI-style arguments into (operation, kwargs) for boto3.

    Handles patterns like:
      ["list-clusters"]
      ["describe-instances"]
      ["get-metric-statistics", "--namespace", "AWS/RDS", "--metric-name", "CPUUtilization", ...]
    """
    if not args:
        raise ValueError("No command arguments provided")

    operation = args[0]
    params: dict[str, Any] = {}
    i = 1
    while i < len(args):
        arg = args[i]
        if not arg.startswith("--"):
            i += 1
            continue
        pascal_key = _pascal_key(arg)
        i += 1
        if i < len(args) and not args[i].startswith("--"):
            i = _store_option(params, pascal_key, args, i) + 1
        else:
            params[pascal_key] = True
    return operation, params


async def _aws_json(context: ToolContext, service: str, command: list[str]) -> Any:
    """Execute an AWS API call using boto3 instead of the CLI.

    Translates CLI-style commands to boto3 method calls.
    """
    if not _aws_allowed(context, service):
        raise ValueError(f"AWS service '{service}' is not allowed")

    boto_service = _SERVICE_MAP.get(service, service)
    session = _get_boto_session(context)
    session = await _assume_role_if_needed(context, session)

    client = session.client(boto_service)
    operation, params = _parse_cli_args(command)
    method_name = _cli_to_method(operation)

    # Remove --output and --region if they ended up in params
    params.pop("Output", None)
    params.pop("Region", None)

    # Services that use camelCase/lowercase instead of PascalCase
    if boto_service in ("logs", "codepipeline", "eks", "support"):
        params = {k[0].lower() + k[1:]: v for k, v in params.items()}
    if boto_service == "wafv2" and "WebAclArn" in params:
        params["WebACLArn"] = params.pop("WebAclArn")

    # CloudWatch Statistics must be a list
    if boto_service == "cloudwatch" and "Statistics" in params:
        val = params["Statistics"]
        if isinstance(val, str):
            params["Statistics"] = [val]
    if boto_service == "ce" and "Metrics" in params:
        val = params["Metrics"]
        if isinstance(val, str):
            params["Metrics"] = [val]

    method = getattr(client, method_name, None)
    if method is None:
        raise ValueError(f"Unknown operation '{operation}' for service '{service}'")

    response = await asyncio.to_thread(method, **params)
    # Remove ResponseMetadata from output (like CLI does)
    if isinstance(response, dict):
        response.pop("ResponseMetadata", None)
    return _sanitize_datetimes(response)


def _sanitize_datetimes(obj: Any) -> Any:
    """Recursively convert datetime objects to ISO format strings for JSON safety."""
    from datetime import date as _date
    from datetime import datetime as _dt

    if isinstance(obj, _dt):
        return obj.isoformat()
    if isinstance(obj, _date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _sanitize_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_datetimes(item) for item in obj]
    return obj
