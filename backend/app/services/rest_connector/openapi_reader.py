"""A small OpenAPI reader: OpenAPI 3.0/3.1 and Swagger 2 (basic), JSON or YAML, local ``$ref`` only."""

from __future__ import annotations

import copy
import json
from typing import Any

import yaml

from . import odata
from .common import METHODS, READ_METHODS, http_url_problem
from .op_keys import derived_key, key_from_operation_id, unique_key
from .param_names import alias_parameters

_HTTP_METHODS = tuple(method.lower() for method in METHODS)
#: Header parameters the model may never set: the connector owns authentication and the target host.
FORBIDDEN_HEADERS = frozenset({"authorization", "cookie", "host", "proxy-authorization", "x-api-key"})
MAX_REF_DEPTH = 64


class OpenApiError(ValueError):
    pass


def parse_document(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise OpenApiError("The OpenAPI document is empty.")
    try:
        document = json.loads(raw)
    except ValueError:
        try:
            document = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise OpenApiError("The document is neither JSON nor YAML.") from exc
    if not isinstance(document, dict):
        raise OpenApiError("The document is not an object.")
    if not str(document.get("openapi") or document.get("swagger") or ""):
        raise OpenApiError("The document names no 'openapi' or 'swagger' version.")
    return document


def _pointer(root: dict[str, Any], ref: str) -> Any:
    node: Any = root
    for part in ref[2:].split("/") if ref != "#" else []:
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise KeyError(ref)
        node = node[part]
    return node


def resolve_refs(node: Any, root: dict[str, Any], stack: tuple[str, ...] = ()) -> Any:
    if isinstance(node, list):
        return [resolve_refs(item, root, stack) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        if not ref.startswith("#"):
            return {"type": "object", "description": f"External reference not resolved: {ref}"}
        if ref in stack or len(stack) >= MAX_REF_DEPTH:
            return {"type": "object", "description": f"Recursive reference: {ref}"}
        try:
            target = _pointer(root, ref)
        except KeyError:
            return {"type": "object", "description": f"Unresolvable reference: {ref}"}
        siblings = {key: value for key, value in node.items() if key != "$ref"}
        resolved = resolve_refs(copy.deepcopy(target), root, (*stack, ref))
        return {**resolved, **siblings} if isinstance(resolved, dict) else resolved
    return {key: resolve_refs(value, root, stack) for key, value in node.items()}


def _servers(document: dict[str, Any], warnings: list[str]) -> list[str]:
    usable = []
    for url in _server_urls(document):
        problem = http_url_problem(url)
        if problem:
            warnings.append(f"Server '{url}' was left out: it {problem} after its variables' defaults were filled in. "
                            "Enter the real base URL on the connection.")
        else:
            usable.append(url)
    return usable


def _server_urls(document: dict[str, Any]) -> list[str]:
    if document.get("swagger"):
        host = str(document.get("host") or "").strip()
        if not host:
            return []
        schemes = [scheme for scheme in document.get("schemes") or [] if scheme in {"https", "http"}] or ["https"]
        base_path = str(document.get("basePath") or "").rstrip("/")
        return [f"{schemes[0]}://{host}{base_path}"]
    servers = []
    for server in document.get("servers") or []:
        url = str((server or {}).get("url") or "").strip() if isinstance(server, dict) else ""
        variables = (server or {}).get("variables") or {} if isinstance(server, dict) else {}
        for name, variable in variables.items() if isinstance(variables, dict) else []:
            default = (variable or {}).get("default") if isinstance(variable, dict) else None
            if default is not None:
                url = url.replace("{" + str(name) + "}", str(default))
        if url:
            servers.append(url.rstrip("/"))
    return servers


def _auth_from_scheme(scheme: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(scheme.get("type") or "").lower()
    if kind == "apikey":
        location = str(scheme.get("in") or "").lower()
        name = str(scheme.get("name") or "").strip()
        if location == "header" and name:
            return {"scheme": "api_key_header", "header_name": name}
        if location == "query" and name:
            return {"scheme": "api_key_query", "query_name": name}
        return None
    if kind == "http":
        http_scheme = str(scheme.get("scheme") or "").lower()
        return {"bearer": {"scheme": "bearer"}, "basic": {"scheme": "basic"}}.get(http_scheme)
    if kind == "basic":  # Swagger 2
        return {"scheme": "basic"}
    if kind == "oauth2":
        flows = scheme.get("flows") if isinstance(scheme.get("flows"), dict) else {}
        flow = flows.get("clientCredentials") if isinstance(flows.get("clientCredentials"), dict) else None
        if flow is None and str(scheme.get("flow") or "") == "application":  # Swagger 2
            flow = scheme
        if flow and flow.get("tokenUrl"):
            return {
                "scheme": "oauth2_client_credentials",
                "token_url": str(flow["tokenUrl"]),
                "scopes": sorted(str(name) for name in (flow.get("scopes") or {})),
            }
    return None


def _auth(document: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    if document.get("swagger"):
        schemes = document.get("securityDefinitions") or {}
    else:
        schemes = ((document.get("components") or {}).get("securitySchemes")) or {}
    schemes = resolve_refs(schemes, document)
    if not isinstance(schemes, dict) or not schemes:
        return {"scheme": "none"}
    for name, scheme in schemes.items():
        mapped = _auth_from_scheme(scheme) if isinstance(scheme, dict) else None
        if mapped is not None:
            return {**mapped, "source_scheme": str(name)}
    warnings.append(
        "No supported security scheme found (api key, bearer, basic, OAuth2 client credentials); auth is 'none' "
        "until an admin sets it."
    )
    return {"scheme": "none"}


def _parameter(raw: dict[str, Any], swagger: bool) -> dict[str, Any] | None:
    location = str(raw.get("in") or "").lower()
    name = str(raw.get("name") or "").strip()
    if location not in {"path", "query", "header"} or not name:
        return None
    if location == "header" and name.lower() in FORBIDDEN_HEADERS:
        return None
    if swagger:
        schema = {key: raw[key] for key in ("type", "items", "enum", "format", "default", "minimum", "maximum")
                  if key in raw}
    else:
        schema = dict(raw.get("schema") or {}) if isinstance(raw.get("schema"), dict) else {}
    parsed = {
        "name": name,
        "in": location,
        "required": bool(raw.get("required")) or location == "path",
        "description": str(raw.get("description") or "").strip(),
        "schema": schema or {"type": "string"},
    }
    if location == "query" and parsed["schema"].get("type") == "array" and not _exploded(raw, swagger):
        parsed["explode"] = False
    return parsed


def _exploded(raw: dict[str, Any], swagger: bool) -> bool:
    if swagger:
        return str(raw.get("collectionFormat") or "csv") == "multi"
    return raw.get("explode") is not False


def _merged_parameters(path_level: list[Any], op_level: list[Any]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*path_level, *op_level]:
        if isinstance(raw, dict):
            merged[(str(raw.get("name") or ""), str(raw.get("in") or ""))] = raw
    return list(merged.values())


def _request_body(operation: dict[str, Any], parameters: list[dict[str, Any]], swagger: bool) -> dict[str, Any] | None:
    if swagger:
        for raw in parameters:
            if str(raw.get("in") or "") == "body" and isinstance(raw.get("schema"), dict):
                return {"schema": raw["schema"], "required": bool(raw.get("required"))}
        return None
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return None
    content = body.get("content") if isinstance(body.get("content"), dict) else {}
    for media_type, entry in content.items():
        if "json" in str(media_type) and isinstance(entry, dict) and isinstance(entry.get("schema"), dict):
            return {"schema": entry["schema"], "required": bool(body.get("required"))}
    if any(str(media_type).startswith(odata.BATCH_MEDIA_TYPE) for media_type in content):
        # Kept only so the operation is recognizable as an OData $batch (``odata.unsupported_reason``).
        return {"media_type": odata.BATCH_MEDIA_TYPE, "schema": {"type": "string"},
                "required": bool(body.get("required"))}
    return None


def _operations(document: dict[str, Any]) -> list[dict[str, Any]]:
    swagger = bool(document.get("swagger"))
    operations: list[dict[str, Any]] = []
    taken: set[str] = set()
    for path, raw_item in (document.get("paths") or {}).items():
        # Per path item, so components no operation uses are never expanded.
        item = resolve_refs(raw_item, document)
        if not isinstance(item, dict):
            continue
        for method in _HTTP_METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            raw_parameters = _merged_parameters(item.get("parameters") or [], operation.get("parameters") or [])
            parameters = alias_parameters(
                [parsed for parsed in (_parameter(raw, swagger) for raw in raw_parameters) if parsed])
            upper = method.upper()
            operation_id = str(operation.get("operationId") or "").strip()
            base = key_from_operation_id(operation_id) if operation_id else derived_key(method, str(path))
            operations.append({
                "op_key": unique_key(base, method, str(path), taken),
                "method": upper,
                "path": str(path),
                "summary": str(operation.get("summary") or operation.get("description") or "").strip(),
                "parameters": parameters,
                "request_body": _request_body(operation, raw_parameters, swagger),
                "read_only": upper in READ_METHODS,
            })
    return operations


def _mark_odata(operations: list[dict[str, Any]], version: str | None, warnings: list[str]) -> None:
    for operation in operations:
        operation.update({"records_path": None, "pagination": {} if version else {"type": "none"}})
        operation["unsupported"] = odata.unsupported_reason(operation["path"], operation["request_body"])
        if operation["unsupported"]:
            warnings.append(f"'{operation['op_key']}' ({operation['method']} {operation['path']}) is an OData $batch "
                            "request and cannot be enabled: a batch carries several requests past the per-call "
                            "grants and audit. Enable the single operations instead.")
    if version:
        warnings.append(f"OData {version}: the API's default response preset is 'odata_{version}' (records and next "
                        "page of its collection reads); an admin can change it for the API or per operation.")


def read_openapi(text: str) -> dict[str, Any]:
    document = parse_document(text)
    warnings: list[str] = []
    info = document.get("info") if isinstance(document.get("info"), dict) else {}
    operations = _operations(document)
    if not operations:
        warnings.append("The document declares no operations.")
    servers = _servers(document, warnings)
    version = odata.spec_version(document, servers, operations)
    _mark_odata(operations, version, warnings)
    auth = _auth(document, warnings)
    if version and any(not operation["read_only"] for operation in operations) and auth["scheme"] != "none":
        # SAP Gateway refuses a write without a token fetched first (HTTP 403, ``x-csrf-token: Required``). The token
        # comes from the service root, which is the connection's base URL (``.../sap/opu/odata/sap/API_X``): the
        # spec's own server path is the vendor sandbox's (``/s4hanacloud/...``), not the customer system's, so no
        # ``fetch_path`` is taken from it. An admin sets one only when a base URL sits above the service.
        auth["csrf"] = {"fetch": True, "header": "x-csrf-token"}
    return {
        "spec_version": str(document.get("openapi") or document.get("swagger"))[:16],
        "title": str(info.get("title") or "").strip(),
        "description": str(info.get("description") or "").strip(),
        "default_preset": f"odata_{version}" if version else "",
        "odata_version": version or "",
        "servers": servers,
        "auth": auth,
        "operations": operations,
        "warnings": warnings,
    }


__all__ = ["FORBIDDEN_HEADERS", "OpenApiError", "parse_document", "read_openapi", "resolve_refs"]
