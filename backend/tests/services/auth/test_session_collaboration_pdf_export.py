"""The session PDF export requires read access."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Message, Role, Session, SessionCollaborator, ToolCall, TurnTrace, User, UserRole
from app.services.auth import hash_password


def _viewer_user(username, display_name):
    return User(
        id=str(uuid.uuid4()),
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
        display_name=display_name,
        is_active=True,
    )


async def _seed_viewers(db):
    viewer_role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    observer = _viewer_user("pdf-observer", "PDF Observer")
    outsider = _viewer_user("pdf-outsider", "PDF Outsider")
    db.add_all([observer, outsider])
    await db.flush()
    db.add_all(
        [
            UserRole(user_id=observer.id, role_id=viewer_role.id),
            UserRole(user_id=outsider.id, role_id=viewer_role.id),
        ]
    )
    return observer, outsider


async def _seed_exported_session(db, owner, observer):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        agent_type="diagnosis",
        status="completed",
        metadata_={"title": "Report Builder Investigation"},
    )
    user_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="user",
        content="what can you tell me about Report Builder?",
    )
    assistant_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Report Builder builds weekly order reports from the shop's exports.",
        model="test-model",
        tokens_in=12,
        tokens_out=18,
    )
    db.add_all([session, user_message, assistant_message])
    await db.flush()
    db.add_all(
        [
            SessionCollaborator(
                session_id=session.id,
                user_id=observer.id,
                role="observer",
                invited_by=owner.id,
            ),
            ToolCall(
                id=str(uuid.uuid4()),
                session_id=session.id,
                message_id=assistant_message.id,
                tool_name="knowledge_get",
                parameters={"key": "report-builder"},
                result={"evidence": "weekly_report_2026_w46"},
                status="success",
            ),
            TurnTrace(
                id=str(uuid.uuid4()),
                session_id=session.id,
                message_id=assistant_message.id,
                provider="test-provider",
                model="test-model",
                context_snapshot_json={"decision_timeline": [{"summary": "loaded knowledge evidence"}]},
                tool_trace_json=[{"tool": "knowledge_get", "status": "success"}],
                raw_output={"content": "Report Builder builds weekly order reports."},
                usage_json={"input_tokens": 12, "output_tokens": 18},
            ),
        ]
    )
    await db.commit()
    return session


async def _assert_pdf_exports(client, session_id, observer_headers):
    export_resp = await client.get(f"/api/v1/sessions/{session_id}/export.pdf", headers=observer_headers)
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.headers["content-type"] == "application/pdf"
    assert "attachment;" in export_resp.headers["content-disposition"]
    assert "Report-Builder-Investigation" in export_resp.headers["content-disposition"]
    assert export_resp.content.startswith(b"%PDF-1.4")
    assert b"/Pages" in export_resp.content
    assert b"Octryx" in export_resp.content

    chat_export_resp = await client.get(f"/chat/api/sessions/{session_id}/export.pdf", headers=observer_headers)
    assert chat_export_resp.status_code == 200, chat_export_resp.text
    assert chat_export_resp.headers["content-type"] == "application/pdf"
    assert chat_export_resp.content.startswith(b"%PDF-1.4")


async def _assert_analysis_exports(client, session_id, observer_headers):
    analysis_resp = await client.get(f"/api/v1/sessions/{session_id}/export.analysis.json", headers=observer_headers)
    assert analysis_resp.status_code == 200, analysis_resp.text
    assert analysis_resp.headers["content-type"] == "application/json; charset=utf-8"
    assert "Report-Builder-Investigation" in analysis_resp.headers["content-disposition"]
    analysis_payload = analysis_resp.json()
    assert analysis_payload["schema"] == "octryx.chat.analysis.v1"
    assert analysis_payload["counts"] == {"messages": 2, "tool_calls": 1, "turn_traces": 1}
    assert analysis_payload["session"]["id"] == session_id
    assert analysis_payload["messages"][0]["content"] == "what can you tell me about Report Builder?"
    assert analysis_payload["messages"][1]["tool_call_ids"]
    assert analysis_payload["tool_calls"][0]["tool_name"] == "knowledge_get"
    assert analysis_payload["tool_calls"][0]["result"]["evidence"] == "weekly_report_2026_w46"
    assert analysis_payload["turn_traces"][0]["context_snapshot"]["decision_timeline"][0]["summary"]
    assert any(item["kind"] == "tool_call" for item in analysis_payload["timeline"])

    chat_analysis_resp = await client.get(
        f"/chat/api/sessions/{session_id}/export.analysis.json",
        headers=observer_headers,
    )
    assert chat_analysis_resp.status_code == 200, chat_analysis_resp.text
    assert chat_analysis_resp.json()["schema"] == "octryx.chat.analysis.v1"


@pytest.mark.asyncio
async def test_session_pdf_export_requires_read_access(client, db, auth_user):
    observer, outsider = await _seed_viewers(db)
    session = await _seed_exported_session(db, auth_user, observer)

    observer_auth = await client.post("/api/v1/auth/login", data={"username": observer.username, "password": "secret123"})
    assert observer_auth.status_code == 200
    observer_headers = {"Authorization": f"Bearer {observer_auth.json()['access_token']}"}
    outsider_auth = await client.post("/api/v1/auth/login", data={"username": outsider.username, "password": "secret123"})
    assert outsider_auth.status_code == 200
    outsider_headers = {"Authorization": f"Bearer {outsider_auth.json()['access_token']}"}

    await _assert_pdf_exports(client, session.id, observer_headers)

    await _assert_analysis_exports(client, session.id, observer_headers)

    markdown_resp = await client.get(f"/chat/api/sessions/{session.id}/export", headers=observer_headers)
    assert markdown_resp.status_code == 200, markdown_resp.text
    assert markdown_resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "Report-Builder-Investigation.md" in markdown_resp.headers["content-disposition"]
    assert "# Report Builder Investigation" in markdown_resp.text
    assert "Report Builder builds weekly order reports" in markdown_resp.text
    assert "`knowledge_get`" in markdown_resp.text

    blocked_resp = await client.get(f"/api/v1/sessions/{session.id}/export.pdf", headers=outsider_headers)
    assert blocked_resp.status_code == 404
    blocked_analysis_resp = await client.get(
        f"/api/v1/sessions/{session.id}/export.analysis.json",
        headers=outsider_headers,
    )
    assert blocked_analysis_resp.status_code == 404
    blocked_markdown_resp = await client.get(f"/chat/api/sessions/{session.id}/export", headers=outsider_headers)
    assert blocked_markdown_resp.status_code == 404
