from __future__ import annotations

import base64
import uuid

import pytest

from app.models import APIKey, ComplianceAuditRecord, Project, UserProject
from app.models.security.compliance_audit import AUDIT_ADMIN_CHANGE, AUDIT_CONNECTOR_ACCESS, AUDIT_RUNTIME_ACTION
from app.services.api_key.service import _hash_api_key, generate_api_key_value
from app.services.compliance_audit.redaction import REDACTED, redact_details
from app.services.compliance_audit.service import (
    create_audit_record,
    create_evidence_package,
    export_evidence_package,
    seal_evidence_package,
)
from app.services.project.private_workspace import PRIVATE_ACCESS_MODE
from app.time_utils import utc_now
from tests.policy_engine_support import bearer, make_user

RECORDS = "/api/v1/admin/compliance-audit/records"
KINDS = "/api/v1/admin/compliance-audit/kinds"
FAKE_KEY = "-".join(["k", "0123456789"])
SECRETS = ("hunter2-pass", "ghp_" + "a" * 36, "sess=abc123", "s3cr3t-value", FAKE_KEY, "pw-in-url")
NESTED = {
    "server": "tracker",
    "steps": [{"calls": [{"request": {"headers": [{"Authorization": "Basic hunter2-pass"}]}}]}],
    "clientSecret": "s3cr3t-value",
    "upstream": {"Cookie": "sess=abc123", "X-Api-Key": FAKE_KEY, "signing_key": FAKE_KEY},
    "note": "pushed with " + "ghp_" + "a" * 36,
    "remote": "postgres://svc:pw-in-url@db.internal/app",
    "tools": ["search", "fetch"],
}


async def _workspace(db, **fields) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True, **fields)
    db.add(project)
    await db.flush()
    return project


async def _key(db, user_id: str, *, scopes: list[str], project_id: str | None = None) -> dict[str, str]:
    raw, prefix = generate_api_key_value()
    db.add(APIKey(user_id=user_id, project_id=project_id, key_hash=_hash_api_key(raw), key_prefix=prefix,
                  name="audit", scopes=scopes))
    await db.commit()
    return {"X-API-Key": raw}


def _assert_clean(text: str) -> None:
    leaked = [secret for secret in SECRETS if secret in text]
    assert not leaked, leaked


def test_redaction_reaches_every_level_and_every_credential_shape():
    clean, fields = redact_details(NESTED)
    _assert_clean(str(clean))
    assert clean["server"] == "tracker" and clean["tools"] == ["search", "fetch"]
    assert clean["upstream"]["X-Api-Key"] == REDACTED and clean["clientSecret"] == REDACTED
    assert "steps[0].calls[0].request.headers[0].Authorization" in fields
    assert "remote" in fields and "note" in fields


FIXED_UUID = "5f0c2a9e-3b71-4d8e-a6f4-0c9d2e7b1a33"
OPAQUE = "".join(["Zx81", "qPw0", "Lm4T", "vB72", "Ys9K"])


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type,resource_type", [
    (AUDIT_CONNECTOR_ACCESS, "connector"),
    (AUDIT_CONNECTOR_ACCESS, "mcp_server_registration"),
])
async def test_a_stored_record_shows_no_unknown_key_or_secret_in_the_api_or_the_export(client, db, event_type,
                                                                                       resource_type):
    admin = await make_user(db, admin=True)
    ws = await _workspace(db)
    details = {**NESTED, "session_ref": OPAQUE, "owner_scope": OPAQUE, "action": "Bearer " + OPAQUE,
               "revision": "7"}
    db.add(ComplianceAuditRecord(id=str(uuid.uuid4()), project_id=ws.id, event_type=event_type,
                                 resource_type=resource_type, details=details, contains_sensitive=False,
                                 redacted_fields=["session_ref", OPAQUE]))
    await db.commit()

    response = await client.get(RECORDS, params={"workspace_id": ws.id}, headers=bearer(admin))
    assert response.status_code == 200
    _assert_clean(response.text)
    assert OPAQUE not in response.text and "session_ref" not in response.text and "upstream" not in response.text
    [row] = response.json()["records"]
    assert row["details"] == {} and row["hidden_field_count"] == len(details)

    package = await create_evidence_package(db, name="review", project_id=ws.id)
    await seal_evidence_package(db, package.id)
    exported = str(await export_evidence_package(db, package.id))
    _assert_clean(exported)
    assert OPAQUE not in exported and "session_ref" not in exported


MCP = "mcp_server_registration"
RECOVERY = "knowledge_projection_outbox"
WRITER_VALUES = {
    MCP: {"action": "connection_failed", "owner_scope": "platform", "revision": 4, "credential_binding_count": 0},
    RECOVERY: {"operation": "retry_now", "previous_state": "dead_letter", "result": "retry_scheduled"},
}
EVENT = {MCP: AUDIT_CONNECTOR_ACCESS, RECOVERY: AUDIT_RUNTIME_ACTION}
FOREIGN = ("connect_blocked:" + OPAQUE.lower(), OPAQUE.lower(), "ghp_" + "b" * 36, FIXED_UUID)


async def _stored(db, ws, resource_type, details):
    record = ComplianceAuditRecord(id=str(uuid.uuid4()), project_id=ws.id, event_type=EVENT[resource_type],
                                   resource_type=resource_type, details=details, contains_sensitive=False)
    db.add(record)
    await db.commit()
    return record


async def _views(client, db, admin, ws) -> tuple[dict, str]:
    response = await client.get(RECORDS, params={"workspace_id": ws.id}, headers=bearer(admin))
    package = await create_evidence_package(db, name="review", project_id=ws.id)
    await seal_evidence_package(db, package.id)
    exported = await export_evidence_package(db, package.id)
    rows = {row["id"]: row for row in response.json()["records"]}
    return {**rows, "export": {r["id"]: r for r in exported["records"]}}, response.text + str(exported)


@pytest.mark.asyncio
@pytest.mark.parametrize("resource_type", [MCP, RECOVERY])
async def test_writer_values_are_shown_and_any_other_value_in_an_approved_key_is_hidden(client, db, resource_type):
    admin = await make_user(db, admin=True)
    ws = await _workspace(db)
    genuine = await _stored(db, ws, resource_type, {**WRITER_VALUES[resource_type], "outbox_entry_id": FIXED_UUID})
    foreign = [await _stored(db, ws, resource_type, {key: value for key in WRITER_VALUES[resource_type]})
               for value in FOREIGN]

    views, text = await _views(client, db, admin, ws)
    for view in (views, views["export"]):
        assert view[genuine.id]["details"] == WRITER_VALUES[resource_type]
        assert view[genuine.id]["hidden_field_count"] == 1, "the free-form id"
        for record in foreign:
            assert view[record.id]["details"] == {}
            assert view[record.id]["hidden_field_count"] == len(WRITER_VALUES[resource_type])
    assert OPAQUE.lower() not in text and "ghp_" not in text and FIXED_UUID not in text


@pytest.mark.asyncio
async def test_a_flagged_record_keeps_vocabulary_values_and_hides_its_numbers(client, db):
    admin = await make_user(db, admin=True)
    ws = await _workspace(db)
    record = await _stored(db, ws, MCP, WRITER_VALUES[MCP])
    record.contains_sensitive = True
    await db.commit()

    views, _text = await _views(client, db, admin, ws)
    for view in (views, views["export"]):
        assert view[record.id]["details"] == {"action": "connection_failed", "owner_scope": "platform"}
        assert view[record.id]["hidden_field_count"] == 2


@pytest.mark.asyncio
async def test_a_bound_api_key_sees_only_its_workspace(client, db):
    admin = await make_user(db, admin=True)
    bound = await _workspace(db)
    other = await _workspace(db)
    mine = await create_audit_record(db, event_type=AUDIT_ADMIN_CHANGE, resource_type="r", project_id=bound.id)
    await create_audit_record(db, event_type=AUDIT_ADMIN_CHANGE, resource_type="r", project_id=other.id)
    await create_audit_record(db, event_type=AUDIT_ADMIN_CHANGE, resource_type="r", project_id=None)
    key = await _key(db, admin, scopes=["admin"], project_id=bound.id)

    rows = (await client.get(RECORDS, headers=key)).json()["records"]
    assert [row["id"] for row in rows] == [mine.id]
    kinds = (await client.get(KINDS, headers=key)).json()
    assert [w["id"] for w in kinds["workspaces"]] == [bound.id]
    foreign = await client.get(RECORDS, params={"workspace_id": other.id}, headers=key)
    unknown = await client.get(RECORDS, params={"workspace_id": str(uuid.uuid4())}, headers=key)
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json().get("detail") == unknown.json().get("detail")


@pytest.mark.asyncio
async def test_a_key_without_the_admin_scope_or_bound_outside_the_users_workspaces_is_refused(client, db):
    admin = await make_user(db, admin=True)
    narrow = await _key(db, admin, scopes=["read"])
    assert (await client.get(RECORDS, headers=narrow)).status_code == 403
    assert (await client.get(KINDS, headers=narrow)).status_code == 403

    user = await make_user(db, admin=False)
    own = await _workspace(db)
    elsewhere = await _workspace(db)
    db.add(UserProject(user_id=user, project_id=own.id, role="admin"))
    await db.flush()
    key = await _key(db, user, scopes=["admin"], project_id=elsewhere.id)
    assert (await client.get(RECORDS, headers=key)).status_code == 403
    assert (await client.get(RECORDS, params={"workspace_id": own.id}, headers=key)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{}, {"limit": "9999"}, {"since": "yesterday"}, {"cursor": "%%%"},
                                 {"event_type": "nope"}])
async def test_a_hidden_private_and_an_unknown_workspace_answer_alike_even_with_a_bad_query(client, db, bad):
    admin = await make_user(db, admin=True)
    stranger = await make_user(db, admin=False)
    private = await _workspace(db, access_mode=PRIVATE_ACCESS_MODE, owner_user_id=stranger)
    await db.commit()

    answers = [await client.get(RECORDS, params={"workspace_id": ws, **bad}, headers=bearer(admin))
               for ws in (private.id, str(uuid.uuid4()))]
    assert [a.status_code for a in answers] == [404, 404]
    assert answers[0].json().get("detail") == answers[1].json().get("detail")


def _cursor(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


FIXED_ID = "0b5b8c1e-6a3f-4f43-9d0e-2f6a7b1c9d21"
VALID = _cursor(f"2026-11-24T10:00:00|{FIXED_ID}")
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _pad_bits_set(cursor: str) -> str:
    last = cursor.rstrip("=")
    padding = cursor[len(last):]
    return last[:-1] + ALPHABET[ALPHABET.index(last[-1]) + 1] + padding


@pytest.mark.parametrize("cursor", [
    pytest.param("", id="empty"),
    pytest.param(_pad_bits_set(VALID), id="pad-bits-set"),
    pytest.param("x" * 300, id="too-long"),
    pytest.param(_cursor("2026-11-24T10:00:00|not-a-uuid"), id="id-not-uuid"),
    pytest.param(_cursor(f"2026-11-24T10:00:00+00:00|{FIXED_ID}"), id="aware-time"),
    pytest.param(_cursor(f"2026-11-24|{FIXED_ID}"), id="date-only"),
    pytest.param(_cursor(f"2026-11-24T10:00:00|{FIXED_ID}|extra"), id="extra-part"),
    pytest.param(_cursor(f"2026-11-24T10:00:00|{FIXED_ID}").rstrip("="), id="padding-missing"),
    pytest.param(_cursor(f"2026-11-24T10:00:00|{FIXED_ID}")[:-4] + "!!!=", id="not-base64"),
])
@pytest.mark.asyncio
async def test_a_malformed_cursor_is_refused_before_the_query(client, db, cursor):
    admin = await make_user(db, admin=True)
    response = await client.get(RECORDS, params={"cursor": cursor}, headers=bearer(admin))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_cursor"


@pytest.mark.asyncio
async def test_an_emitted_cursor_round_trips(client, db):
    admin = await make_user(db, admin=True)
    ws = await _workspace(db)
    for _ in range(3):
        record = await create_audit_record(db, event_type=AUDIT_ADMIN_CHANGE, resource_type="r", project_id=ws.id)
        record.created_at = utc_now()
    await db.commit()
    first = (await client.get(RECORDS, params={"workspace_id": ws.id, "limit": "2"}, headers=bearer(admin))).json()
    second = await client.get(RECORDS, params={"workspace_id": ws.id, "limit": "2", "cursor": first["next_cursor"]},
                              headers=bearer(admin))
    assert second.status_code == 200 and len(second.json()["records"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("query,code", [
    ({"limit": ""}, "invalid_limit"),
    ({"limit": "\u0663"}, "invalid_limit"),
    ({"limit": "9" * 40}, "invalid_limit"),
    ({"limit": "0"}, "invalid_limit"),
    ({"since": ""}, "invalid_since"),
    ({"since": "0001-01-01T00:00:00+14:00"}, "invalid_since"),
    ({"until": "9999-12-31T23:59:59-14:00"}, "invalid_until"),
])
async def test_a_malformed_limit_or_time_is_a_422_never_a_server_error(client, db, query, code):
    admin = await make_user(db, admin=True)
    response = await client.get(RECORDS, params=query, headers=bearer(admin))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
