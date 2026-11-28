from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import update

from app.models import Message, User
from app.services.devices.chat_turn import store_prompt
from app.services.session.handovers import _move_session
from app.time_utils import utc_now
from app.web._helpers.workspace import _serialize_chat_message_page_bundle
from app.web._helpers.workspace_message_page import load_workspace_message_page_bundle
from tests.devices.device_support import chat_session
from tests.policy_engine_support import make_user


async def _person(db, name: str) -> User:
    user = await db.get(User, await make_user(db, admin=False))
    user.display_name = name
    return user


async def _authors(db, thread, viewer) -> list[tuple[str, str | None]]:
    bundle = await load_workspace_message_page_bundle(db, session=thread, user=viewer, limit=20)
    rows, _more = _serialize_chat_message_page_bundle(bundle, session=thread, workspace_root=None,
                                                      selected_runtime_label="")
    return [(row["content"], row["authorName"]) for row in rows if row["role"] == "user"]


@pytest.mark.asyncio
async def test_a_hand_over_keeps_the_earlier_prompts_with_the_person_who_wrote_them(db):
    owner, taker = await _person(db, "Previous Owner"), await _person(db, "New Owner")
    thread = await chat_session(db, owner)
    db.add(Message(session_id=thread.id, role="user", content="first", created_at=utc_now() - timedelta(minutes=5)))
    await db.flush()
    await _move_session(db, thread, taker, None)
    db.add(Message(session_id=thread.id, role="user", content="second"))
    await db.flush()
    assert await _authors(db, thread, taker) == [("first", "Previous Owner"), ("second", "New Owner")]


@pytest.mark.asyncio
async def test_a_named_author_is_kept_in_another_persons_chat(db):
    owner, contributor = await _person(db, "Owner"), await _person(db, "Contributor")
    thread = await chat_session(db, owner)
    db.add(Message(session_id=thread.id, role="user", content="from a contributor", author_user_id=contributor.id))
    await db.flush()
    assert await _authors(db, thread, owner) == [("from a contributor", "Contributor")]


@pytest.mark.asyncio
async def test_a_message_older_than_its_recorded_author_shows_under_the_session_owner(db):
    owner = await _person(db, "Owner")
    thread = await chat_session(db, owner)
    db.add(Message(session_id=thread.id, role="user", content="before the author column"))
    db.add(Message(session_id=thread.id, role="assistant", content="an answer"))
    await db.flush()
    await db.execute(update(Message).where(Message.session_id == thread.id).values(author_user_id=None))
    assert await _authors(db, thread, owner) == [("before the author column", "Owner")]
    bundle = await load_workspace_message_page_bundle(db, session=thread, user=owner, limit=20)
    rows, _more = _serialize_chat_message_page_bundle(bundle, session=thread, workspace_root=None,
                                                      selected_runtime_label="")
    assert [row["authorName"] for row in rows if row["role"] == "assistant"] == [None]


@pytest.mark.parametrize(("prompt", "expected"), [("rewritten by the taker", "New Owner"), ("first", "Previous Owner")])
@pytest.mark.asyncio
async def test_a_rerun_with_new_words_is_the_rerunners_and_an_unchanged_one_stays_with_its_writer(db, prompt, expected):
    owner, taker = await _person(db, "Previous Owner"), await _person(db, "New Owner")
    thread = await chat_session(db, owner)
    first = Message(session_id=thread.id, role="user", content="first", created_at=utc_now() - timedelta(minutes=5))
    db.add(first)
    db.add(Message(session_id=thread.id, role="assistant", content="an answer"))
    await db.flush()
    await _move_session(db, thread, taker, None)
    await store_prompt(db, thread, None, prompt, rerun_message=first, message_on_accept=False, idempotency_key=None,
                       author_user_id=taker.id)
    await db.flush()
    assert await _authors(db, thread, taker) == [(prompt, expected)]
