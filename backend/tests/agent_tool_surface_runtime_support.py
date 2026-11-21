"""Shared helpers for the test_agent_tool_surface_runtime_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select

import app.agent.engine as engine_module
import app.tools.registry as registry_module
from app.agent.engine import run_agent
from app.models import Session, User
from app.services.run_capability.declared import (
    DECLARED_RUN_CAPABILITY_METADATA_KEY,
    SOURCE_FLOW_DEFINITION,
    declared_run_capability,
)

_ANSWER = "SUM=43"


_TASK = "Workflow step input (JSON):\n{\"context\": \"Synthetic validation numbers: 31, 8 and 4.\"}"


def _agent(surface: str | None) -> dict:
    payload = {
        "id": str(uuid.uuid4()),
        "name": "Synthetic sum",
        "description": "",
        "goal": "Sum the supplied numbers and return exactly SUM=<number>.",
        "agentType": "chat",
        "thinkingLevel": "light",
        "branchPrefix": "octryx",
        "requireSelfReview": False,
        "systemPrompt": "",
        "outputPrompt": "",
        "projectId": "",
        "groupId": "",
        "groupName": "",
        "runtimeTargetId": "",
        "skillPreferences": {},
        "isActive": True,
        "steps": [],
    }
    if surface is not None:
        payload["toolSurface"] = surface
    return payload


class _Script:
    """A scripted provider: records each request's tool names and system texts, replays responses."""

    def __init__(self, monkeypatch, responses: list[dict]):
        self.calls: list[dict] = []
        self._responses = list(responses)

        async def fake_runtimes(_db, runtime_target_id=None):
            return [{"provider_name": "bedrock", "model": "anthropic.claude-sonnet-4-5"}]

        async def fake_chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None, **_kwargs):
            self.calls.append(
                {
                    "tools": sorted(str(tool["function"]["name"]) for tool in tools or []),
                    "system": [str(m.get("content") or "") for m in messages if m.get("role") == "system"],
                }
            )
            response = self._responses.pop(0) if self._responses else {"content": _ANSWER, "tool_calls": None}
            usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            return {"model": "anthropic.claude-sonnet-4-5", **response, "usage": usage}, runtimes[0]

        monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_runtimes)
        monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat)


async def _session(db, project_id: str | None = None) -> tuple[User, Session]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    # Like a workflow agent step's child session: a flow that declares no class.
    declared = declared_run_capability(None, source=SOURCE_FLOW_DEFINITION).to_metadata()
    session = Session(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project_id, agent_type="chat", status="running",
        metadata_={DECLARED_RUN_CAPABILITY_METADATA_KEY: declared},
    )
    db.add(session)
    await db.commit()
    return admin, session


async def _run(db, admin, session, *, agent_definition, message=_TASK) -> list[str]:
    contents: list[str] = []
    async for event in run_agent(
        session_id=session.id, user_message=message, user_id=admin.id, project_id=session.project_id,
        agent_type="chat", db=db, agent_definition=agent_definition,
    ):
        if getattr(event, "role", "") == "assistant" and getattr(event, "content", ""):
            contents.append(str(event.content))
    return contents


def _record_tool_executions(monkeypatch) -> list[str]:
    executed: list[str] = []

    async def recording_dispatch(tool_name, params, context):
        executed.append(tool_name)
        return {"status": "ok", "results": []}

    monkeypatch.setattr(registry_module, "_dispatch_registered_tool", recording_dispatch)
    return executed
