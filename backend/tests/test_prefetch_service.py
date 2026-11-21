import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.models import Message, PrefetchCacheEntry, Session, SessionToolCacheEntry, User
from app.services.prefetch import (
    PrefetchJob,
    PrefetchRequest,
    PrefetchWorker,
    build_prefetch_params_hash,
    lookup_prefetch_cache,
    select_prefetch_cache_ttl_seconds,
    store_prefetch_cache_result,
)
from app.time_utils import utc_now
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_prefetch_worker_processes_explicit_requests_and_persists_cache(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    db.add(session)
    await db.commit()

    # No prompt-regex planner; a producer hands the worker explicit requests.
    requests = [
        PrefetchRequest(
            rule_id="explicit", tool_name=tool_name, params={"namespace": "payments"}, prefetch_strategy="parallel"
        )
        for tool_name in ("list_failed_pods", "get_k8s_events")
    ]

    executions: list[tuple[str, dict[str, Any]]] = []

    async def fake_execute_tool(tool_name, tool_args, _tool_context):
        executions.append((tool_name, dict(tool_args)))
        return {"tool_name": tool_name, "namespace": tool_args.get("namespace"), "status": "ok"}

    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    worker = PrefetchWorker(session_factory, execute_tool_fn=fake_execute_tool)
    enqueued = await worker.enqueue(
        PrefetchJob(
            session_id=session.id,
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            project_config={"k8s_namespace": "payments"},
            workspace_root=str(Path.cwd()),
            request_id="req-prefetch-test",
            requests=requests,
        )
    )
    assert enqueued == 2

    processed = 0
    while await worker.run_once():
        processed += 1

    assert processed == 2
    assert len(executions) == 2
    assert {name for name, _params in executions} == {"list_failed_pods", "get_k8s_events"}

    cache_rows = (
        (await db.execute(select(PrefetchCacheEntry).where(PrefetchCacheEntry.session_id == session.id)))
        .scalars()
        .all()
    )
    assert len(cache_rows) == 2
    assert all(row.status == "completed" for row in cache_rows)
    assert all(row.params_json.get("namespace") == "payments" for row in cache_rows)


@pytest.mark.asyncio
async def test_execute_tool_call_for_turn_uses_prefetch_cache_before_session_cache(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id=admin.id, metadata_={})
    message = Message(id=str(uuid.uuid4()), session_id=session_id, role="assistant", content="prefetched")
    db.add(session)
    db.add(message)
    await db.commit()

    db.add(
        PrefetchCacheEntry(
            session_id=session_id,
            tool_name="list_failed_pods",
            params_hash=build_prefetch_params_hash("list_failed_pods", {"namespace": "prod"}),
            params_json={"namespace": "prod"},
            result_json={"source": "prefetch", "failed_count": 1},
            status="completed",
        )
    )
    db.add(
        SessionToolCacheEntry(
            session_id=session_id,
            tool_name="list_failed_pods",
            params_hash="session-hash",
            result_json={"source": "session", "failed_count": 2},
            ttl_seconds=60,
        )
    )
    await db.commit()

    execution_count = {"count": 0}

    async def fake_execute_tool(tool_name, tool_args, tool_context):
        execution_count["count"] += 1
        return {"source": "live"}

    result = await execute_tool_call_for_turn(
        db=db,
        assistant_message_id=message.id,
        tool_call={
            "id": "prefetch-hit",
            "function": {"name": "list_failed_pods", "arguments": json.dumps({"namespace": "prod"})},
        },
        tool_context=ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=session_id,
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
        ),
        active_steps=[],
        current_step_index=0,
        current_step_tool_activity=False,
        current_allowed_tool_names=set(),
        latest_repo_state={},
        infer_repo_tool_args=lambda tool_name, tool_args, latest_repo_state: tool_args,
        resolve_allowed_tools_for_step_tool_call=lambda **kwargs: (
            kwargs["current_step_index"],
            kwargs["current_step_tool_activity"],
            kwargs["current_allowed_tool_names"],
        ),
        compact_tool_result_for_model=lambda tool_name, tool_result: tool_result,
        summary_domains_satisfied_by_result=lambda tool_name, tool_result: set(),
        execute_tool=fake_execute_tool,
        turn_diff_tracker=TurnDiffTracker(),
        context_snapshot={},
    )

    assert result.tool_result["result"]["source"] == "prefetch"
    assert result.tool_result["cache"]["status"] == "prefetch_hit"
    assert execution_count["count"] == 0


@pytest.mark.asyncio
async def test_lookup_prefetch_cache_ignores_stale_entries(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session_id = str(uuid.uuid4())
    session = Session(id=session_id, user_id=admin.id, metadata_={})
    db.add(session)
    await db.commit()

    db.add(
        PrefetchCacheEntry(
            session_id=session_id,
            tool_name="list_failed_pods",
            params_hash=build_prefetch_params_hash("list_failed_pods", {"namespace": "prod"}),
            params_json={"namespace": "prod"},
            result_json={"source": "prefetch", "failed_count": 1},
            status="completed",
            completed_at=utc_now() - timedelta(minutes=10),
        )
    )
    await db.commit()

    cached = await lookup_prefetch_cache(
        db,
        session_id=session_id,
        tool_name="list_failed_pods",
        params={"namespace": "prod"},
    )

    assert cached is None


def test_select_prefetch_cache_ttl_seconds_uses_stricter_prefetch_freshness():
    assert select_prefetch_cache_ttl_seconds("list_failed_pods", {"namespace": "prod"}) == 30
    assert select_prefetch_cache_ttl_seconds("get_k8s_events", {"namespace": "prod"}) == 30
    assert select_prefetch_cache_ttl_seconds("search_jira_tickets", {"query": "OPS-123"}) == 120
    assert select_prefetch_cache_ttl_seconds("search_jira_tickets", {"jql": 'project = "OPS"'}) == 300
    assert select_prefetch_cache_ttl_seconds("list_jira_transitions", {"issue_key": "OPS-1"}) == 0


@pytest.mark.asyncio
async def test_store_prefetch_cache_result_skips_unsupported_tools(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    db.add(session)
    await db.commit()

    stored = await store_prefetch_cache_result(
        db,
        session_id=session.id,
        tool_name="list_jira_transitions",
        params={"issue_key": "OPS-1"},
        result={"status": "ok"},
    )

    assert stored is None
    cache_rows = (await db.execute(select(PrefetchCacheEntry))).scalars().all()
    assert cache_rows == []


@pytest.mark.asyncio
async def test_store_prefetch_cache_result_logs_governance_suppression(db, caplog):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    db.add(session)
    await db.commit()

    caplog.set_level("INFO", logger="app.services.prefetch.cache")

    stored = await store_prefetch_cache_result(
        db,
        session_id=session.id,
        tool_name="list_failed_pods",
        params={"namespace": "payments"},
        result={"approval_required": True},
    )

    assert stored is None
    assert "Prefetch cache write suppressed by governance" in caplog.text
