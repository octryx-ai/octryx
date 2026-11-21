"""Shared constants, errors and digest/signature helpers for signed knowledge packages."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from .federation_export_labels import PACKAGE_EXPORT_CLASSIFICATIONS

PACKAGE_SCHEMA_VERSION = "engineering_knowledge_package.v1"
PACKAGE_SIGNATURE_ALGORITHM = "hmac-sha256"
DEFAULT_EXPORT_CLASSIFICATIONS = set(PACKAGE_EXPORT_CLASSIFICATIONS)
DEFAULT_EXPORT_TRUST_LEVELS = {"gold", "official", "verified"}
BLOCKED_EXPORT_KEY_PARTS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "private_key",
    "raw_log",
    "raw_payload",
    "secret",
    "session_token",
}


class KnowledgePackageValidationError(ValueError):
    """Raised when an Engineering Knowledge package fails validation."""


def _without_signature(package: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(package)
    unsigned.pop("signature", None)
    return unsigned


def _signature_value(package: dict[str, Any], *, signing_key: str) -> str:
    return hmac.new(signing_key.encode("utf-8"), _canonical_json(package), hashlib.sha256).hexdigest()


def _sha256_hex(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _fact_content_digest(fact: dict[str, Any]) -> str:
    return _sha256_hex({key: value for key, value in fact.items() if key not in {"id", "content_digest"}})


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _reject_unsafe_payload(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if any(part in normalized_key for part in BLOCKED_EXPORT_KEY_PARTS):
                raise KnowledgePackageValidationError(f"{path}.{key} contains unsafe raw secret or log field")
            _reject_unsafe_payload(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unsafe_payload(item, path=f"{path}[{index}]")


def _require_signing_key(signing_key: str) -> None:
    if len(str(signing_key or "")) < 16:
        raise KnowledgePackageValidationError("signing_key must be at least 16 characters")
