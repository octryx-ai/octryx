"""Shared GCP connector helpers."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import time
from pathlib import Path

import httpx

from app.services.outbound_egress import CONNECTION_GCP, egress_transport

from ..context import ToolContext
from .common import _string


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


async def _gcp_access_token(context: ToolContext) -> str:
    token = _string(context.project_config.get("gcp_access_token"))
    if token:
        return token
    raw_json = _string(context.project_config.get("gcp_service_account_json"))
    if not raw_json:
        raise ValueError("No GCP service account JSON configured for this project")
    service_account = json.loads(raw_json)
    private_key = _string(service_account.get("private_key"))
    client_email = _string(service_account.get("client_email"))
    token_uri = _string(service_account.get("token_uri") or "https://oauth2.googleapis.com/token")
    if not private_key or not client_email:
        raise ValueError("GCP service account JSON is incomplete")
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": client_email,
        "scope": "https://www.googleapis.com/auth/cloud-platform.read-only",
        "aud": token_uri,
        "exp": now + 3600,
        "iat": now,
    }
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode('utf-8'))}.{_b64url(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
    openssl_bin = "/usr/bin/openssl"
    if not Path(openssl_bin).exists():
        openssl_bin = "openssl"
    if not (Path(openssl_bin).exists() or Path("/usr/bin/openssl").exists()):
        raise ValueError("openssl is not available for GCP token signing")

    # Write the private key to temp file with 0o600 permissions.
    # The file is created with a secure name prefix, permissions set atomically
    # before content is written, and deleted immediately after use.
    key_fd = None
    key_path = None
    try:
        key_fd, key_path = tempfile.mkstemp(prefix="gcp_key_", suffix=".pem")
        os.fchmod(key_fd, 0o600)
        os.write(key_fd, private_key.encode("utf-8"))
        os.fsync(key_fd)
        os.close(key_fd)
        key_fd = None  # ownership transferred

        process = await asyncio.create_subprocess_exec(
            openssl_bin,
            "dgst",
            "-sha256",
            "-sign",
            key_path,
            "-binary",
            stdout=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate(signing_input.encode("utf-8"))
        if process.returncode != 0:
            # openssl stderr can name the temporary key path; only the exit status is kept.
            raise ValueError(f"openssl_signing_failed exit_code={process.returncode}")
    finally:
        if key_fd is not None:
            try:
                os.close(key_fd)
            except OSError:
                pass
        if key_path is not None:
            try:
                Path(key_path).unlink(missing_ok=True)
            except OSError:
                pass
    assertion = f"{signing_input}.{_b64url(stdout)}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GCP)) as client:
        response = await client.post(
            token_uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
        )
    response.raise_for_status()
    data = response.json()
    access_token = _string(data.get("access_token"))
    if not access_token:
        raise ValueError("Failed to obtain GCP access token")
    return access_token


def _gcp_resourcemanager_base_url(context: ToolContext) -> str:
    return _string(
        context.project_config.get("gcp_resourcemanager_url") or "https://cloudresourcemanager.googleapis.com"
    ).rstrip("/")


def _gcp_container_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("gcp_gke_url") or "https://container.googleapis.com").rstrip("/")


def _gcp_compute_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("gcp_compute_url") or "https://compute.googleapis.com").rstrip("/")


def _gcp_logging_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("gcp_logging_url") or "https://logging.googleapis.com").rstrip("/")


def _gcp_sqladmin_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("gcp_sqladmin_url") or "https://sqladmin.googleapis.com").rstrip("/")


def _gcp_monitoring_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("gcp_monitoring_url") or "https://monitoring.googleapis.com").rstrip("/")


def _gcp_run_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("gcp_run_url") or "https://run.googleapis.com").rstrip("/")
