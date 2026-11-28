"""Chat sidebar list hygiene: no empty "New thread" rows, and no duplicate thread for a repeated ``idempotency_key``."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models import Message, Project, Session, User
from app.services.session.session_title import title_from_prompt
from tests.chat_pool_support import chat_pool  # noqa: F401 - fixture
from tests.conftest import ADMIN_PASSWORD


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


@pytest.mark.asyncio
async def test_a_session_without_title_or_message_is_not_a_sidebar_thread(client, auth_headers, db):
    admin = await _admin(db)
    gateway_session = Session(
        id=str(uuid.uuid4()), user_id=admin.id, agent_type="external_agent", status="active",
        metadata_={"external_source": "model_gateway", "summary": "gateway session"},
    )
    db.add(gateway_session)
    await db.commit()

    page = await client.get("/admin/chat/api/thread-groups?project_id=&offset=0&limit=100", headers=auth_headers)
    assert page.status_code == 200
    rows = {row["id"]: row for row in page.json()["sessions"]}
    assert gateway_session.id not in rows


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_repeated_new_thread_send_with_the_same_key_creates_one_thread(client, db, chat_pool):  # noqa: F811
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    prompt = f"duplicate-thread repro {uuid.uuid4()}"
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    body = {"prompt": prompt, "session_id": "", "idempotency_key": "send-once-1", "project_id": project.id}

    first = await client.post("/admin/chat/api/send", json=body)
    second = await client.post("/admin/chat/api/send", json=body)
    assert first.status_code == 200, first.text
    assert second.status_code in (200, 409)

    admin_id = (await _admin(db)).id
    thread_count = (
        await db.execute(
            select(func.count(Session.id)).where(
                Session.user_id == admin_id, Session.metadata_["title"].as_string() == title_from_prompt(prompt)
            )
        )
    ).scalar_one()
    assert thread_count == 1
    assert second.json()["selectedSession"]["id"] == first.json()["selectedSession"]["id"]


@pytest.mark.asyncio
async def test_machine_origin_sessions_are_not_listed_even_with_a_title(client, auth_headers, db):
    admin = await _admin(db)
    chat = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active",
                   metadata_={"title": "A real chat"})
    analysis = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active",
                       origin="work_item_analysis", metadata_={"title": "Analysis of WI-1"})
    db.add_all([chat, analysis])
    await db.commit()

    page = await client.get("/admin/chat/api/thread-groups?project_id=&offset=0&limit=100", headers=auth_headers)
    count = await client.get("/admin/chat/api/thread-groups/count?project_id=", headers=auth_headers)

    ids = {row["id"] for row in page.json()["sessions"]}
    assert chat.id in ids
    assert analysis.id not in ids
    assert count.json()["count"] == len(ids)


def test_an_unknown_origin_is_refused():
    with pytest.raises(ValueError):
        Session(id=str(uuid.uuid4()), user_id="u", origin="guessed")


@pytest.mark.asyncio
async def test_a_key_of_another_user_never_matches(db):
    from app.services.session.send_idempotency import find_idempotent_send_session

    admin = await _admin(db)
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active")
    db.add(session)
    db.add(Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content="hi", idempotency_key="k-1"))
    await db.commit()

    assert (await find_idempotent_send_session(db, user_id=admin.id, idempotency_key="k-1")).id == session.id
    assert await find_idempotent_send_session(db, user_id="someone-else", idempotency_key="k-1") is None
    assert await find_idempotent_send_session(db, user_id=admin.id, idempotency_key="") is None
