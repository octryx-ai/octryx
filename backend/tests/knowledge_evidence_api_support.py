"""Shared helpers for the test_knowledge_evidence_api_* modules."""

from __future__ import annotations

import pytest

from app.main import app
from app.services.auth import get_current_user
from app.services.knowledge.runtime import set_evidence_runtime
from tests.knowledge_evidence_runtime_support import build_runtime

BASE = "/api/v1/workspaces"


TEXT = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"


@pytest.fixture
def evidence_runtime():
    runtime, s3, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, s3, evidence_index
    finally:
        set_evidence_runtime(None)


@pytest.fixture
def as_user(db):
    """Authenticate the request as a chosen user without minting a token."""

    def _install(user):
        app.dependency_overrides[get_current_user] = lambda: user

    yield _install
    app.dependency_overrides.pop(get_current_user, None)


def _upload(payload: bytes, *, content_type: str = "text/plain", source_key: str = "runbook") -> dict:
    return {
        "files": {"file": ("ignored-name.txt", payload, content_type)},
        "data": {"source_key": source_key, "display_title": "Runbook"},
    }
