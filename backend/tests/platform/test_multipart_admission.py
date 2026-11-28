"""Multipart admission before any parser sees the body: the configuration contract, the ASGI boundary, and
the real application, where an oversized unauthenticated upload reaches neither the parser nor the route."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.multipart_admission_policy import (
    DEFAULT_MULTIPART_REQUEST_BYTES,
    GLOBAL_ROUTE_POLICY,
    KNOWLEDGE_EVIDENCE_PAYLOAD_BYTES,
    KNOWLEDGE_EVIDENCE_REQUEST_BYTES,
    KNOWLEDGE_EVIDENCE_UPLOAD_ROUTE,
    LARGEST_ROUTE_PAYLOAD_BYTES,
    MAX_MULTIPART_REQUEST_BYTES,
    MIN_MULTIPART_REQUEST_BYTES,
    MULTIPART_ENVELOPE_ALLOWANCE_BYTES,
    MultipartAdmissionConfigError,
    resolve_request_limit,
    route_path,
    validate_multipart_request_bytes,
)
from app.services.knowledge.ingestion.text_ingest import MAX_UPLOAD_BYTES
from tests.support.multipart_admission_support import LIMIT, OTHER_MULTIPART_PATH, WORKSPACE_PATH, _settings


def test_the_default_ceiling_covers_every_upload_route_the_product_accepts():
    assert DEFAULT_MULTIPART_REQUEST_BYTES == LARGEST_ROUTE_PAYLOAD_BYTES + MULTIPART_ENVELOPE_ALLOWANCE_BYTES
    assert _settings().max_multipart_request_bytes == DEFAULT_MULTIPART_REQUEST_BYTES
    assert DEFAULT_MULTIPART_REQUEST_BYTES > KNOWLEDGE_EVIDENCE_REQUEST_BYTES


def test_the_knowledge_route_ceiling_tracks_the_service_payload_limit():
    assert KNOWLEDGE_EVIDENCE_PAYLOAD_BYTES == MAX_UPLOAD_BYTES
    assert KNOWLEDGE_EVIDENCE_REQUEST_BYTES == MAX_UPLOAD_BYTES + MULTIPART_ENVELOPE_ALLOWANCE_BYTES


@pytest.mark.parametrize(
    "value",
    [0, -1, MIN_MULTIPART_REQUEST_BYTES - 1, MAX_MULTIPART_REQUEST_BYTES + 1, "8mb", 1.5, None],
)
@pytest.mark.parametrize("profile", ["local", "production"])
def test_an_invalid_or_unbounded_ceiling_fails_startup_in_every_profile(value, profile):
    overrides: dict[str, object] = {"max_multipart_request_bytes": value, "runtime_profile": profile}
    if profile == "production":
        overrides["database_url"] = "postgresql+asyncpg://oe:pw@db:5432/oe"
    with pytest.raises(ValidationError):
        _settings(**overrides)


def test_debug_does_not_weaken_the_ceiling_validation():
    with pytest.raises(ValidationError):
        _settings(debug=True, runtime_profile="local", max_multipart_request_bytes=0)


def test_the_rejection_message_never_echoes_the_configured_value():
    with pytest.raises(MultipartAdmissionConfigError) as error:
        validate_multipart_request_bytes(7)
    assert "7" not in str(error.value).replace(str(MIN_MULTIPART_REQUEST_BYTES), "")


def test_a_route_ceiling_applies_under_an_ingress_root_path():
    prefixed = f"/gateway{WORKSPACE_PATH}"
    assert route_path(prefixed, "/gateway") == WORKSPACE_PATH
    assert resolve_request_limit(
        route_path(prefixed, "/gateway"), global_limit=DEFAULT_MULTIPART_REQUEST_BYTES
    ) == (KNOWLEDGE_EVIDENCE_UPLOAD_ROUTE, KNOWLEDGE_EVIDENCE_REQUEST_BYTES)
    assert route_path(WORKSPACE_PATH, "") == WORKSPACE_PATH


def test_a_route_ceiling_never_raises_the_global_one():
    assert resolve_request_limit(WORKSPACE_PATH, global_limit=DEFAULT_MULTIPART_REQUEST_BYTES) == (
        KNOWLEDGE_EVIDENCE_UPLOAD_ROUTE,
        KNOWLEDGE_EVIDENCE_REQUEST_BYTES,
    )
    assert resolve_request_limit(WORKSPACE_PATH, global_limit=LIMIT) == (KNOWLEDGE_EVIDENCE_UPLOAD_ROUTE, LIMIT)
    assert resolve_request_limit(OTHER_MULTIPART_PATH, global_limit=LIMIT) == (GLOBAL_ROUTE_POLICY, LIMIT)
