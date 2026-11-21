from __future__ import annotations

import re
from typing import Any

DECISION_TRACE_SCHEMA_VERSION = "1.0"
DECISION_TRACE_KIND = "flow_v2_node_decision"
MAX_DECISION_STRING_LENGTH = 320
MAX_DECISION_DICT_ITEMS = 20
MAX_DECISION_LIST_ITEMS = 8
MAX_EVIDENCE_REFS = 5
MAX_ARTIFACT_REFS = 5
REDACTED = "[redacted]"

_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|authorization|bearer|client[_-]?secret|credential|password|private[_-]?key|refresh[_-]?token|secret|token)",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/=-]+|(?:api[_-]?key|password|secret|token)\s*[:=]\s*['\"]?[^'\"\s,}]+)",
    re.IGNORECASE,
)


def build_node_decision_trace(
    *,
    node: dict[str, Any],
    input_snapshot: dict[str, Any],
    output: dict[str, Any],
    status: str,
    evidence_summary: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    node_id = str(node.get("id") or "")
    node_type = str(node.get("type") or "")
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    tool_name = output.get("tool") or config.get("tool") or config.get("tool_name")
    child_session_id = output.get("session_id")
    decision = {
        "schema_version": DECISION_TRACE_SCHEMA_VERSION,
        "kind": DECISION_TRACE_KIND,
        "node": {
            "id": node_id,
            "label": str(node.get("label") or node_id),
            "type": node_type,
            "status": status,
        },
        "basis": _decision_basis(
            node_type=node_type,
            status=status,
            input_snapshot=input_snapshot,
            output=output,
            evidence_summary=evidence_summary,
            artifact_refs=artifact_refs,
        ),
        "source": _decision_source(
            node_type=node_type,
            tool_name=str(tool_name) if tool_name else "",
            child_session_id=str(child_session_id) if child_session_id else "",
            output=output,
        ),
        "next_action": _next_action(node_type=node_type, status=status, output=output),
    }
    return _compact(decision)


def decision_trace_from_refs(trace_refs: dict[str, Any]) -> dict[str, Any]:
    value = trace_refs.get("decision_trace")
    return dict(value) if isinstance(value, dict) else {}


def _decision_basis(
    *,
    node_type: str,
    status: str,
    input_snapshot: dict[str, Any],
    output: dict[str, Any],
    evidence_summary: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    refs = _evidence_refs(output, evidence_summary)
    basis: dict[str, Any] = {
        "rationale": _rationale(node_type=node_type, status=status, output=output),
        "input_keys": sorted(str(key) for key in input_snapshot.keys())[:MAX_DECISION_LIST_ITEMS],
        "output_keys": sorted(str(key) for key in output.keys())[:MAX_DECISION_LIST_ITEMS],
        "evidence_summary": evidence_summary,
    }
    if refs:
        basis["evidence_refs"] = refs
    if artifact_refs:
        basis["artifact_refs"] = artifact_refs[:MAX_ARTIFACT_REFS]
    return basis


def _decision_source(
    *,
    node_type: str,
    tool_name: str,
    child_session_id: str,
    output: dict[str, Any],
) -> dict[str, Any]:
    if tool_name:
        return {"kind": "tool_call", "tool": tool_name}
    if child_session_id:
        return {"kind": "child_session", "session_id": child_session_id}
    if node_type == "router":
        return {"kind": "router", "selected_route": output.get("route")}
    if node_type in {"approval", "human_task", "learning_proposal"}:
        approval = output.get("approval") if isinstance(output.get("approval"), dict) else {}
        return {"kind": "human_review", "approval_id": output.get("approval_id"), "status": approval.get("status")}
    return {"kind": "flow_node"}


def _next_action(*, node_type: str, status: str, output: dict[str, Any]) -> dict[str, Any]:
    if status == "failed":
        return {"action": "stop", "reason": output.get("error") or "node failed"}
    if status == "paused":
        return {"action": "wait_for_review", "reason": output.get("reason") or "human review required"}
    if status == "skipped":
        return {"action": "skip_downstream_branch", "reason": output.get("reason") or "branch not selected"}
    if node_type == "router":
        return {"action": "continue_route", "route": output.get("route") or "default"}
    if node_type == "output":
        return {"action": "complete_flow"}
    return {"action": "continue_downstream"}


def _rationale(*, node_type: str, status: str, output: dict[str, Any]) -> str:
    if status == "failed":
        return "The node failed and the flow must stop before downstream work can continue."
    if status == "paused":
        return "The node produced a review requirement, so the flow is paused before downstream execution."
    if status == "skipped":
        return "The node was skipped because its upstream branch was not selected."
    if node_type in {"trigger", "input_schema", "input"}:
        return "The flow accepted initial input and made it available to downstream nodes."
    if node_type in {"tool_step", "retrieval"}:
        return "The configured tool was executed and its bounded evidence summary is available to downstream nodes."
    if node_type == "agent_step":
        return "A child agent step was executed and the child session/output was captured for downstream use."
    if node_type == "router":
        return f"The router selected route `{output.get('route') or 'default'}` from the configured routing rules."
    if node_type == "parallel":
        return "The flow opened parallel downstream branches."
    if node_type == "join":
        return "The flow joined upstream branch outputs according to the configured join strategy."
    if node_type == "approval":
        return "The node requires explicit human approval before downstream work can continue."
    if node_type == "evaluation":
        return "The node evaluated the configured quality gate result for downstream use."
    if node_type == "output":
        return "The node produced the final flow output from upstream materialized input."
    return "The node completed and passed its output to downstream execution."


def _evidence_refs(output: dict[str, Any], evidence_summary: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    examples = evidence_summary.get("examples")
    if isinstance(examples, list):
        refs.extend(_compact_evidence_ref(item) for item in examples if isinstance(item, dict))
    result = output.get("result") if isinstance(output.get("result"), dict) else output
    if isinstance(result, dict):
        rows = result.get("results") or result.get("items") or result.get("matches")
        if isinstance(rows, list):
            refs.extend(_compact_evidence_ref(item) for item in rows if isinstance(item, dict))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        identity = "|".join(str(ref.get(key) or "") for key in ("id", "key", "title", "url", "source"))
        if not identity.strip("|") or identity in seen:
            continue
        seen.add(identity)
        deduped.append(ref)
        if len(deduped) >= MAX_EVIDENCE_REFS:
            break
    return deduped


def _compact_evidence_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in ("id", "key", "title", "summary", "source", "space_key", "status", "url", "author")
        if item.get(key) not in (None, "", [], {})
    }


def _compact(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _compact_string(value)
    if isinstance(value, list):
        items = [_compact(item, depth=depth + 1) for item in value[:MAX_DECISION_LIST_ITEMS]]
        if len(value) > MAX_DECISION_LIST_ITEMS:
            items.append({"_truncated_items": len(value) - MAX_DECISION_LIST_ITEMS})
        return items
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            key_text = str(key)
            if index >= MAX_DECISION_DICT_ITEMS:
                compacted["_truncated_keys"] = len(value) - MAX_DECISION_DICT_ITEMS
                break
            if _SECRET_KEY_PATTERN.search(key_text):
                compacted[key_text] = REDACTED
            elif depth > 6:
                compacted[key_text] = "[max-depth]"
            else:
                compacted[key_text] = _compact(item, depth=depth + 1)
        return {key: item for key, item in compacted.items() if item not in (None, "", [], {})}
    return _compact_string(str(value))


def _compact_string(value: str) -> str:
    if _SECRET_VALUE_PATTERN.search(value):
        value = _SECRET_VALUE_PATTERN.sub(REDACTED, value)
    if len(value) <= MAX_DECISION_STRING_LENGTH:
        return value
    return f"{value[:MAX_DECISION_STRING_LENGTH]}... [truncated {len(value) - MAX_DECISION_STRING_LENGTH} chars]"


__all__ = [
    "build_node_decision_trace",
    "decision_trace_from_refs",
]
