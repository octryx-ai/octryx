"""OData: response presets per operation, the version a spec declares, and ``$batch`` (not supported)."""

from __future__ import annotations

import copy
from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "odata_v2": {"records_path": "d.results", "pagination": {"type": "next_url", "next_path": "d.__next"}},
    "odata_v2_offset": {"records_path": "d.results", "pagination": {
        "type": "offset", "offset_param": "$skip", "limit_param": "$top", "page_size": 50}},
    "odata_v4": {"records_path": "value", "pagination": {"type": "next_url", "next_path": "@odata.nextLink"}},
}
UNSUPPORTED_BATCH = "odata_batch"
BATCH_MEDIA_TYPE = "multipart/mixed"
#: OData system query options; a spec whose operations use them is OData even without ``x-sap-api-type``.
QUERY_OPTIONS = frozenset({"$filter", "$select", "$expand", "$orderby", "$top", "$skip", "$count", "$inlinecount",
                           "$search", "$skiptoken", "$format"})
_SINGLE_RESULT_ENDINGS = (")", "/$count", "/$value", "/$batch", "}")


def preset(name: str) -> dict[str, Any]:
    return copy.deepcopy(PRESETS[name])


def preset_of(records_path: str | None, pagination: dict[str, Any]) -> str:
    for name, values in PRESETS.items():
        if (records_path or "") == values["records_path"] and pagination == values["pagination"]:
            return name
    return ""


def spec_version(document: dict[str, Any], servers: list[str], operations: list[dict[str, Any]]) -> str | None:
    declared = str(document.get("x-sap-api-type") or "").upper()
    if declared == "ODATAV4":
        return "v4"
    if declared == "ODATA":
        return "v2"
    if any("/odata4/" in server.lower() or "/odata/v4" in server.lower() for server in servers):
        return "v4"
    if any("/sap/opu/odata/" in server.lower() for server in servers):
        return "v2"
    names = {str(param.get("wire_name") or param.get("name")) for operation in operations
             for param in operation.get("parameters") or []}
    return "v4" if names & QUERY_OPTIONS else None


def is_collection_read(method: str, path: str) -> bool:
    return str(method).upper() == "GET" and not str(path).rstrip("/").endswith(_SINGLE_RESULT_ENDINGS)


def import_preset(version: str | None, method: str, path: str) -> str | None:
    if version is None or not is_collection_read(method, path):
        return None
    return "odata_v4" if version == "v4" else "odata_v2"


def inherits(operation: Any) -> bool:
    return not getattr(operation, "pagination", None) and not getattr(operation, "records_path", None)


def effective_response(definition: Any, operation: Any) -> tuple[str | None, dict[str, Any], str]:
    from .pagination import normalize_pagination

    if not inherits(operation):
        return operation.records_path or None, normalize_pagination(operation.pagination), "operation"
    name = str(getattr(definition, "default_preset", None) or "")
    if name in PRESETS and is_collection_read(operation.method, operation.path):
        values = preset(name)
        return values["records_path"], values["pagination"], "definition"
    return None, {"type": "none"}, "none"


def unsupported_reason(path: str, request_body: Any) -> str | None:
    if str(path or "").rstrip("/").endswith("/$batch"):
        return UNSUPPORTED_BATCH
    if isinstance(request_body, dict) and str(request_body.get("media_type") or "").startswith(BATCH_MEDIA_TYPE):
        return UNSUPPORTED_BATCH
    return None


__all__ = [
    "effective_response",
    "inherits",
    "BATCH_MEDIA_TYPE",
    "PRESETS",
    "QUERY_OPTIONS",
    "UNSUPPORTED_BATCH",
    "import_preset",
    "is_collection_read",
    "preset",
    "preset_of",
    "spec_version",
    "unsupported_reason",
]
