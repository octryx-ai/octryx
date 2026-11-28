"""The Memory lobe: experience from sessions, kept apart from source evidence."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.project.knowledge_memory import KnowledgeMemoryItem
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.memory.control import correct_memory, forget_memory, list_memory
from app.services.knowledge.memory.errors import MemoryRefusedError
from app.tools.knowledge_memory.recall import MemoryRecallTool
from app.tools.knowledge_memory.remember import MemoryRememberTool
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context

REMEMBER = MemoryRememberTool()
RECALL = MemoryRecallTool()


def _ctx(db, user_id: str, workspace_id: str):
    return tool_context(user_id=user_id, project_id=workspace_id, project_ids=[workspace_id], db=db)


async def _authorized(db, user_id: str, workspace_id: str):
    return await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)


async def test_remember_then_recall_marks_memory_as_not_source_evidence(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    context = _ctx(db, user_id, workspace_id)

    recorded = await REMEMBER.execute({"text": "I prefer answers in German with English code."}, context)
    assert recorded["state"] == "recorded"
    assert (recorded["scope"], recorded["class"], recorded["author_class"]) == ("personal", "personal", "human_stated")
    again = await REMEMBER.execute({"text": "I prefer answers in  german with English code."}, context)
    assert (again["state"], again["memory_id"]) == ("confirmed", recorded["memory_id"])

    result = await RECALL.execute({"query": "German answers"}, context)
    assert (result["state"], result["kind"], result["not_source_evidence"]) == ("ok", "memory", True)
    [item] = result["items"]
    assert item["kind"] == "memory" and item["not_source_evidence"] is True
    assert item["state"] == "confirmed" and item["author_class"] == "human_stated"
    assert item["provenance"]["session_id"] == context.session_id
    assert item["provenance"]["session_link"] == f"/chat?session_id={context.session_id}"
    assert item["present_as"].startswith("from session of ") and item["present_as"].endswith("(confirmed)")
    flat = repr(result)
    assert "source_url" not in flat and "cite_as" not in flat
    assert (await RECALL.execute({"query": "kubernetes"}, context))["state"] == "no_match"


async def test_personal_memory_is_its_owners_and_workspace_memory_needs_the_author_role(db):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    admin_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    member, admin = _ctx(db, member_id, workspace_id), _ctx(db, admin_id, workspace_id)

    await REMEMBER.execute({"text": "My deploy window is Friday afternoon."}, member)
    denied = await REMEMBER.execute(
        {"text": "We deploy on Fridays.", "scope": "workspace", "class": "convention"}, member
    )
    assert (denied["state"], denied["reason"]) == ("denied", "author_required")
    team = await REMEMBER.execute({"text": "We deploy on Fridays.", "scope": "workspace", "class": "convention"}, admin)
    assert team["state"] == "recorded" and team["scope"] == "workspace"

    admin_view = await RECALL.execute({"query": "Friday deploy"}, admin)
    assert [item["scope"] for item in admin_view["items"]] == ["workspace"]
    member_view = await RECALL.execute({"query": "Friday deploy"}, member)
    assert sorted(item["scope"] for item in member_view["items"]) == ["personal", "workspace"]

    listed = await list_memory(db, authorized=await _authorized(db, member_id, workspace_id), user_id=member_id)
    assert {item["scope"]: item["may_change"] for item in listed} == {"personal": True, "workspace": False}
    admin_authorized = await _authorized(db, admin_id, workspace_id)
    personal_id = next(item["id"] for item in listed if item["scope"] == "personal")
    with pytest.raises(MemoryRefusedError) as refused:
        await forget_memory(db, authorized=admin_authorized, user_id=admin_id, memory_id=personal_id)
    assert refused.value.reason == "not_found"


async def test_memory_stays_in_its_workspace_and_secrets_are_refused(db):
    workspace_id = await seed_workspace(db)
    other_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    from app.models.security.user import UserProject

    db.add(UserProject(user_id=user_id, project_id=other_id, role="admin"))
    await db.flush()
    await REMEMBER.execute(
        {"text": "The Acme Orders team reviews on Tuesdays.", "scope": "workspace", "class": "convention"},
        _ctx(db, user_id, workspace_id),
    )
    assert (await RECALL.execute({"query": "Tuesdays"}, _ctx(db, user_id, other_id)))["state"] == "no_match"

    refused = await REMEMBER.execute(
        {"text": "Remember the staging password=Hunter2Hunter2 for later."}, _ctx(db, user_id, workspace_id)
    )
    assert (refused["state"], refused["reason"]) == ("denied", "secret_detected")
    fine = await REMEMBER.execute({"text": "We follow a risk-based task-list review."}, _ctx(db, user_id, workspace_id))
    assert fine["state"] == "recorded"


async def test_correct_supersedes_and_forget_erases_every_version_for_good(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    context = _ctx(db, user_id, workspace_id)
    authorized = await _authorized(db, user_id, workspace_id)

    original = await REMEMBER.execute({"text": "We are on Spring Boot 3.4."}, context)
    corrected = await correct_memory(
        db, authorized=authorized, user_id=user_id, memory_id=original["memory_id"], text="We are on Spring Boot 4.0."
    )
    assert corrected.supersedes_id == original["memory_id"] and corrected.state == "confirmed"
    [item] = (await RECALL.execute({"query": "Spring Boot"}, context))["items"]
    assert (item["memory_id"], item["text"]) == (corrected.id, "We are on Spring Boot 4.0.")
    with pytest.raises(MemoryRefusedError) as refused:
        await correct_memory(db, authorized=authorized, user_id=user_id, memory_id=original["memory_id"], text="x")
    assert refused.value.reason == "not_active"

    assert await forget_memory(db, authorized=authorized, user_id=user_id, memory_id=corrected.id) == 2
    rows = (
        await db.execute(select(KnowledgeMemoryItem).where(KnowledgeMemoryItem.project_id == workspace_id))
    ).scalars()
    for row in rows:
        assert (row.state, row.text, row.content_hash, row.state_changed_by) == ("forgotten", None, None, user_id)
    assert (await RECALL.execute({"query": "Spring Boot"}, context))["state"] == "no_match"
    assert (await RECALL.execute({}, context))["state"] == "no_match"
    assert await list_memory(db, authorized=authorized, user_id=user_id) == []
    history = await list_memory(db, authorized=authorized, user_id=user_id, include_history=True)
    assert {entry["state"] for entry in history} == {"forgotten"} and all(entry["text"] is None for entry in history)
