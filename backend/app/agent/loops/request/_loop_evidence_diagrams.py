"""Evidence-backed diagram enforcement at the runtime boundary.

Once a turn has collected an ``aws_topology_snapshot`` (or, for source code,
a ``code_structure_snapshot``), a model-authored
``create_diagram``/``append_diagram`` never reaches dispatch: hand-drawn XML
cannot be audited against the evidence and bypasses curation and the quality
gate. The freehand call is replaced with the deterministic renderer output —
AWS evidence first (overview, then the inventory/detail set), otherwise the
code-structure class diagram (evidence is binding).
"""

from __future__ import annotations

import logging
from typing import Any

from ....services.diagrams.aws_topology_diagram import (
    _successful_diagram_artifact_count,
    build_aws_topology_detail_diagram_tool_calls,
    build_aws_topology_diagram_tool_call,
)
from ....services.diagrams.aws_topology_shapes import _NODE_SHAPE_ALIASES
from ....services.turn_tool_history import (
    _build_tool_call,
    _latest_successful_tool_result,
)

# uvicorn.error is guaranteed to reach the process log; module loggers were
# swallowed by the logging config during live debugging.
_logger = logging.getLogger("uvicorn.error")

_DIAGRAM_TOOL_NAMES = {"create_diagram", "append_diagram"}
_ENFORCED_CONTRACT = {"diagram_source": "aws_topology_snapshot", "topic": ""}
_CODE_STRUCTURE_DIAGRAM_TITLE = "Code structure - Class diagram"


def _call_name(tool_call: Any) -> str:
    if not isinstance(tool_call, dict):
        return ""
    return str((tool_call.get("function") or {}).get("name") or "").strip()


def _aws_shape_request_names() -> list[str]:
    names = sorted({aliases[0] for aliases in _NODE_SHAPE_ALIASES.values()})
    return names[:16]


def enforce_evidence_backed_diagrams(
    *,
    tool_calls: list[dict[str, Any]] | None,
    turn_tool_history: list[dict[str, Any]],
    allowed_tool_names: set[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Return (replacement_tool_calls, audit_trace) when a freehand diagram
    call must be swapped for the deterministic render; None when untouched."""
    freehand = [call for call in (tool_calls or []) if _call_name(call) in _DIAGRAM_TOOL_NAMES]
    if not freehand:
        return None
    snapshot = _latest_successful_tool_result(turn_tool_history, "aws_topology_snapshot")
    _logger.info(
        "evidence-diagram check: freehand=%d snapshot_found=%s brief=%s history_items=%d",
        len(freehand),
        isinstance(snapshot, dict) and bool(snapshot),
        isinstance(snapshot, dict) and isinstance(snapshot.get("diagram_brief"), dict),
        len(turn_tool_history or []),
    )
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("diagram_brief"), dict):
        if isinstance(snapshot, dict) and snapshot:
            _logger.info("evidence-diagram check: snapshot keys=%s", sorted(snapshot.keys())[:12])
        # AWS evidence takes precedence; without it, code-structure evidence
        # is equally binding for freehand diagram calls.
        return _enforce_code_structure_diagrams(
            tool_calls=tool_calls,
            freehand=freehand,
            turn_tool_history=turn_tool_history,
            allowed_tool_names=allowed_tool_names,
        )

    return _enforce_aws_topology_diagrams(
        tool_calls=tool_calls,
        freehand=freehand,
        turn_tool_history=turn_tool_history,
        allowed_tool_names=allowed_tool_names,
        snapshot=snapshot,
    )


def _enforce_aws_topology_diagrams(
    *,
    tool_calls: list[dict[str, Any]] | None,
    freehand: list[dict[str, Any]],
    turn_tool_history: list[dict[str, Any]],
    allowed_tool_names: set[str] | None,
    snapshot: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replace freehand diagram calls with the deterministic AWS topology render."""
    kept = [call for call in (tool_calls or []) if _call_name(call) not in _DIAGRAM_TOOL_NAMES]
    shape_library = _latest_successful_tool_result(turn_tool_history, "get_shape_library")
    if not isinstance(shape_library, dict) or not shape_library:
        # deterministic prerequisite instead of freehand drawing
        planned = _build_tool_call(
            "get_shape_library",
            {"library": "aws4", "shape_names": _aws_shape_request_names()},
            allowed_tool_names,
        )
        return kept + planned, _trace("requested_shape_library", freehand, planned)

    if _successful_diagram_artifact_count(turn_tool_history) == 0:
        planned = build_aws_topology_diagram_tool_call(
            dict(_ENFORCED_CONTRACT), snapshot, shape_library, allowed_tool_names
        )
        reason = "rendered_evidence_overview"
    else:
        planned = build_aws_topology_detail_diagram_tool_calls(
            dict(_ENFORCED_CONTRACT), snapshot, shape_library, allowed_tool_names
        )
        reason = "rendered_evidence_details"
    # Never render the same section twice: successive freehand attempts walk
    # through the missing sections (overview -> inventory -> security -> ...).
    existing_titles = _existing_diagram_titles(turn_tool_history)
    planned = [call for call in planned if _planned_title(call) not in existing_titles]
    # Even when nothing is left to render, the freehand call stays dropped:
    # an unauditable diagram is worse than no additional diagram.
    return kept + planned, _trace(reason, freehand, planned)


def _enforce_code_structure_diagrams(
    *,
    tool_calls: list[dict[str, Any]] | None,
    freehand: list[dict[str, Any]],
    turn_tool_history: list[dict[str, Any]],
    allowed_tool_names: set[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Replace freehand diagram calls with the deterministic class-diagram
    render once the turn holds a code_structure_snapshot with a brief."""
    from ....services.diagrams.code_structure_diagrams import (
        build_code_structure_class_diagram_tool_call,
        snapshot_has_renderable_classes,
    )
    from ....services.diagrams.code_structure_terraform_view import (
        build_terraform_diagram_tool_calls,
        snapshot_is_terraform,
    )

    snapshot = _latest_successful_tool_result(turn_tool_history, "code_structure_snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("diagram_brief"), dict):
        return None
    if not snapshot_has_renderable_classes(snapshot):
        return None
    kept = [call for call in (tool_calls or []) if _call_name(call) not in _DIAGRAM_TOOL_NAMES]
    if snapshot_is_terraform(snapshot):
        # Terraform evidence gets the dedicated diagram set (module overview
        # board + per-module details with provider icons); repeated freehand
        # attempts walk the missing set titles like the AWS branch.
        planned = build_terraform_diagram_tool_calls({}, snapshot, allowed_tool_names)
        reason = "rendered_terraform_diagram_set"
    else:
        planned = build_code_structure_class_diagram_tool_call(
            snapshot, allowed_tool_names, title=_CODE_STRUCTURE_DIAGRAM_TITLE
        )
        reason = "rendered_code_structure_class_diagram"
    # Same section discipline as the AWS branch: each deterministic render is
    # produced once; repeated freehand attempts walk the missing sections.
    existing_titles = _existing_diagram_titles(turn_tool_history)
    planned = [call for call in planned if _planned_title(call) not in existing_titles]
    return kept + planned, _trace(reason, freehand, planned)


def _existing_diagram_titles(turn_tool_history: list[dict[str, Any]]) -> set[str]:
    titles: set[str] = set()
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() not in {"create_diagram", "append_diagram", "edit_diagram"}:
            continue
        result = item.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        title = str(result.get("title") or "").strip()
        if title:
            titles.add(title)
    return titles


def _planned_title(tool_call: dict[str, Any]) -> str:
    import json

    arguments = (tool_call.get("function") or {}).get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return ""
    if isinstance(arguments, dict):
        return str(arguments.get("title") or "").strip()
    return ""


def _trace(
    reason: str,
    freehand: list[dict[str, Any]],
    planned: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "rule": "evidence_backed_diagrams",
        "reason": reason,
        "dropped_freehand_calls": [_call_name(call) for call in freehand],
        "planned_tool_names": [_call_name(call) for call in planned],
    }
