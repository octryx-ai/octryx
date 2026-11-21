"""Summaries of node outputs: evidence, artifact references, trace references, usage and cost."""

from __future__ import annotations

from typing import Any

from ..decision_trace import build_node_decision_trace


def _normalize_tool_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    data = getattr(result, "data", None)
    error = getattr(result, "error", None)
    if isinstance(data, dict):
        payload = dict(data)
        if error:
            payload["error"] = error
        return payload
    return {"result": result}


def _evidence_summary(output: dict[str, Any]) -> dict[str, Any]:
    result = output.get("result") if isinstance(output.get("result"), dict) else output
    if not isinstance(result, dict):
        return {}
    examples = _result_examples(result)
    summary = {
        "result_keys": sorted(str(key) for key in result.keys())[:20],
        "count": _first_present(result, ("count", "total", "total_matches", "total_count")),
        "query": _first_present(result, ("query", "cql", "jql")),
        "source_counts": _first_present(result, ("source_counts", "sources", "by_source")),
        "artifact_id": _first_present(result, ("artifact_id", "_artifact_id")),
    }
    if examples:
        summary["examples"] = examples
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def _trace_refs(
    node: dict[str, Any],
    output: dict[str, Any],
    *,
    status: str,
    input_snapshot: dict[str, Any],
    evidence_summary: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    node_type = str(node.get("type") or "")
    refs: dict[str, Any] = {
        "node_label": node.get("label"),
        "node_type": node_type,
        "status_transition": ["running", status],
    }
    config = node.get("config") or {}
    tool_name = output.get("tool") or config.get("tool") or config.get("tool_name")
    if tool_name:
        refs["tool"] = tool_name
    if output.get("session_id"):
        refs["child_session_id"] = output.get("session_id")
    if output.get("route"):
        refs["selected_route"] = output.get("route")
    if output.get("reason"):
        refs["pause_reason"] = output.get("reason")
    if output.get("error"):
        refs["error"] = output.get("error")
    if node_type in {"approval", "human_task", "learning_proposal"}:
        refs["requires_human_review"] = True
    if artifact_refs:
        refs["artifact_ids"] = [item["artifact_id"] for item in artifact_refs if item.get("artifact_id")]
    refs["decision_trace"] = build_node_decision_trace(
        node=node,
        input_snapshot=input_snapshot,
        output=output,
        status=status,
        evidence_summary=evidence_summary,
        artifact_refs=artifact_refs,
    )
    return {key: value for key, value in refs.items() if value not in (None, "", [], {})}


def _artifact_refs(output: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    _collect_artifact_refs(output, refs)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        artifact_id = str(ref.get("artifact_id") or "")
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        deduped.append(ref)
    return deduped[:20]


def _collect_artifact_refs(value: Any, refs: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        artifact_id = value.get("artifact_id") or value.get("_artifact_id")
        if artifact_id:
            refs.append(
                {
                    "artifact_id": str(artifact_id),
                    "storage": value.get("_artifact_storage") or value.get("storage"),
                    "sha256": value.get("content_sha256"),
                    "payload_size_bytes": value.get("payload_size_bytes"),
                }
            )
        artifact_ids = value.get("artifact_ids")
        if isinstance(artifact_ids, list):
            refs.extend({"artifact_id": str(item)} for item in artifact_ids if item)
        for item in value.values():
            _collect_artifact_refs(item, refs)
    elif isinstance(value, list):
        for item in value[:100]:
            _collect_artifact_refs(item, refs)


def _token_usage(output: dict[str, Any]) -> dict[str, Any]:
    usage = output.get("usage") or output.get("token_usage")
    if isinstance(usage, dict):
        return dict(usage)
    result = output.get("result")
    if isinstance(result, dict):
        nested = result.get("usage") or result.get("token_usage")
        if isinstance(nested, dict):
            return dict(nested)
    return {}


def _cost_estimate(output: dict[str, Any]) -> dict[str, Any]:
    cost = output.get("cost") or output.get("cost_estimate")
    if isinstance(cost, dict):
        return dict(cost)
    result = output.get("result")
    if isinstance(result, dict):
        nested = result.get("cost") or result.get("cost_estimate")
        if isinstance(nested, dict):
            return dict(nested)
    return {}


def _result_examples(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("results") or result.get("items") or result.get("matches")
    if not isinstance(rows, list):
        return []
    examples: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        examples.append(
            {
                key: row.get(key)
                for key in (
                    "id",
                    "key",
                    "title",
                    "summary",
                    "status",
                    "url",
                    "source",
                    "space_key",
                    "repository",
                    "author",
                    "updated_when",
                )
                if row.get(key) not in (None, "")
            }
        )
    return [item for item in examples if item]


def _first_present(value: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in value and value[key] not in (None, "", [], {}):
            return value[key]
    return None


def _flow_final(output: dict[str, Any]) -> dict[str, Any]:
    """A flow's output as people and callers read it: no fence markers (fence only at a model's input).

    Node outputs stay as they ran (an agent node downstream reads its tool step's result fenced); the output node and
    the run's ``final`` are the exit, so a fenced live read passed through to the end never shows its markers."""
    from ...content_security.knowledge_fence import unfenced_result

    return unfenced_result(output)
