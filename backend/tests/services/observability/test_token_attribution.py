"""Token metrics by engine, model, role and Workspace, labelled from memory only; a call without any context
is counted as unattributed."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models import UsageEvent, WorkflowRun, WorkflowRunSession, WorkItem
from app.services.observability import agent_metrics, attribution
from tests.observability_support import admin_user, session_for, workspace


@pytest.fixture(autouse=True)
def _empty():
    agent_metrics.reset()
    yield
    agent_metrics.reset()


def _tokens(text: str, **labels: str) -> float:
    wanted = [f'{key}="{value}"' for key, value in labels.items()]
    found = [line for line in text.splitlines()
             if line.startswith("octryx_llm_tokens_total{") and all(part in line for part in wanted)]
    assert len(found) == 1, (labels, [line for line in text.splitlines() if line.startswith("octryx_llm_tokens")])
    return float(found[0].rsplit(" ", 1)[1])


def _usage(admin, session, provider: str, tokens_in: int, **fields) -> UsageEvent:
    return UsageEvent(id=str(uuid.uuid4()), session_id=session.id, user_id=admin.id, provider=provider,
                      model="m", tokens_in=tokens_in, tokens_out=1, cost=Decimal("0"), **fields)


@pytest.mark.asyncio
async def test_labels_come_from_the_request_the_row_or_the_known_run_session(db):
    admin = await admin_user(db)
    project = await workspace(db, "Coffee Bench")
    item = WorkItem(project_id=project.id, source_key="CAF-30", title="Story", epic_key="CAF-24")
    db.add(item)
    await db.flush()
    run = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="story-delivery", title="t",
                      requested_by=admin.id, ticket_key="CAF-30", work_item_id=item.id)
    linked = await session_for(db, admin, project=project)
    gateway = await session_for(db, admin, project=project)
    chat = await session_for(db, admin, project=project)
    db.add(run)
    await db.flush()
    db.add(WorkflowRunSession(run_id=run.id, session_id=linked.id, role="main"))
    await db.commit()

    # 1. The session this process saw bound to the run: work of a story in an epic.
    db.add(_usage(admin, linked, "openai_codex_seat", 100))
    await db.commit()  # the context is the one at the flush
    # 2. The gateway's run context of the request (a spec run elsewhere).
    with attribution.scope(run="r-spec", workflow="spec-writing", workspace=project.id, epic="CAF-9", role="main"):
        db.add(_usage(admin, gateway, "anthropic_seat", 200))
        await db.commit()
    # 3. The writer attached its run to the row: the review.
    db.add(attribution.attach(_usage(admin, linked, "anthropic_seat", 300, dispatch_owner="workflow_run_review"),
                              run=run.id, role="review"))
    # 4. Nothing known: counted, and as unattributed.
    db.add(_usage(admin, chat, "litellm", 400))
    await db.commit()

    text = "\n".join(agent_metrics.render())
    assert _tokens(text, type="input", engine="codex", role="work", workspace="Coffee Bench") == 100
    assert _tokens(text, type="input", engine="claude_code", role="spec") == 200
    assert _tokens(text, type="input", engine="claude_code", role="review") == 300
    assert _tokens(text, type="input", engine="governed", role="none") == 400
    assert 'octryx_metrics_unattributed_total{source="usage"} 1' in text
    assert 'octryx_llm_usage_events_total{engine="codex",model="m",role="work",workspace="Coffee Bench"}' \
           ' 1' in text
    # No epic label on the counters (it grows with every epic; the run gauges carry it).
    assert not [line for line in text.splitlines() if line.startswith("octryx_llm_") and 'epic="' in line]


def test_the_engine_of_a_provider():
    assert agent_metrics.usage_engine("anthropic_seat") == "claude_code"
    assert agent_metrics.usage_engine("openai_codex_seat") == "codex"
    assert agent_metrics.usage_engine("bedrock") == "governed"
    assert agent_metrics.usage_engine(None) == "governed"
