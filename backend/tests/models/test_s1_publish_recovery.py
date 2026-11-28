"""S1 publication through Confluence Cloud v2: one claimed send, crash recovery, exact reconciliation,
with the v2 adapter on an injected ``httpx.MockTransport`` Cloud fake."""

from __future__ import annotations

import pytest

from app.models import DocumentationWriteIntent, WorkItemDocument
from tests.phased_workflow_fixtures import admin_user
from tests.s1_publish_cloud_support import PARENT, FakeCloudV2
from tests.s1_publish_run_support import publish, published_ready

pytestmark = pytest.mark.asyncio


async def _intent(db, intent_id: str) -> DocumentationWriteIntent:
    row = await db.get(DocumentationWriteIntent, intent_id)
    await db.refresh(row)
    return row


async def test_a_create_is_sent_once_read_back_and_recorded(db):
    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    outcome = await publish(db, run, fake)
    assert outcome.ok, outcome.reason
    page_id = outcome.result["page_id"]
    assert (outcome.result["version"], outcome.result["status"]) == (1, "created")
    # Every run publication is agent output: one page write plus its best-effort label.
    assert fake.children(PARENT) == [page_id]
    assert [method for method, url in fake.writes if "/api/v2/" in url] == ["POST"]
    row = await _intent(db, intent.id)
    assert (row.state, row.result_kind, row.result_page_id, row.result_version) == (
        "sent_confirmed", "provider_reply", page_id, 1)
    assert outcome.result["storage_digest"] == row.result_storage_digest
    assert outcome.result["location"]["parent_id"] == PARENT
    assert run.context["documentation"]["page_id"] == page_id
    assert (await db.get(WorkItemDocument, (await db.execute(
        WorkItemDocument.__table__.select().where(WorkItemDocument.page_id == page_id))).first().id)).version == 1


async def test_an_ai_written_page_is_marked_labelled_and_verifies_again_without_a_false_change(db):
    from sqlalchemy import select

    from app.models import Message, WorkflowRunSession

    fake = FakeCloudV2()
    run, intent = await published_ready(db, fake)
    session_id = (await db.execute(select(WorkflowRunSession.session_id).where(
        WorkflowRunSession.run_id == run.id))).scalar_one()
    db.add(Message(session_id=session_id, role="assistant", content="docs", model="claude-haiku-5-5"))
    await db.commit()

    outcome = await publish(db, run, fake)
    assert outcome.ok, outcome.reason
    page_id = outcome.result["page_id"]
    admin = await admin_user(db)
    marker = (f"<p><em>— Written by an agent (octryx · claude-haiku-5-5, run {run.ticket_key}) — responsible: "
              f"{admin.display_name}.</em></p>")
    assert fake.pages[page_id]["versions"][-1]["storage"].endswith(marker)
    # The label is best effort: the fake answers 404 to the v1 label call and the publication still succeeds.
    assert ("POST", f"https://your-site.atlassian.net/wiki/rest/api/content/{page_id}/label") in fake.requests
    row = await _intent(db, intent.id)
    assert row.dispatch_check["ai_marking"] == {"responsible": admin.display_name, "model": "claude-haiku-5-5",
                                                "run_key": run.ticket_key}

    db.add(Message(session_id=session_id, role="assistant", content="later", model="another-model"))
    await db.commit()
    again = await publish(db, run, fake)
    assert again.ok, again.reason
    assert again.result["status"] == "reconciled" and again.result["storage_digest"] == row.result_storage_digest
    assert [method for method, url in fake.writes if "/api/v2/" in url] == ["POST"]  # never written again
