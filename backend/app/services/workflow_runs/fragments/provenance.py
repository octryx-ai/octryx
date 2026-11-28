"""Where a compiled node came from: fragment provenance in the run graph, its events and its view."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..graph import PhasedGraph

COMPOSITION_KEY = "composition"
PUBLIC_FIELDS = ("key", "version", "ref")
ADMIN_FIELDS = ("version_id", "checksum")
EVENT_FIELDS = ("key", "version", "checksum", "ref")
RUN_COMPOSITION_FIELDS = ("key", "version", "checksum")


def _composition(version: Any) -> dict[str, Any]:
    settings = getattr(version, "runtime_settings", None) if version is not None else None
    block = dict(settings or {}).get(COMPOSITION_KEY) if isinstance(settings, dict) else None
    return block if isinstance(block, dict) else {}


def _entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("key"), str) or not raw["key"]:
        return None
    version = raw.get("version")
    entry: dict[str, Any] = {
        "ref": str(raw.get("ref") or ""),
        "key": raw["key"],
        "version": version if isinstance(version, int) and not isinstance(version, bool) else None,
        "version_id": str(raw["version_id"]) if raw.get("version_id") else None,
        "checksum": str(raw.get("checksum") or ""),
    }
    if raw.get("node"):
        entry["node"] = str(raw["node"])
    return entry


def version_provenance(version: Any) -> dict[str, dict[str, Any]]:
    raw = _composition(version).get("provenance")
    if not isinstance(raw, dict):
        return {}
    return {str(node_id): entry for node_id, item in raw.items() if (entry := _entry(item)) is not None}


def node_provenance(graph: PhasedGraph, node_id: str) -> dict[str, Any] | None:
    # The pinned version id stays out: every run reader reads the event.
    entry = dict(getattr(graph, "provenance", None) or {}).get(node_id)
    if not isinstance(entry, dict):
        return None
    return {field: entry.get(field) for field in EVENT_FIELDS}


def run_composition(version: Any) -> list[dict[str, Any]]:
    fragments = _composition(version).get("fragments")
    pins: list[dict[str, Any]] = []
    for item in fragments if isinstance(fragments, list) else []:
        entry = _entry(item)
        if entry is not None:
            pins.append({field: entry.get(field) for field in RUN_COMPOSITION_FIELDS})
    return pins


def reader_fragment(entry: dict[str, Any] | None, *, admin: bool) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    fields = PUBLIC_FIELDS + ADMIN_FIELDS if admin else PUBLIC_FIELDS
    return {field: entry.get(field) for field in fields}


def redact_event_detail(kind: str, detail: dict[str, Any], *, admin: bool) -> dict[str, Any]:
    if admin or not isinstance(detail, dict) or ("fragment" not in detail and "composition" not in detail):
        return detail
    redacted = dict(detail)
    if isinstance(redacted.get("fragment"), dict):
        redacted["fragment"] = {key: value for key, value in redacted["fragment"].items() if key not in ADMIN_FIELDS}
    if isinstance(redacted.get("composition"), list):
        redacted["composition"] = [
            {key: value for key, value in item.items() if key not in ADMIN_FIELDS} if isinstance(item, dict) else item
            for item in redacted["composition"]]
    return redacted


async def is_platform_admin(db: Any, user: Any) -> bool:
    if user is None or not getattr(user, "id", None):
        return False
    from ...secure_work.access import work_scope_project_ids

    return await work_scope_project_ids(db, user) is None


__all__ = [
    "ADMIN_FIELDS",
    "COMPOSITION_KEY",
    "PUBLIC_FIELDS",
    "is_platform_admin",
    "node_provenance",
    "reader_fragment",
    "redact_event_detail",
    "run_composition",
    "version_provenance",
]
