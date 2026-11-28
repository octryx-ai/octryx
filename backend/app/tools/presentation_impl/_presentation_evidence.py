"""Turn evidence for the deterministic presentation composer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...services.turn_tool_history import (
    _latest_successful_tool_result,
    _successful_tool_results,
)

_logger = logging.getLogger("uvicorn.error")

# The tools whose successful results this module reads.
AWS_SNAPSHOT_TOOL = "aws_topology_snapshot"
KNOWLEDGE_SEARCH_TOOL = "knowledge_search"
DIAGRAM_TOOL_NAMES = ("create_diagram", "append_diagram")

MAX_KNOWLEDGE_FACTS = 12
MAX_DIAGRAM_IMAGES = 4
_PNG_RENDER_SCALE = 2


def aws_snapshot_from_history(turn_tool_history: list[dict[str, Any]] | None) -> dict[str, Any]:
    history = [item for item in (turn_tool_history or []) if isinstance(item, dict)]
    snapshot = _latest_successful_tool_result(history, AWS_SNAPSHOT_TOOL)
    return snapshot if isinstance(snapshot, dict) else {}


def externalized_snapshot_artifact_id(turn_tool_history: list[dict[str, Any]] | None) -> str:
    for item in reversed([item for item in (turn_tool_history or []) if isinstance(item, dict)]):
        if str(item.get("tool_name") or "").strip() != AWS_SNAPSHOT_TOOL:
            continue
        result = item.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        if snapshot_is_usable(result):
            return ""
        return str(result.get("artifact_id") or item.get("artifact_id") or "").strip()
    return ""


def snapshot_is_usable(snapshot: dict[str, Any]) -> bool:
    if not isinstance(snapshot, dict) or not snapshot:
        return False
    if snapshot.get("_hard_capped"):
        return False
    return bool(snapshot.get("service_summary")) or bool(snapshot.get("account_id"))


async def load_snapshot_artifact(db: Any, artifact_id: str) -> dict[str, Any]:
    if db is None or not artifact_id:
        return {}
    from app.services.artifact_store.records import load_tool_artifact_record, read_tool_artifact_payload

    record = await load_tool_artifact_record(db, artifact_id=artifact_id)
    if record is None:
        return {}
    payload = read_tool_artifact_payload(record)
    return payload if isinstance(payload, dict) else {}


async def load_full_diagram_xml(db: Any, *, session_id: str, diagram_id: str) -> str:
    diagram_id = str(diagram_id or "").strip()
    if db is None or not str(session_id or "").strip() or not diagram_id:
        return ""
    from sqlalchemy import select

    from app.services.artifact_store.records import load_tool_artifact_record, read_tool_artifact_payload

    from ...models import ToolCall

    rows = (
        (
            await db.execute(
                select(ToolCall)
                .where(
                    ToolCall.session_id == str(session_id).strip(),
                    ToolCall.tool_name.in_(sorted(DIAGRAM_TOOL_NAMES)),
                )
                .order_by(ToolCall.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    for tool_call in rows:
        record = await load_tool_artifact_record(db, artifact_id=str(tool_call.id))
        payload = read_tool_artifact_payload(record) if record is not None else tool_call.result
        if not isinstance(payload, dict):
            continue
        if str(payload.get("diagram_id") or "").strip() != diagram_id:
            continue
        xml = str(payload.get("diagram_xml") or "").strip()
        if xml:
            return xml
    return ""


def knowledge_facts_from_history(turn_tool_history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    history = [item for item in (turn_tool_history or []) if isinstance(item, dict)]
    facts: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in _successful_tool_results(history, KNOWLEDGE_SEARCH_TOOL):
        entries = result.get("evidence")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            statement = _first_non_empty(entry, ("text",))
            source = _first_non_empty(entry, ("cite_as", "source_url"))
            # Both halves are mandatory: a statement without a traceable source
            # is exactly the unsourced claim the deck must not carry.
            if not statement or not source:
                continue
            if source in seen:
                continue
            seen.add(source)
            facts.append({"statement": statement, "source": source})
            if len(facts) >= MAX_KNOWLEDGE_FACTS:
                return facts
    return facts


async def diagram_images_from_history(
    turn_tool_history: list[dict[str, Any]] | None,
    *,
    output_dir: Path,
    db: Any = None,
    session_id: str = "",
) -> tuple[list[dict[str, str]], list[str]]:
    from ...services.diagram_export_service import (
        DiagramRenderError,
        DiagramRendererUnavailableError,
        render_diagram_png,
    )

    history = [item for item in (turn_tool_history or []) if isinstance(item, dict)]
    images: list[dict[str, str]] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()

    for tool_name in DIAGRAM_TOOL_NAMES:
        for result in _successful_tool_results(history, tool_name):
            diagram_id = str(result.get("diagram_id") or "").strip()
            preview_xml = str(result.get("diagram_xml") or "").strip()
            title = str(result.get("title") or "").strip()
            if not diagram_id or not preview_xml:
                continue
            if diagram_id in seen_ids:
                continue
            seen_ids.add(diagram_id)
            if len(images) >= MAX_DIAGRAM_IMAGES:
                warnings.append(
                    f"diagram '{title or diagram_id}' omitted: only {MAX_DIAGRAM_IMAGES} diagram slides are composed"
                )
                continue
            full_xml = await load_full_diagram_xml(db, session_id=session_id, diagram_id=diagram_id)
            diagram_xml = full_xml or preview_xml
            if not full_xml:
                warnings.append(
                    f"diagram '{title or diagram_id}' embedded from a capped preview: "
                    "the full diagram XML could not be loaded, so the image may be incomplete"
                )
            try:
                png_bytes = render_diagram_png(
                    diagram_id=diagram_id, diagram_xml=diagram_xml, scale=_PNG_RENDER_SCALE
                )
            except DiagramRendererUnavailableError as exc:
                warnings.append(f"renderer_unavailable: diagram '{title or diagram_id}' not embedded ({exc})")
                continue
            except DiagramRenderError as exc:
                warnings.append(f"render_failed: diagram '{title or diagram_id}' not embedded ({exc})")
                continue
            image_path = output_dir / f"diagram-{diagram_id}.png"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(png_bytes)
            images.append({"path": str(image_path), "title": title, "diagram_id": diagram_id})

    _logger.info(
        "presentation evidence: diagrams=%d warnings=%d history_items=%d",
        len(images),
        len(warnings),
        len(history),
    )
    return images, warnings


def _first_non_empty(entry: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    return ""
