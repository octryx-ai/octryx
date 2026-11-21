"""Test fixture: the additive spec-from-idea producer graph (not shipped as a workflow); publishing requires
central integration and spec review."""
from __future__ import annotations

BUDGET = {"tokens": 100000, "cost_usd": 1, "active_seconds": 1200, "tool_calls": 40}
BUDGET_NOTICE = (
    "These are whole-run thresholds checked after each completed phase turn. A turn can overshoot; "
    "they are not hard per-read caps or a guaranteed wall-clock timeout."
)


def _phase(kind: str, instructions: str, *, inputs=(), research=False) -> dict:
    tools = [f"submit_{kind}"] + (["knowledge_search", "knowledge_read"] if research else [])
    return {"agent": "assistant", "output": kind, "inputs": list(inputs),
        "workflow_id": "knowledge_request", "workflow_class": "knowledge_request",
        "instructions": instructions,
        "tool_policy": {"allowlist": tools, "denylist": []},
        "workflow_contract": {"workflow_id": "knowledge_request", "workflow_class": "knowledge_request",
            "capability_class": "read_only", "when_to_use": instructions,
            "checks": [{"type": "tool_called", "blocking": True, "description": f"Record {kind}",
                "params": {"tools": [f"submit_{kind}"]}}]}}


def specification_definition() -> dict:
    """Return a fresh, non-published definition. No engineering/external-action/handoff nodes."""
    phase_specs = [
        ("idea", "idea_frame", "Clarify the idea, scope and explicit uncertainty. Retain stable IDs. "
         "Do not invent source facts. Open questions prevent readiness.", (), False),
        ("plan", "research_plan", "Propose Knowledge-only research questions. No web egress. "
         "The server binds the confirmed idea and actual effective run budget. " + BUDGET_NOTICE,
         ("idea_frame",), False),
        ("research", "research_brief", "Research only the confirmed plan using Knowledge. Read actual passages "
         "with knowledge_read before submitting claims. Cite exact evidence_keys, disclose contradictions and "
         "uncertainty. Search snippets/URLs are not proof. No source means needs_configuration.",
         ("research_plan",), True),
        ("draft", "spec", "Draft user stories and Given/When/Then criteria with stable IDs; include NFRs, risks, "
         "documentation audience and explicit uncertainty. Factual claims use only the brief's admitted exact "
         "Knowledge evidence keys. Do not treat proposed requirements as observed evidence.",
         ("idea_frame", "research_brief"), False),
    ]
    nodes = [{"id": "start", "type": "start"}]
    edges = []
    previous = "start"
    for name, kind, instructions, inputs, research in phase_specs:
        nodes.append({"id": name, "type": "phase", "config": _phase(kind, instructions,
                      inputs=inputs, research=research)})
        edges.append({"id": f"to-{name}", "source": previous, "target": name})
        previous = name
        if kind in {"idea_frame", "research_plan"}:
            gate = f"{name}-ready"
            nodes.append({"id": gate, "type": "gate", "config": {"phase": name, "checks": [
                {"type": "specification_ready", "blocking": True, "description": f"Current {kind} ready",
                 "params": {"kind": kind}}]}})
            edges.extend([{"id": f"to-{gate}", "source": name, "target": gate},
                {"id": f"revise-{name}", "source": gate, "target": name, "when": "failed", "kind": "loop",
                 "max_iterations": 2}])
            card = f"confirm-{name}"
            nodes.append({"id": card, "type": "user_confirmation", "config": {"subject": "advance", "shows": kind}})
            edges.extend([{"id": f"to-{card}", "source": gate, "target": card, "when": "passed"},
                {"id": f"change-{name}", "source": card, "target": name, "when": "changed", "kind": "loop",
                 "max_iterations": 2}])
            previous = card
    nodes.extend([
        {"id": "review", "type": "review", "config": {"mode": "artefact", "kind": "spec",
            "source": "local_output", "producer": "draft", "rubric_version": 1}},
        {"id": "spec-ready", "type": "gate", "config": {"checks": [
            {"type": "artefact_review_passed", "description": "Exact spec independently reviewed", "blocking": True,
             "params": {}}, {"type": "specification_ready", "description": "Current spec has no open questions",
                             "blocking": True, "params": {"kind": "spec"}}]}},
        {"id": "confirm-spec", "type": "user_confirmation", "config": {"subject": "advance", "shows": "spec"}},
        {"id": "done", "type": "outcome", "label": "Specification accepted; engineering not started",
         "config": {"outcome": "done"}},
    ])
    edges.extend([
        {"id": "to-review", "source": "draft", "target": "review"},
        {"id": "to-spec-ready", "source": "review", "target": "spec-ready"},
        {"id": "revise-spec", "source": "spec-ready", "target": "draft", "when": "failed", "kind": "loop",
         "max_iterations": 2},
        {"id": "to-confirm-spec", "source": "spec-ready", "target": "confirm-spec", "when": "passed"},
        {"id": "change-spec", "source": "confirm-spec", "target": "draft", "when": "changed", "kind": "loop",
         "max_iterations": 2},
        {"id": "accepted", "source": "confirm-spec", "target": "done", "when": "confirmed"},
    ])
    # Every human card advances only on an explicit confirmation.
    for edge in edges:
        if edge["source"] in {"confirm-idea", "confirm-plan"} and "when" not in edge:
            edge["when"] = "confirmed"
    return {"execution_kind": "phased", "budget": dict(BUDGET), "nodes": nodes, "edges": edges}
