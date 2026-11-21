"""Shared seeds for the work item analysis tests: a Workspace with a published Model Policy,
a Jira work item, scripted model answers and stubbed knowledge tools. No live model or connector call."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.models import Project, User, WorkItem
from app.tools.registry import TOOL_REGISTRY
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.model_policy_support import publish_model_policy

ALIAS = "analysis-alias"
POLICY = "analysis-policy"
GATEWAY_RUNTIME = {"provider_name": "analysis-gateway", "driver": "litellm_gateway", "model": ALIAS,
                   "target_id": "target-a", "priority": 1, "config_json": {}}
MANUAL_PAGE = "Vendor manual, page 42"
MANUAL_HIT = f"Certificate rotation fails when the truststore is stale ({MANUAL_PAGE})"


def tool_call(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> dict[str, Any]:
    return {"content": "", "tool_calls": [{"id": call_id, "type": "function",
                                            "function": {"name": name, "arguments": json.dumps(arguments)}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5}}


def final(answer: dict[str, Any] | str) -> dict[str, Any]:
    content = answer if isinstance(answer, str) else json.dumps(answer)
    return {"content": content, "tool_calls": None, "usage": {"prompt_tokens": 80, "completion_tokens": 40}}


def analysis(**overrides: Any) -> dict[str, Any]:
    value = {
        "summary": "The nightly import fails since the certificate rotation.",
        "impact": "No orders are imported for all customers.",
        "likely_cause": {"text": "A stale truststore after the rotation.", "confidence": "medium"},
        "affected_components": ["importer"],
        "evidence": [{"claim": "The manual names a stale truststore as the cause.",
                      "source": {"kind": "manual", "title": "Vendor manual", "locator": MANUAL_PAGE, "url": None}}],
        "similar_tickets": [],
        "next_steps": ["Refresh the truststore."],
        "open_questions": ["When did the last successful import run?"],
    }
    value.update(overrides)
    return value


@dataclass
class Scripted:
    """A provider factory answering from ``script``; every request is kept in ``seen``."""

    script: list[dict[str, Any]]
    seen: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, **_kwargs: Any) -> Any:
        scripted = self

        class _Provider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                scripted.seen.append({"messages": messages, "tools": tools, "model": model})
                return {**scripted.script.pop(0), "model": model or ""}

            async def close(self):
                return None

        return _Provider()


async def gateway_runtimes(_db, *, requires_tools: bool) -> list[dict[str, Any]]:
    return [dict(GATEWAY_RUNTIME)]


@dataclass
class Env:
    workspace_id: str
    user: User
    item: WorkItem
    knowledge_calls: list[dict[str, Any]]
    context_calls: list[dict[str, Any]]


async def seed_env(db, monkeypatch, *, settings: dict[str, Any] | None = None, source_type: str = "jira",
                   work_state: str = "intake", project_config: dict[str, Any] | None = None) -> Env:
    workspace_id = await seed_workspace(db)
    project = await db.get(Project, workspace_id)
    user = await db.get(User, await seed_member(db, workspace_id=workspace_id, role="owner"))
    analysis_settings = {"model_policy": f"{POLICY}@1"} if settings is None else settings
    project.config = {"model_policy": {"allowed_aliases": [ALIAS]}, "work_item_analysis": analysis_settings,
                      **(project_config or {})}
    await publish_model_policy(db, project, user, POLICY, aliases=(ALIAS,))
    item = WorkItem(id=str(uuid.uuid4()), project_id=workspace_id, source_type=source_type, source_instance="test",
                    source_key=f"BRD-{uuid.uuid4().hex[:4]}", title="Nightly import fails",
                    description="Since Monday the import stops with a TLS error.", work_state=work_state,
                    labels_json=["octryx"], issue_type="incident" if source_type == "servicenow" else "Bug",
                    reporter="acc-reporter-1",
                    source_fields_json={"people": {"reporter": {"id": "acc-reporter-1", "display": "Rita Reporter"}}})
    db.add(item)
    await db.commit()
    knowledge_calls: list[dict[str, Any]] = []
    context_calls: list[dict[str, Any]] = []

    async def knowledge(params, context):
        knowledge_calls.append(dict(params))
        return {"results": [{"title": "Vendor manual", "text": MANUAL_HIT, "locator": MANUAL_PAGE}]}

    async def work_context(params, context):
        context_calls.append(dict(params))
        return {"work_item": params.get("work_item"), "notes": []}

    monkeypatch.setattr(TOOL_REGISTRY["knowledge_search"], "execute", knowledge)
    monkeypatch.setattr(TOOL_REGISTRY["knowledge_read"], "execute", knowledge)
    monkeypatch.setattr(TOOL_REGISTRY["work_item_context"], "execute", work_context)
    return Env(workspace_id, user, item, knowledge_calls, context_calls)


def run_options(scripted: Scripted) -> dict[str, Any]:
    return {"get_provider": scripted, "resolve_runtimes": gateway_runtimes}


__all__ = ["ALIAS", "MANUAL_PAGE", "POLICY", "Env", "Scripted", "analysis", "final", "run_options", "seed_env",
           "tool_call"]
