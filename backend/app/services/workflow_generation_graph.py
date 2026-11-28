"""The phased graph a generated workflow draft starts from (``workflow_generation``)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from ..models import Message, ToolCall, TurnTrace
from ..models import Session as AgentSession
from ..tools.capability_requirements import CAPABILITY_CHANGE, CAPABILITY_READ_ONLY
from .platform_agents.catalog import ASSISTANT, ENGINEER
from .workflow_runs.graph_validation import validate_phased_definition

MAX_SOURCE_TOOL_CALLS = 10
MAX_SOURCE_TRACES = 8
GENERATED_WORKFLOW_CLASS = "generated"
# The results the generated phase's agent ends with; the decision after its gate routes on them.
RESULT_COMPLETE, RESULT_INCOMPLETE = "complete", "incomplete"
# A session without usable tool evidence: the generated phase investigates through the knowledge tools.
PLACEHOLDER_TOOLS = ("knowledge_search", "knowledge_read")


def build_flow_definition(
    *,
    session: AgentSession,
    title: str,
    messages: list[Message],
    tool_calls: list[ToolCall],
    traces: list[TurnTrace],
    allowed_tools: list[str],
) -> dict[str, Any]:
    intent = first_user_message(messages)
    tools = phase_tools(allowed_tools)
    capability = _capability_class(tools)
    if not tools:
        # No usable tool evidence: the phase investigates through the knowledge tools (an explicit placeholder).
        tools = list(PLACEHOLDER_TOOLS)
    checks = [{"type": "tool_called", "params": {"tools": [tool]}, "blocking": True,
               "description": f"{tool} was called"} for tool in tools[:MAX_SOURCE_TOOL_CALLS]]
    phase = _phase_config(
        session=session, title=title, intent=intent, tools=tools, capability=capability, checks=checks, traces=traces
    )
    definition = {"execution_kind": "phased", "nodes": _nodes(title, phase, checks), "edges": _edges()}
    report = validate_phased_definition(definition)
    if not report["valid"]:
        # Never a draft the designer cannot open: the generator's own graph must be a valid phased workflow.
        raise HTTPException(status_code=422, detail=report)
    return definition


def _phase_config(
    *,
    session: AgentSession,
    title: str,
    intent: str,
    tools: list[str],
    capability: str,
    checks: list[dict[str, Any]],
    traces: list[TurnTrace],
) -> dict[str, Any]:
    workflow_id = f"generated_{slug(title).replace('-', '_')}"[:80].strip("_") or "generated_workflow"
    return {
        "agent": ASSISTANT if capability == CAPABILITY_READ_ONLY else ENGINEER,
        "workflow_id": workflow_id,
        "workflow_class": GENERATED_WORKFLOW_CLASS,
        "workflow_contract": {
            "workflow_id": workflow_id,
            "workflow_class": GENERATED_WORKFLOW_CLASS,
            "capability_class": capability,
            "when_to_use": (intent or title)[:500],
            "checks": checks,
            "source_session_id": session.id,
            "trace_ids": [trace.id for trace in traces[:MAX_SOURCE_TRACES]],
        },
        "tool_policy": {"allowlist": tools, "denylist": []},
        "result_values": [RESULT_COMPLETE, RESULT_INCOMPLETE],
    }


def _nodes(title: str, phase: dict[str, Any], checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"id": "start", "type": "start", "label": "Start", "config": {}},
        {"id": "work", "type": "phase", "label": title[:120], "config": phase},
        {"id": "verify", "type": "gate", "label": "Evidence recorded",
         "config": {"phase": "work", "checks": [dict(check) for check in checks]}},
        {"id": "result", "type": "decision", "label": "Work complete?",
         "config": {"check": "result", "source": "work", "options": [RESULT_COMPLETE]}},
        {"id": "review", "type": "approval", "label": "Review the result",
         "config": {"decider": "requester", "title": "Review the result",
                    "summary": "The agent's result and the evidence it recorded."}},
        {"id": "done", "type": "outcome", "label": "Done", "config": {"outcome": "done"}},
        {"id": "blocked", "type": "outcome", "label": "Needs attention", "config": {"outcome": "blocked"}},
        {"id": "stopped", "type": "outcome", "label": "Rejected", "config": {"outcome": "stopped"}},
    ]


def _edges() -> list[dict[str, Any]]:
    return [
        _edge("start", "work"),
        _edge("work", "verify"),
        _edge("verify", "result", when="passed"),
        {**_edge("verify", "work", when="failed"), "kind": "loop", "max_iterations": 2, "label": "One more pass"},
        _edge("result", "review", when=RESULT_COMPLETE),
        _edge("result", "blocked", when="otherwise"),
        _edge("review", "done", when="approved"),
        _edge("review", "stopped", when="rejected"),
    ]


def _edge(source: str, target: str, *, when: str | None = None) -> dict[str, Any]:
    edge_id = f"e-{source}-{target}" + (f"-{when}" if when else "")
    return {"id": edge_id, "source": source, "target": target, "kind": "next", "when": when,
            "max_iterations": None}


def phase_tools(allowed_tools: list[str]) -> list[str]:
    # Never delivery, never an unknown tool.
    from ..tools.capability_requirements import tool_required_capability
    from .run_capability.classes import capability_covers

    return [tool for tool in allowed_tools if capability_covers(CAPABILITY_CHANGE, tool_required_capability(tool))]


def _capability_class(tools: list[str]) -> str:
    from ..tools.capability_requirements import tool_required_capability

    return CAPABILITY_CHANGE if any(tool_required_capability(tool) == CAPABILITY_CHANGE for tool in tools) else (
        CAPABILITY_READ_ONLY)


def first_user_message(messages: list[Message]) -> str:
    for message in messages:
        if message.role == "user":
            return " ".join(str(message.content or "").split())
    return ""


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


__all__ = [
    "MAX_SOURCE_TOOL_CALLS",
    "MAX_SOURCE_TRACES",
    "build_flow_definition",
    "first_user_message",
    "phase_tools",
    "slug",
]
