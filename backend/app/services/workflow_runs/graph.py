"""A workflow that runs in phases: its graph and its closed validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...models.runtime.flow_definition import FlowDefinitionVersion
from .states import OUTCOMES

EXECUTION_KIND_KEY = "execution_kind"
EXECUTION_KIND_PHASED = "phased"

NODE_START = "start"
NODE_PHASE = "phase"
NODE_GATE = "gate"
NODE_DECISION = "decision"
NODE_OUTCOME = "outcome"
NODE_PLATFORM_ACTION = "platform_action"
NODE_CONVERSATION = "user_conversation"
NODE_CONFIRMATION = "user_confirmation"
NODE_WATCH = "watch"
NODE_APPROVAL = "approval"
NODE_SUB_WORKFLOW = "sub_workflow"
NODE_REVIEW = "review"
NODE_PAUSE = "pause"
NODE_PARALLEL = "parallel_work"
NODE_KINDS = frozenset({
    NODE_START, NODE_PHASE, NODE_GATE, NODE_DECISION, NODE_OUTCOME, NODE_PLATFORM_ACTION, NODE_CONVERSATION,
    NODE_CONFIRMATION, NODE_WATCH, NODE_APPROVAL, NODE_SUB_WORKFLOW, NODE_REVIEW, NODE_PAUSE, NODE_PARALLEL,
})
HITL_KINDS = frozenset({NODE_CONVERSATION, NODE_CONFIRMATION, NODE_WATCH, NODE_APPROVAL})

EDGE_NEXT = "next"
EDGE_LOOP = "loop"

PASSED, FAILED = "passed", "failed"
CONFIRMED, CHANGED, STOPPED = "confirmed", "changed", "stopped"
APPROVED, REJECTED = "approved", "rejected"
SUCCEEDED = "succeeded"
DECISION_CHECK_RESULT, DECISION_CHECK_FIELD = "result", "field"
OTHERWISE = "otherwise"
YES, NO = "yes", "no"
# Publish & prove: the deferred PM stage has two independently hashed statements, (a) the functional
# acceptance and (b) the publication, plus the authorised follow-up intent and the declared exception
# (``documentation/acceptance``). Statement (a) routes on its own closed values, never on confirm/change/stop.
SUBJECT_FUNCTIONAL_ACCEPTANCE = "functional_acceptance"
SUBJECT_PUBLICATION = "publication"
SUBJECT_FOLLOWUP = "followup"
SUBJECT_EXCEPTION = "exception"
SUBJECT_DECISIONS = "decisions"
SUBJECT_READINESS = "readiness"
SUBJECT_INTERVIEW = "interview"
ACCEPTED, NOT_TESTABLE_YET = "accepted", "not_testable_yet"
CONFIRMATION_SUBJECTS = frozenset({"test_contract", "ticket_draft", "reproduction", "retry_choice", "advance",
                                   "questions", SUBJECT_FUNCTIONAL_ACCEPTANCE, SUBJECT_PUBLICATION,
                                   SUBJECT_FOLLOWUP, SUBJECT_EXCEPTION, SUBJECT_DECISIONS,
                                   SUBJECT_READINESS, SUBJECT_INTERVIEW})
SUBJECT_ROUTES: dict[str, frozenset[str]] = {
    SUBJECT_FUNCTIONAL_ACCEPTANCE: frozenset({ACCEPTED, NOT_TESTABLE_YET, REJECTED}),
}
WATCH_CONDITIONS = frozenset({
    "pr.approved", "pr.merged", "pr.declined", "ci.succeeded", "ci.failed", "jira.status", "approval.decided",
})
GATE_CHECK_TYPES = frozenset({
    "tool_called", "tool_not_called", "evidence_count", "artifact_created", "citations_present", "test_command_passed",
    "tests_red", "tests_green", "confirmed_tests_intact", "ci_green", "reproduces", "review_passed", "slices_merged",
    "definition_of_ready", "artefact_review_passed", "specification_ready", "evidence_families",
})

_FIXED_ROUTES: dict[str, frozenset[str] | None] = {
    NODE_START: None,
    NODE_PHASE: None,
    NODE_REVIEW: None,
    NODE_PAUSE: None,
    NODE_CONVERSATION: None,
    NODE_GATE: frozenset({PASSED, FAILED}),
    NODE_CONFIRMATION: frozenset({CONFIRMED, CHANGED, STOPPED}),
    NODE_APPROVAL: frozenset({APPROVED, REJECTED}),
    NODE_PLATFORM_ACTION: frozenset({SUCCEEDED, FAILED}),
    NODE_SUB_WORKFLOW: frozenset(OUTCOMES),
    NODE_PARALLEL: frozenset({"done", "replan"}),
}


@dataclass(frozen=True, slots=True)
class PhasedNode:
    id: str
    kind: str
    title: str
    config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PhasedEdge:
    id: str
    source: str
    target: str
    kind: str
    when: str | None
    max_iterations: int | None
    title: str


@dataclass(slots=True)
class PhasedGraph:
    nodes: dict[str, PhasedNode]
    edges: list[PhasedEdge]
    order: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    plan_node: str = ""
    # Compiled node id -> the fragment it came from (``runtime_settings.composition.provenance`` of the run's
    # version; ``fragments.provenance``). Empty for a plain graph; ``parse_phased_definition`` never fills it.
    provenance: dict[str, dict[str, Any]] = field(default_factory=dict)

    def start(self) -> PhasedNode | None:
        return next((node for node in self.nodes.values() if node.kind == NODE_START), None)

    def exits(self, node_id: str) -> list[PhasedEdge]:
        return [edge for edge in self.edges if edge.source == node_id]

    def ordered_nodes(self) -> list[PhasedNode]:
        ordered = [self.nodes[node_id] for node_id in self.order if node_id in self.nodes]
        return ordered + [node for node_id, node in self.nodes.items() if node_id not in self.order]

    def loop_edges(self) -> list[PhasedEdge]:
        return [edge for edge in self.edges if edge.kind == EDGE_LOOP]


def _text(value: Any) -> str:
    return str(value or "").strip()


def is_phased_definition(definition: Any) -> bool:
    return isinstance(definition, dict) and _text(definition.get(EXECUTION_KIND_KEY)) == EXECUTION_KIND_PHASED


def route_values(node: PhasedNode, graph: PhasedGraph | None = None) -> frozenset[str] | None:
    if node.kind == NODE_DECISION:
        if _text(node.config.get("check")) == DECISION_CHECK_FIELD:
            return frozenset({YES, NO})
        options = frozenset(_text(item) for item in node.config.get("options") or [] if _text(item))
        # The fallback route: a value of the graph's otherwise edge (without a graph, a legal route of any decision).
        if graph is None or any(edge.source == node.id and edge.when == OTHERWISE for edge in graph.edges):
            return options | {OTHERWISE}
        return options
    if node.kind == NODE_WATCH:
        return frozenset(_text(item) for item in node.config.get("conditions") or [] if _text(item))
    if node.kind == NODE_PLATFORM_ACTION and _text(node.config.get("action")):
        from .documentation.s1_graph import S1_ACTION_ROUTES
        from .platform.catalog import ACTION_ROUTES

        key = _text(node.config.get("action"))
        return ACTION_ROUTES.get(key) or S1_ACTION_ROUTES.get(key) or _FIXED_ROUTES[NODE_PLATFORM_ACTION]
    if node.kind == NODE_CONFIRMATION and _text(node.config.get("subject")) in SUBJECT_ROUTES:
        return SUBJECT_ROUTES[_text(node.config.get("subject"))]
    return _FIXED_ROUTES.get(node.kind)


def _edge_end(edge: dict[str, Any], *keys: str) -> str:
    return next((_text(edge.get(key)) for key in keys if _text(edge.get(key))), "")


def parse_phased_definition(definition: dict[str, Any]) -> PhasedGraph:
    nodes: dict[str, PhasedNode] = {}
    for raw in definition.get("nodes") or []:
        if not isinstance(raw, dict) or not _text(raw.get("id")):
            continue
        config = dict(raw.get("config") or {}) if isinstance(raw.get("config"), dict) else {}
        node_id = _text(raw.get("id"))
        title = _text(raw.get("label")) or _text(raw.get("title")) or _text(config.get("title")) or node_id
        nodes[node_id] = PhasedNode(node_id, _text(raw.get("type")), title, config)
    edges: list[PhasedEdge] = []
    for index, raw in enumerate(definition.get("edges") or []):
        if not isinstance(raw, dict):
            continue
        raw_max = raw.get("max_iterations")
        edges.append(PhasedEdge(
            id=_text(raw.get("id")) or f"edge-{index + 1}",
            source=_edge_end(raw, "source_node_id", "source", "from_node_id", "from"),
            target=_edge_end(raw, "target_node_id", "target", "to_node_id", "to"),
            kind=_text(raw.get("kind")) or EDGE_NEXT,
            when=_text(raw.get("when")) or None,
            max_iterations=raw_max if type(raw_max) is int else None,
            title=_text(raw.get("label")) or _text(raw.get("title")),
        ))
    budget = definition.get("budget") if isinstance(definition.get("budget"), dict) else {}
    graph = PhasedGraph(nodes=nodes, edges=edges, budget=dict(budget), plan_node=_text(definition.get("plan_node")))
    graph.order = _topological_order(graph) or []
    return graph


def _topological_order(graph: PhasedGraph) -> list[str] | None:
    incoming = {node_id: 0 for node_id in graph.nodes}
    for edge in graph.edges:
        if edge.kind == EDGE_NEXT and edge.target in incoming and edge.source in graph.nodes:
            incoming[edge.target] += 1
    ready = [node_id for node_id in graph.nodes if incoming[node_id] == 0]
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for edge in graph.edges:
            if edge.kind == EDGE_NEXT and edge.source == node_id and edge.target in incoming:
                incoming[edge.target] -= 1
                if incoming[edge.target] == 0:
                    ready.append(edge.target)
    return order if len(order) == len(graph.nodes) else None


async def graph_for_run(db: AsyncSession, run: WorkflowRun) -> PhasedGraph:
    from .fragments.provenance import version_provenance

    version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id or "")
    graph = parse_phased_definition(dict(version.definition_json or {}) if version is not None else {})
    graph.provenance = version_provenance(version)
    from .size_class.merge import merged_graph

    return merged_graph(graph, run)


__all__ = [
    "DECISION_CHECK_FIELD",
    "DECISION_CHECK_RESULT",
    "EDGE_LOOP",
    "EDGE_NEXT",
    "EXECUTION_KIND_PHASED",
    "HITL_KINDS",
    "NODE_KINDS",
    "NODE_PARALLEL",
    "NODE_PAUSE",
    "NO",
    "OTHERWISE",
    "PhasedEdge",
    "PhasedGraph",
    "PhasedNode",
    "graph_for_run",
    "is_phased_definition",
    "parse_phased_definition",
    "route_values",
    "YES",
]
