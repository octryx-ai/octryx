"""Evidence-contract follow-up helpers for tool-loop runtime decisions.

The loop core carries NO tool lists here: evidence contracts are attached to
tool results by their single producer
(``app.services.tool_result_compression.evidence_contracts``), which owns the
per-connector tool sets. A result that carries a contract IS an evidence tool
by construction — presence and status decide, not name matching.
"""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt


def critical_incomplete_evidence_contracts(tool_results: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    incomplete: list[dict[str, Any]] = []
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        contract = _evidence_contract_from_tool_result(item)
        if not isinstance(contract, dict) or contract.get("status") != "failed":
            continue
        incomplete.append(
            {
                "tool_name": tool_name,
                "artifact_id": str(item.get("artifact_id") or "").strip(),
                "missing_paths": [
                    str(path)
                    for path in (contract.get("missing_paths") or [])
                    if str(path or "").strip()
                ],
                "hard_capped": bool(contract.get("hard_capped")),
                "evidence_state": str(contract.get("evidence_state") or "incomplete_compact_evidence"),
            }
        )
    return incomplete


def build_incomplete_evidence_contract_reminder(items: list[dict[str, Any]]) -> str:
    summaries = []
    artifact_ids: list[str] = []
    for item in items:
        tool_name = str(item.get("tool_name") or "").strip()
        artifact_id = str(item.get("artifact_id") or "").strip()
        if artifact_id:
            artifact_ids.append(artifact_id)
        missing_paths = item.get("missing_paths") if isinstance(item.get("missing_paths"), list) else []
        missing = ", ".join(str(path) for path in missing_paths[:6]) or render_prompt(
            "guard.evidence.hard_capped_label"
        )
        summaries.append(f"{tool_name}: {missing}")
    artifact_hint = ""
    if artifact_ids:
        rendered_ids = ", ".join(f"`{artifact_id}`" for artifact_id in artifact_ids[:4])
        artifact_hint = render_prompt("guard.evidence.artifact_hint", rendered_ids=rendered_ids)
    return render_prompt(
        "guard.evidence.incomplete_reminder", incomplete_evidence="; ".join(summaries), artifact_hint=artifact_hint
    )


def _evidence_contract_from_tool_result(item: dict[str, Any]) -> dict[str, Any] | None:
    compact_result = item.get("compact_result") if isinstance(item.get("compact_result"), dict) else None
    result = item.get("result") if isinstance(item.get("result"), dict) else None
    candidates = []
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


__all__ = [
    "build_incomplete_evidence_contract_reminder",
    "critical_incomplete_evidence_contracts",
]
