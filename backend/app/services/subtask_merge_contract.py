"""Controlled merge contract for delegated child-session work."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..models import Session, ToolCall
from ..time_utils import utc_now

MERGE_CONTRACT_SCHEMA_VERSION = "1.0"
MERGE_CONTRACT_KIND = "subtask_merge_contract"


def build_subtask_merge_contract(
    *,
    parent_session: Session | None,
    child_sessions: list[Session],
    accepted_subthreads: list[dict[str, Any]],
    rejected_subthreads: list[dict[str, Any]],
    tool_calls_by_session: dict[str, list[ToolCall]],
) -> dict[str, Any]:
    accepted_ids = {str(item.get("session_id") or "").strip() for item in accepted_subthreads}
    rejected_ids = {str(item.get("session_id") or "").strip() for item in rejected_subthreads}
    tasks = [
        _task_contract(
            child,
            accepted=child.id in accepted_ids,
            rejected=child.id in rejected_ids,
            tool_calls=tool_calls_by_session.get(child.id, []),
        )
        for child in child_sessions
    ]
    conflicts = _detect_conflicts(tasks)
    incomplete = [
        task
        for task in tasks
        if str(task.get("status") or "").strip().lower() not in {"completed", "done"}
    ]
    rejected = [task for task in tasks if task.get("accepted") is False]
    status = _derive_status(conflicts=conflicts, incomplete=incomplete, rejected=rejected)
    return {
        "schema_version": MERGE_CONTRACT_SCHEMA_VERSION,
        "kind": MERGE_CONTRACT_KIND,
        "parent_session_id": parent_session.id if parent_session is not None else "",
        "status": status,
        "requires_review": status in {"blocked_conflicts", "blocked_incomplete", "blocked_rejected"},
        "updated_at": utc_now().isoformat(),
        "task_count": len(tasks),
        "accepted_count": sum(1 for task in tasks if task.get("accepted") is True),
        "rejected_count": sum(1 for task in tasks if task.get("accepted") is False),
        "conflict_count": len(conflicts),
        "tasks": tasks,
        "conflicts": conflicts,
        "policy": {
            "merge_requires_all_children_completed": True,
            "merge_requires_accepted_children": True,
            "merge_blocks_on_overlapping_write_areas": True,
            "merge_blocks_on_overlapping_changed_files": True,
            "automatic_conflict_resolution": False,
        },
    }


def persist_subtask_merge_contract(parent_session: Session | None, contract: dict[str, Any]) -> None:
    if parent_session is None:
        return
    metadata = dict(parent_session.metadata_ or {})
    metadata["subtask_merge_contract"] = contract
    parent_session.metadata_ = metadata


def _task_contract(
    child: Session,
    *,
    accepted: bool,
    rejected: bool,
    tool_calls: list[ToolCall],
) -> dict[str, Any]:
    metadata = dict(child.metadata_ or {})
    changed_files = _dedupe_paths(
        _paths_from_metadata(metadata, ("changed_files", "modified_files", "touched_files"))
        + _changed_files_from_tool_calls(tool_calls)
    )
    write_areas = _dedupe_paths(
        _paths_from_metadata(
            metadata,
            (
                "delegated_write_areas",
                "write_areas",
                "owned_paths",
                "scope_paths",
                "assigned_paths",
            ),
        )
    )
    status = str(child.status or "").strip().lower()
    return {
        "session_id": child.id,
        "title": str(metadata.get("title") or child.id),
        "agent_type": child.agent_type,
        "status": status,
        "sub_agent_depth": child.sub_agent_depth,
        "accepted": bool(accepted) and not rejected,
        "rejected": bool(rejected),
        "write_areas": write_areas,
        "changed_files": changed_files,
        "ownership_known": bool(write_areas or changed_files),
    }


def _derive_status(
    *,
    conflicts: list[dict[str, Any]],
    incomplete: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> str:
    if conflicts:
        return "blocked_conflicts"
    if incomplete:
        return "blocked_incomplete"
    if rejected:
        return "blocked_rejected"
    return "merge_ready"


def _detect_conflicts(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    conflicts.extend(_path_conflicts(tasks, key="changed_files", conflict_type="changed_file_overlap"))
    conflicts.extend(_path_conflicts(tasks, key="write_areas", conflict_type="write_area_overlap"))
    return conflicts


def _path_conflicts(tasks: list[dict[str, Any]], *, key: str, conflict_type: str) -> list[dict[str, Any]]:
    owners_by_path: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        session_id = str(task.get("session_id") or "")
        for path in task.get(key) or []:
            normalized = _normalize_path(path)
            if normalized:
                owners_by_path[normalized].append(session_id)
    conflicts = []
    for path, owners in sorted(owners_by_path.items()):
        unique_owners = sorted(set(owners))
        if len(unique_owners) > 1:
            conflicts.append({"type": conflict_type, "path": path, "child_session_ids": unique_owners})

    paths = sorted(owners_by_path)
    for index, left in enumerate(paths):
        for right in paths[index + 1 :]:
            if not _paths_overlap(left, right):
                continue
            owners = sorted(set(owners_by_path[left] + owners_by_path[right]))
            if len(owners) > 1:
                conflict = {
                    "type": conflict_type,
                    "path": left,
                    "overlaps_with": right,
                    "child_session_ids": owners,
                }
                if conflict not in conflicts:
                    conflicts.append(conflict)
    return conflicts


def _paths_from_metadata(metadata: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = metadata.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item).strip())
    return values


def _changed_files_from_tool_calls(tool_calls: list[ToolCall]) -> list[str]:
    paths: list[str] = []
    for call in tool_calls:
        result = call.result if isinstance(call.result, dict) else {}
        contract = result.get("workspace_change_safety_contract")
        if not isinstance(contract, dict):
            nested_result = result.get("result")
            contract = (
                nested_result.get("workspace_change_safety_contract") if isinstance(nested_result, dict) else {}
            )
        if not isinstance(contract, dict):
            continue
        for key in ("changed_files", "new_dirty_paths", "preserved_dirty_paths", "target_paths"):
            value = contract.get(key)
            if isinstance(value, str):
                paths.append(value)
            elif isinstance(value, list):
                paths.extend(str(item) for item in value if str(item).strip())
    return paths


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        normalized = _normalize_path(path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result[:100]


def _normalize_path(path: Any) -> str:
    return str(path or "").strip().replace("\\", "/").strip("/")


def _paths_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    return right.startswith(f"{left}/") or left.startswith(f"{right}/")
