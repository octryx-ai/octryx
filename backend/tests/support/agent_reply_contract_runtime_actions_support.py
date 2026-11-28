"""Shared helpers for the test_agent_reply_contract_runtime_actions_* modules."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

from app.models import Message, Session, Task, TurnTrace
from app.services.session.turn_execution_snapshot import (
    AGENT_REPLY_CONTRACT_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
    TURN_EXECUTION_SNAPSHOT_VERSION,
)
from app.time_utils import utc_now
from tests.scheduler.test_action_runtime_admission import _admin, _agent, _project

CONTRACT = {
    "kind": "json_object",
    "schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
}


SATISFIED = {"kind": "json_object", "status": "satisfied", "reason": None}


NOT_JSON = {"kind": "json_object", "status": "violated", "reason": "agent_reply_not_json"}


UNCHECKED = "agent_reply_contract_unchecked"


FINISHED_SATISFIED = {"outcome": "finished", "record": SATISFIED}


STOPPED_NOT_JSON = {"outcome": "stopped", "stop_reason": "agent_reply_not_json", "record": NOT_JSON}


INTERMEDIATE: dict = {}


async def _session(db, owner_id):
    session = Session(id=str(uuid.uuid4()), user_id=owner_id, agent_type="diagnosis", status="active", metadata_={})
    db.add(session)
    await db.flush()
    return session


async def _trace(db, session_id, *, at, outcome=None, stop_reason=None, record=None):
    snapshot = {"version": TURN_EXECUTION_SNAPSHOT_VERSION, "execution_profile": {"present": True},
                "gate": {"allowed": True}, "turn": {"user_message_id": None, "sequence": 1}}
    if outcome:
        snapshot["runtime_outcome"] = outcome
    if stop_reason:
        snapshot["runtime_stop_reason"] = stop_reason
    context = {TURN_EXECUTION_SNAPSHOT_KEY: snapshot, **({AGENT_REPLY_CONTRACT_KEY: record} if record else {})}
    trace_id = str(uuid.uuid4())
    db.add(TurnTrace(id=trace_id, session_id=session_id, context_snapshot_json=context,
                     raw_output={"content": "x"}, created_at=at))
    await db.flush()
    return trace_id


async def _write_run(db, session_id, specs):
    start = utc_now()
    return [await _trace(db, session_id, at=start + timedelta(milliseconds=index), **spec)
            for index, spec in enumerate(specs)]


@asynccontextmanager
async def _single_session(db):
    yield db


async def _action(db, *, reply_contract=None, task_type="agent_run", config=None, name="Nightly summary"):
    project = await _project(db, f"reply-contract-{uuid.uuid4().hex[:6]}")
    owner = await _admin(db)
    fields = {"reply_contract_json": json.dumps(reply_contract)} if reply_contract else {}
    agent = await _agent(db, owner.id, project.id, **fields)
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name=name, task_type=task_type,
                agent_type="diagnosis", owner_id=owner.id, is_active=True,
                config={"agent_definition_id": agent.id, **(config or {})})
    db.add(task)
    await db.commit()
    return task, agent


async def _foreign_chat_turn(db, session_id):
    at = utc_now()
    db.add(Message(id=str(uuid.uuid4()), session_id=session_id, role="user", content="Chat in between", created_at=at))
    await db.flush()
    return await _trace(db, session_id, at=at + timedelta(milliseconds=1), **FINISHED_SATISFIED)
