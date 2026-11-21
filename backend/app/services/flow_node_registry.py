from __future__ import annotations

from typing import Any

from .flow_node_contract import FlowNodeContract, _object_schema

FLOW_NODE_CONTRACTS: tuple[FlowNodeContract, ...] = (
    FlowNodeContract(
        type="trigger",
        display_name="Input",
        category="Input / Output",
        description="Starts a flow from a manual, scheduled, webhook, or chat request.",
        config_schema=_object_schema({"trigger_type": {"type": "string"}}),
        output_schema={"request": "string"},
        can_start=True,
        project_visibility_implications=("May expose project-scoped runtime entry points.",),
    ),
    FlowNodeContract(
        type="input_schema",
        display_name="Input Schema",
        category="Input / Output",
        description="Normalizes inbound fields into a typed flow input contract.",
        input_schema={"request": "string"},
        output_schema={"request": "string"},
        can_start=True,
    ),
    FlowNodeContract(
        type="output",
        display_name="Output",
        category="Input / Output",
        description="Marks the final structured result returned by a flow.",
        input_schema={"result": "object"},
        can_end=True,
    ),
    FlowNodeContract(
        type="agent_step",
        display_name="Agent Step",
        category="AI",
        description=(
            "Runs an Octryx agent or a prompt on the workflow's default agent. Its result is the agent's final "
            "text; data (optional) is the parsed reply object, present only when the agent declares a checked "
            "JSON reply format and the reply satisfied it."
        ),
        config_schema=_object_schema(
            {
                "agent_definition_id": {"type": "string"},
                "prompt": {"type": "string"},
                "thinking_level": {"type": "string"},
            }
        ),
        input_schema={"context": "object"},
        # The final text, as returned; ``data`` only for a satisfied checked JSON reply.
        output_schema={"result": "string", "data": "object"},
        calls_llm=True,
        required_config_any=("agent_definition_id", "prompt"),
        security_requirements=("LLM prompt and retrieved context must be auditable.",),
        project_visibility_implications=("Agent availability is filtered by project policy.",),
    ),
    FlowNodeContract(
        type="tool_step",
        display_name="Tool Step",
        category="Tools",
        description="Calls one configured tool or a constrained allowlist of tools.",
        config_schema=_object_schema(
            {
                "tool": {"type": "string"},
                "allowed_tools": {"type": "array", "items": {"type": "string"}},
            }
        ),
        input_schema={"arguments": "object"},
        output_schema={"result": "object"},
        calls_tools=True,
        required_config_any=("tool", "allowed_tools"),
        security_requirements=("Tool must be visible to the project and approved by policy.",),
        project_visibility_implications=("Tool choices are filtered by project tool visibility.",),
    ),
    FlowNodeContract(
        type="retrieval",
        display_name="Retrieval / Knowledge Search",
        category="Tools",
        description="Retrieves evidence from Knowledge, connectors, or governed search tools.",
        config_schema=_object_schema(
            {
                "query_template": {"type": "string"},
                "allowed_tools": {"type": "array", "items": {"type": "string"}},
            }
        ),
        input_schema={"query": "string"},
        output_schema={"evidence": "array", "known_gaps": "array"},
        calls_tools=True,
        security_requirements=("Retrieval scope must honor project connector and knowledge access.",),
        project_visibility_implications=("Knowledge and connector results are project-scoped.",),
    ),
    FlowNodeContract(
        type="router",
        display_name="Router / Conditional",
        category="Logic",
        description="Selects an outgoing path based on typed input or policy conditions.",
        config_schema=_object_schema(
            {
                "routes": {
                    "type": "array",
                    "description": (
                        "Ordered route rules; the first match wins. Each item uses route plus a when object, for "
                        'example {"route":"found","when":{"field":"total","operator":"gt","value":0}}. Operators: '
                        "equals (eq, ==), not_equals (neq, !=), in/not_in (list), contains/not_contains, "
                        "gt/gte/lt/lte (finite number), exists/truthy (true/false). A missing, null or {} when "
                        "always matches. A "
                        "malformed rule is refused on save and fails the run (router_rule_invalid), never the "
                        "default route."
                    ),
                    "items": {"type": "object"},
                },
                "default_route": {
                    "type": "string",
                    "description": "Route emitted when no route condition matches.",
                },
            }
        ),
        input_schema={"context": "object"},
        output_schema={"route": "string", "context": "object"},
    ),
    FlowNodeContract(
        type="parallel",
        display_name="Parallel Group",
        category="Logic",
        description="Starts a bounded set of parallel branches.",
        config_schema=_object_schema({"max_parallel": {"type": "integer"}}),
        input_schema={"context": "object"},
        output_schema={"branches": "array"},
    ),
    FlowNodeContract(
        type="join",
        display_name="Join / Merge",
        category="Logic",
        description="Merges branch outputs into a single typed context.",
        input_schema={"branches": "array"},
        output_schema={"context": "object"},
    ),
    FlowNodeContract(
        type="approval",
        display_name="Approval / HITL",
        category="Human In The Loop",
        description="Pauses execution until a human approves, rejects, or supplies input.",
        config_schema=_object_schema({"approval_policy": {"type": "string"}}),
        input_schema={"proposal": "object"},
        output_schema={"approved": "boolean", "proposal": "object"},
        can_pause=True,
        security_requirements=("Approval decision must be audited before downstream action.",),
    ),
    FlowNodeContract(
        type="human_task",
        display_name="Human Task",
        category="Human In The Loop",
        description="Requests structured human review or input during a flow.",
        config_schema=_object_schema({"review_policy": {"type": "string"}}),
        input_schema={"task": "object"},
        output_schema={"human_response": "object"},
        can_pause=True,
        security_requirements=("Human response must be tied to user identity and audit record.",),
    ),
    FlowNodeContract(
        type="evaluation",
        display_name="Evaluation / Quality Gate",
        category="Quality",
        description=(
            "Not executable in a flow graph (a run fails explicitly instead of passing unjudged); a workflow "
            "that runs in phases uses a gate over the evidence its phases recorded."
        ),
        config_schema=_object_schema({"quality_gate": {"type": "string"}}, ["quality_gate"]),
        input_schema={"candidate": "object"},
        output_schema={"quality_passed": "boolean", "candidate": "object"},
        required_config_keys=("quality_gate",),
        security_requirements=("Blocking quality gates must be enforced before publish/action.",),
    ),
    FlowNodeContract(
        type="learning_proposal",
        display_name="Learning Proposal",
        category="Learning",
        description="Creates review-first learning candidates from session or run evidence.",
        config_schema=_object_schema({"target": {"type": "string"}}, ["target"]),
        input_schema={"learning_candidates": "array"},
        output_schema={"created_learning_ids": "array"},
        required_config_keys=("target",),
        security_requirements=("Learning must remain review-first before Knowledge promotion.",),
    ),
    FlowNodeContract(
        type="error_handler",
        display_name="Error Handler",
        category="Reliability",
        description="Handles node or branch errors with a typed fallback path.",
        config_schema=_object_schema({"strategy": {"type": "string"}}),
        input_schema={"error": "object"},
        output_schema={"recovered": "boolean", "result": "object"},
    ),
    FlowNodeContract(
        type="supervisor",
        display_name="Supervisor",
        category="AI",
        description="Coordinates delegated child steps or agents under an explicit prompt.",
        config_schema=_object_schema(
            {
                "agent_definition_id": {"type": "string"},
                "prompt": {"type": "string"},
            }
        ),
        input_schema={"context": "object"},
        output_schema={"result": "object"},
        calls_llm=True,
        required_config_any=("agent_definition_id", "prompt"),
        security_requirements=("Delegation plan and child outputs must be traceable.",),
    ),
    FlowNodeContract(
        type="subflow",
        display_name="Subflow",
        category="Composition",
        description=(
            "Not executable in a flow graph (a run fails explicitly); a workflow that runs in phases uses a "
            "sub_workflow node."
        ),
        config_schema=_object_schema({"flow_definition_id": {"type": "string"}}, ["flow_definition_id"]),
        input_schema={"input": "object"},
        output_schema={"result": "object"},
        required_config_keys=("flow_definition_id",),
        project_visibility_implications=("Referenced subflow must be visible to the project.",),
    ),
)

FLOW_NODE_REGISTRY: dict[str, FlowNodeContract] = {item.type: item for item in FLOW_NODE_CONTRACTS}


def get_flow_node_contract(node_type: str) -> FlowNodeContract | None:
    return FLOW_NODE_REGISTRY.get(node_type)


def list_flow_node_contracts() -> list[FlowNodeContract]:
    return list(FLOW_NODE_CONTRACTS)


def serialize_flow_node_registry() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "items": [contract.serialize() for contract in FLOW_NODE_CONTRACTS],
    }


__all__ = [
    "FLOW_NODE_CONTRACTS",
    "FLOW_NODE_REGISTRY",
    "get_flow_node_contract",
    "list_flow_node_contracts",
    "serialize_flow_node_registry",
]
