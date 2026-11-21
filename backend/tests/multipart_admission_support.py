"""Shared helpers for the test_multipart_admission_* modules."""

from __future__ import annotations

from app.config import Settings
from app.multipart_admission_policy import MIN_MULTIPART_REQUEST_BYTES

BOUNDARY = "----------------------------820"


MULTIPART_CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"


WORKSPACE_PATH = "/api/v1/workspaces/0dcb1bfe-55c3-4d2a-9f01-2f0d9f0a1c77/knowledge/sources"


OTHER_MULTIPART_PATH = "/chat/api/panel/office-templates/upload"


# The lowest ceiling the configuration accepts, so the boundary tests run against
# a legal production configuration rather than an invented one.
LIMIT = MIN_MULTIPART_REQUEST_BYTES


CHUNK = 16 * 1024


OVERSIZE_CHUNKS = LIMIT // CHUNK + 2


def _settings(**overrides) -> Settings:
    """Startup-valid Settings with secure, non-placeholder values."""
    values: dict[str, object] = {
        "debug": False,
        "runtime_profile": "local",
        "jwt_secret": "s" * 48,
        "encryption_key": "e" * 32,
        "admin_default_password": "S3cureAdminPass!",
        "admin_email": "admin@octryx.local",
        "cors_allowed_origins": "https://octryx.example",
        "force_secure_auth_cookies": True,
    }
    values.update(overrides)
    return Settings(**values)


def _part_header(*, field: str = "file", file_name: str = "runbook.txt") -> bytes:
    """One complete multipart part header, so a streamed body stays well-formed."""
    return (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{file_name}"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode()
