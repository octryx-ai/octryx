"""Timeline events of execution: runtime responses, tool results with their evidence, and quality checks."""

from __future__ import annotations

from typing import Any

from .timeline import append_decision_timeline_event


def append_runtime_response_event(
    context_snapshot: dict[str, Any],
    *,
    runtime: dict[str, Any],
    model: str,
    tool_calls: list[dict[str, Any]] | None,
    content: str,
) -> dict[str, Any]:
    selected_tools = [
        str(call.get("function", {}).get("name") or call.get("tool_name") or "").strip()
        for call in tool_calls or []
        if isinstance(call, dict)
    ]
    if selected_tools:
        return append_decision_timeline_event(
            context_snapshot,
            phase="runtime",
            title="Runtime returned tool calls",
            status="ok",
            detail=f"The selected runtime requested {len(selected_tools)} tool call(s).",
            metadata={
                "provider": runtime.get("provider_name"),
                "model": model,
                "tool_calls": [tool for tool in selected_tools if tool],
            },
        )
    return append_decision_timeline_event(
        context_snapshot,
        phase="runtime",
        title="Runtime returned final text",
        status="info",
        detail="The selected runtime did not request a tool call in this response.",
        metadata={
            "provider": runtime.get("provider_name"),
            "model": model,
            "content_chars": len(str(content or "")),
        },
    )


def append_tool_execution_event(
    context_snapshot: dict[str, Any],
    *,
    tool_results: list[dict[str, Any]],
    forced_tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    names = [
        str(item.get("tool_name") or "").strip()
        for item in tool_results or []
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    ]
    errors = [
        name
        for name, item in zip(names, tool_results, strict=False)
        if isinstance(item, dict)
        and (
            item.get("status") in {"error", "failed"}
            or (isinstance(item.get("result"), dict) and item["result"].get("error"))
            or (isinstance(item.get("compact_result"), dict) and item["compact_result"].get("error"))
        )
    ]
    forced_names = [
        str(call.get("function", {}).get("name") or call.get("tool_name") or "").strip()
        for call in forced_tool_calls or []
        if isinstance(call, dict)
    ]
    evidence_summary = _summarize_evidence_contracts(tool_results)
    has_incomplete_evidence = bool(evidence_summary.get("failed_tools") or evidence_summary.get("hard_capped_tools"))
    status = "error" if errors else "warning" if has_incomplete_evidence else "ok"
    return append_decision_timeline_event(
        context_snapshot,
        phase="execution",
        title="Tool execution completed",
        status=status,
        detail=f"Executed {len(names)} tool result(s)." if names else "No tool results were produced.",
        metadata={
            "executed_tools": names,
            "failed_tools": errors,
            "forced_tools": [name for name in forced_names if name],
            "evidence_contracts": evidence_summary,
        },
    )


def _evidence_contract_from_tool_result(item: dict[str, Any]) -> dict[str, Any] | None:
    candidates = []
    compact_result = item.get("compact_result") if isinstance(item.get("compact_result"), dict) else None
    result = item.get("result") if isinstance(item.get("result"), dict) else None
    if compact_result is not None:
        candidates.append(compact_result.get("evidence_contract"))
    if result is not None:
        candidates.append(result.get("evidence_contract"))
        nested_compact = result.get("compact_result") if isinstance(result.get("compact_result"), dict) else None
        preview = result.get("preview") if isinstance(result.get("preview"), dict) else None
        preview_compact = (
            preview.get("compact_result")
            if preview is not None and isinstance(preview.get("compact_result"), dict)
            else None
        )
        if nested_compact is not None:
            candidates.append(nested_compact.get("evidence_contract"))
        if preview_compact is not None:
            candidates.append(preview_compact.get("evidence_contract"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def _summarize_evidence_contracts(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    contract_count = 0
    passed_tools: list[str] = []
    failed_tools: list[str] = []
    hard_capped_tools: list[str] = []
    missing_paths_by_tool: dict[str, list[str]] = {}
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        contract = _evidence_contract_from_tool_result(item)
        if contract is None:
            continue
        contract_count += 1
        tool_name = str(item.get("tool_name") or contract.get("tool_name") or "").strip() or "unknown"
        status = str(contract.get("status") or "").strip().lower()
        if status == "passed":
            passed_tools.append(tool_name)
        else:
            failed_tools.append(tool_name)
        if contract.get("hard_capped") is True:
            hard_capped_tools.append(tool_name)
        missing_paths = [
            str(path).strip()
            for path in contract.get("missing_paths") or []
            if str(path).strip()
        ][:8]
        if missing_paths:
            missing_paths_by_tool[tool_name] = missing_paths
    return {
        "contract_count": contract_count,
        "passed_tools": sorted(set(passed_tools)),
        "failed_tools": sorted(set(failed_tools)),
        "hard_capped_tools": sorted(set(hard_capped_tools)),
        "missing_paths_by_tool": missing_paths_by_tool,
    }


def append_quality_event(
    context_snapshot: dict[str, Any],
    *,
    title: str,
    status: str,
    detail: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return append_decision_timeline_event(
        context_snapshot,
        phase="quality",
        title=title,
        status=status,
        detail=detail,
        metadata=metadata,
    )
