"""Core update handlers for admin runtime settings."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...system_config import (
    AGENT_AUTH_LOGIN_MODE_KEY,
    ARTIFACT_STORE_BACKEND_KEY,
    ARTIFACT_STORE_BUCKET_KEY,
    ARTIFACT_STORE_PREFIX_KEY,
    ARTIFACT_STORE_S3_ENDPOINT_URL_KEY,
    ARTIFACT_STORE_S3_REGION_KEY,
    set_system_config_value,
)
from ._admin_runtime_fallback_policy import apply_runtime_fallback_mode_setting
from ._admin_runtime_update_limits import (
    AGENT_LIMIT_SETTINGS,
    COST_LIMIT_SETTINGS,
    apply_bounded_settings,
)


async def apply_core_runtime_settings(db: AsyncSession, *, payload: dict[str, Any]) -> None:
    # The groups run in this order on purpose: a refused value leaves every later setting unwritten.
    await _apply_model_and_login_settings(db, payload)
    await apply_bounded_settings(db, payload, AGENT_LIMIT_SETTINGS)
    # Closed-enum setting with its own writer and validation.
    await apply_runtime_fallback_mode_setting(db, payload=payload)
    await apply_bounded_settings(db, payload, COST_LIMIT_SETTINGS)
    await _apply_artifact_store_settings(db, payload)


async def _apply_model_and_login_settings(db: AsyncSession, payload: dict[str, Any]) -> None:
    if "auth_oidc_only" in payload:
        await set_system_config_value(
            db,
            key=AGENT_AUTH_LOGIN_MODE_KEY,
            value="true" if bool(payload.get("auth_oidc_only")) else None,
            description="Allow login only through configured OIDC providers when enabled.",
        )


async def _apply_artifact_store_settings(db: AsyncSession, payload: dict[str, Any]) -> None:
    if "artifact_store_backend" in payload:
        value = str(payload.get("artifact_store_backend") or "filesystem").strip().lower()
        if value not in {"filesystem", "s3", "gcs"}:
            raise HTTPException(status_code=400, detail="artifact_store_backend must be one of: filesystem, s3, gcs")
        await set_system_config_value(
            db,
            key=ARTIFACT_STORE_BACKEND_KEY,
            value=value,
            description="Artifact store backend: filesystem, s3, or gcs",
        )
    if "artifact_store_bucket" in payload:
        await set_system_config_value(
            db,
            key=ARTIFACT_STORE_BUCKET_KEY,
            value=str(payload.get("artifact_store_bucket") or "").strip() or None,
            description="S3/GCS bucket name for artifact storage",
        )
    if "artifact_store_prefix" in payload:
        await set_system_config_value(
            db,
            key=ARTIFACT_STORE_PREFIX_KEY,
            value=str(payload.get("artifact_store_prefix") or "").strip().strip("/") or None,
            description="Prefix path within the artifact store bucket",
        )
    if "artifact_store_s3_region" in payload:
        await set_system_config_value(
            db,
            key=ARTIFACT_STORE_S3_REGION_KEY,
            value=str(payload.get("artifact_store_s3_region") or "").strip() or None,
            description="AWS region for S3 artifact store",
        )
    if "artifact_store_s3_endpoint_url" in payload:
        await set_system_config_value(
            db,
            key=ARTIFACT_STORE_S3_ENDPOINT_URL_KEY,
            value=str(payload.get("artifact_store_s3_endpoint_url") or "").strip() or None,
            description="Custom S3 endpoint URL (for MinIO or S3-compatible storage)",
        )
