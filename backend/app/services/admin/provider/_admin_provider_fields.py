"""Field mapping for provider create and update requests."""

from __future__ import annotations

import uuid
from typing import Any

from ....agent.providers import infer_provider_runtime
from ....models import LLMProvider


def build_provider_row(payload: dict[str, Any], *, runtime: dict[str, Any], auth_mode: Any) -> LLMProvider:
    return LLMProvider(
        id=str(uuid.uuid4()),
        name=runtime["name"],
        provider_family=runtime["provider_family"],
        driver=runtime["driver"],
        runtime_kind=runtime["runtime_kind"],
        display_name=str(payload.get("display_name") or runtime["name"]),
        profile_name=str(payload.get("profile_name") or "").strip() or None,
        endpoint_url=str(payload.get("endpoint_url") or "").strip() or None,
        binary_path=str(payload.get("binary_path") or "").strip() or None,
        auth_mode=auth_mode,
        config_json=(payload.get("config_json") if isinstance(payload.get("config_json"), dict) else None),
        capabilities_json=(
            payload.get("capabilities_json") if isinstance(payload.get("capabilities_json"), dict) else None
        ),
        aws_region=payload.get("aws_region") or None,
        aws_role_arn=payload.get("aws_role_arn") or None,
        bootstrap_role=str(payload.get("bootstrap_role") or "").strip() or None,
        is_global=bool(payload.get("is_global", True)),
    )


def apply_descriptive_fields(provider: LLMProvider, payload: dict[str, Any]) -> None:
    if payload.get("display_name") is not None:
        provider.display_name = str(payload["display_name"])
    if payload.get("profile_name") is not None:
        provider.profile_name = str(payload.get("profile_name") or "").strip() or None
    if payload.get("endpoint_url") is not None:
        provider.endpoint_url = str(payload.get("endpoint_url") or "").strip() or None
    if payload.get("binary_path") is not None:
        provider.binary_path = str(payload.get("binary_path") or "").strip() or None
    if payload.get("bootstrap_role") is not None:
        provider.bootstrap_role = str(payload.get("bootstrap_role") or "").strip() or None
    if payload.get("config_json") is not None and isinstance(payload.get("config_json"), dict):
        provider.config_json = dict(payload["config_json"])
    if payload.get("capabilities_json") is not None and isinstance(payload.get("capabilities_json"), dict):
        provider.capabilities_json = dict(payload["capabilities_json"])


def apply_runtime_fields(provider: LLMProvider, payload: dict[str, Any]) -> None:
    if payload.get("driver") is None and payload.get("provider_family") is None and payload.get("runtime_kind") is None:
        return
    runtime = infer_provider_runtime(
        name=provider.name,
        driver=payload.get("driver") or provider.driver,
        provider_family=payload.get("provider_family") or provider.provider_family,
        runtime_kind=payload.get("runtime_kind") or provider.runtime_kind,
        auth_mode=payload.get("auth_mode") or provider.auth_mode,
    )
    if payload.get("name") is not None:
        provider.name = str(payload.get("name") or "").strip().lower() or runtime["name"]
    provider.provider_family = runtime["provider_family"]
    provider.driver = runtime["driver"]
    provider.runtime_kind = runtime["runtime_kind"]


def apply_aws_and_active_fields(provider: LLMProvider, payload: dict[str, Any]) -> None:
    if payload.get("aws_region") is not None:
        provider.aws_region = str(payload["aws_region"]) or None
    if payload.get("aws_role_arn") is not None:
        provider.aws_role_arn = str(payload["aws_role_arn"]) or None
    if payload.get("is_active") is not None:
        provider.is_active = bool(payload["is_active"])
