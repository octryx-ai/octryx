"""The audit middleware persists request ids and anonymous mutations and logs or writes a JSONL fallback when persisting fails."""

import json
import logging
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from starlette.responses import Response

import app.middleware.audit.request_audit as audit_module
from app.models import AuditLog, User
from tests.support.middleware_support import _build_request, _resolve_user_id


@pytest.mark.asyncio
async def test_audit_middleware_logs_failed_audit_persist(monkeypatch, caplog):
    request = _build_request(
        "/api/test",
        method="POST",
        headers={"Authorization": "Bearer valid"},
    )

    async def next_handler(_request):
        return Response("ok", status_code=201)

    monkeypatch.setattr(audit_module, "resolve_bearer_principal_user_id", _resolve_user_id)

    class FailingAuditSession:
        def add(self, _obj):
            return None

        async def commit(self):
            raise RuntimeError("db down")

    class FailingAuditFactory:
        async def __aenter__(self):
            return FailingAuditSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(audit_module, "async_session_factory", lambda: FailingAuditFactory())

    with caplog.at_level(logging.ERROR):
        response = await audit_module.audit_middleware(request, next_handler)

    assert response.status_code == 201
    assert "Failed to persist audit log entry" in caplog.text


@pytest.mark.asyncio
async def test_audit_middleware_writes_jsonl_fallback_when_db_persist_fails(monkeypatch, tmp_path):
    request = _build_request(
        "/api/test",
        method="POST",
        headers={"Authorization": "Bearer valid", "X-Request-ID": "req-fallback"},
    )
    request.state.request_id = "req-fallback"

    async def next_handler(_request):
        return Response("ok", status_code=201)

    monkeypatch.setattr(audit_module, "resolve_bearer_principal_user_id", _resolve_user_id)
    monkeypatch.setattr(audit_module, "_AUDIT_FALLBACK_FILE", tmp_path / "audit-fallback.jsonl")

    class FailingAuditSession:
        def add(self, _obj):
            return None

        async def commit(self):
            raise RuntimeError("db down")

    class FailingAuditFactory:
        async def __aenter__(self):
            return FailingAuditSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(audit_module, "async_session_factory", lambda: FailingAuditFactory())

    response = await audit_module.audit_middleware(request, next_handler)

    assert response.status_code == 201
    lines = (tmp_path / "audit-fallback.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["request_id"] == "req-fallback"
    assert payload["user_id"] == "user-1"
    assert payload["action"] == "POST /api/test"
    assert payload["status_code"] == 201


@pytest.mark.asyncio
async def test_audit_middleware_persists_request_id(monkeypatch):
    request = _build_request(
        "/api/test",
        method="POST",
        headers={"Authorization": "Bearer valid", "X-Request-ID": "req-999"},
    )
    request.state.request_id = "req-999"

    async def next_handler(_request):
        return Response("ok", status_code=201)

    monkeypatch.setattr(audit_module, "resolve_bearer_principal_user_id", _resolve_user_id)
    captured = {}

    class AuditSession:
        def add(self, obj):
            captured["log"] = obj

        async def commit(self):
            return None

    class AuditFactory:
        async def __aenter__(self):
            return AuditSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(audit_module, "async_session_factory", lambda: AuditFactory())

    response = await audit_module.audit_middleware(request, next_handler)

    assert response.status_code == 201
    assert captured["log"].details["request_id"] == "req-999"


@pytest.mark.asyncio
async def test_audit_middleware_persists_anonymous_mutation_with_audit_principal(monkeypatch, db):
    request = _build_request("/api/test", method="POST", headers={"X-Request-ID": "req-anon"})
    request.state.request_id = "req-anon"

    async def next_handler(_request):
        return Response("ok", status_code=202)

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    monkeypatch.setattr(audit_module, "async_session_factory", fake_session_factory)

    response = await audit_module.audit_middleware(request, next_handler)

    assert response.status_code == 202
    anonymous_user = await db.get(User, "anonymous")
    assert anonymous_user is not None
    assert anonymous_user.is_active is False
    log = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.user_id == "anonymous",
                AuditLog.action == "POST /api/test",
            )
        )
    ).scalar_one()
    assert log.details["request_id"] == "req-anon"
