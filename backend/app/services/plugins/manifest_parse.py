"""Reading ``octryx-plugin.yaml`` into a checked :class:`manifest.Manifest` (every issue found, never guessed)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import yaml

from .manifest import (
    API_VERSION,
    CONNECTION_KINDS,
    CONTRIBUTION_KEYS,
    HOST_PATTERN,
    ID_PATTERN,
    MANIFEST_FILE,
    MCP_METHOD,
    MCP_TRANSPORTS,
    PERMISSION_KEYS,
    SETTINGS_METHOD,
    TOOL_METHOD,
    TOP_KEYS,
    UI_SLOTS,
    VERSION_PATTERN,
    Manifest,
    ManifestError,
    McpServer,
    _keys,
    _list,
    _text,
    issue,
    package_path,
)


def _mcp_servers(raw: Any, issues: list[dict[str, str]]) -> list[McpServer]:
    servers: list[McpServer] = []
    for index, entry in enumerate(_list(raw, "contributes.mcp_servers", issues)):
        path = f"contributes.mcp_servers[{index}]"
        if not isinstance(entry, dict):
            issues.append(issue("manifest_field_invalid", "An MCP server is {name, url, transport?}.", path))
            continue
        _keys(entry, {"name", "url", "transport", "description", "tools"}, path, issues)
        name = str(entry.get("name") or "").strip()
        url = str(entry.get("url") or "").strip()
        transport = str(entry.get("transport") or "streamable-http").strip()
        parsed = urlparse(url)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", name):
            issues.append(issue("manifest_mcp_name_invalid", "An MCP server name is 2-63 chars of a-z, 0-9, '-'.",
                                f"{path}.name"))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            issues.append(issue("manifest_mcp_url_invalid",
                                "An MCP server URL is https:// without credentials (secrets go into settings).",
                                f"{path}.url"))
        if transport not in MCP_TRANSPORTS:
            issues.append(issue("manifest_mcp_transport_invalid",
                                f"transport is one of: {', '.join(MCP_TRANSPORTS)}.", f"{path}.transport"))
        tools = [str(tool).strip() for tool in _list(entry.get("tools"), f"{path}.tools", issues) if str(tool).strip()]
        servers.append(McpServer(name=name, url=url, transport=transport,
                                 description=str(entry.get("description") or "").strip()[:500], tools=tools))
    return servers


def _ui(raw: Any, issues: list[dict[str, str]]) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        issues.append(issue("manifest_field_invalid", "'contributes.ui' is a mapping.", "contributes.ui"))
        return None
    _keys(raw, {"bundle", "methods", *UI_SLOTS}, "contributes.ui", issues)
    bundle = package_path(raw.get("bundle"), "contributes.ui.bundle", issues) if raw.get("bundle") else None
    methods = []
    for index, value in enumerate(_list(raw.get("methods"), "contributes.ui.methods", issues)):
        name = str(value or "").strip()
        if name == SETTINGS_METHOD or MCP_METHOD.fullmatch(name) or TOOL_METHOD.fullmatch(name):
            methods.append(name)
        else:
            issues.append(issue("manifest_ui_method_invalid", "A method is 'settings.get', an Octryx tool name or "
                                "'<mcp server>.<tool>'.", f"contributes.ui.methods[{index}]"))
    slots: dict[str, Any] = {"bundle": bundle, "methods": sorted(set(methods))}
    for slot, areas in UI_SLOTS.items():
        entries = []
        for index, entry in enumerate(_list(raw.get(slot), f"contributes.ui.{slot}", issues)):
            path = f"contributes.ui.{slot}[{index}]"
            if not isinstance(entry, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", str(entry.get("id") or "")):
                issues.append(issue("manifest_ui_entry_invalid", "A UI entry needs an id (a-z, 0-9, '-').", path))
                continue
            # YAML 1.1 reads a bare ``on:`` key as the boolean True; accept both spellings.
            where = str(entry.get("area") or entry.get("on") or entry.get(True) or "")
            if areas and where not in areas:
                issues.append(issue("manifest_ui_slot_invalid", f"{slot} go on one of: {', '.join(areas)}.", path))
                continue
            entries.append({"id": entry["id"], "title": str(entry.get("title") or entry["id"])[:80],
                            "where": where or None, "entry": str(entry.get("entry") or "index.html")})
        slots[slot] = entries
    if any(slots[slot] for slot in UI_SLOTS) and not bundle:
        issues.append(issue("manifest_ui_bundle_missing", "UI entries need 'bundle' (the folder of the built UI).",
                            "contributes.ui.bundle"))
    return slots


def _server(raw: Any, issues: list[dict[str, str]]) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        issues.append(issue("manifest_field_invalid", "'contributes.server' is a mapping.", "contributes.server"))
        return None
    _keys(raw, {"image", "tools", "port", "resources"}, "contributes.server", issues)
    image = str(raw.get("image") or "").strip()
    if not re.fullmatch(r"[a-z0-9./_:-]+@sha256:[a-f0-9]{64}", image):
        issues.append(issue("manifest_server_image_digest",
                            "The server image is pinned by digest (name@sha256:...): what was reviewed runs.",
                            "contributes.server.image"))
    tools = [str(tool) for tool in _list(raw.get("tools"), "contributes.server.tools", issues)]
    return {"image": image, "tools": tools,
            "port": raw.get("port"), "resources": raw.get("resources") if isinstance(raw.get("resources"), dict)
            else None}


def _names(raw: Any, path: str, allowed: tuple[str, ...] | None, issues: list[dict[str, str]]) -> list[str]:
    values = []
    for index, entry in enumerate(_list(raw, path, issues)):
        value = str(entry or "").strip().lower()
        if allowed is not None and value not in allowed:
            issues.append(issue("manifest_permission_unknown", f"'{value}' is not one of: {', '.join(allowed)}.",
                                f"{path}[{index}]"))
            continue
        if allowed is None and not HOST_PATTERN.match(value):
            issues.append(issue("manifest_egress_invalid", f"'{value}' is not a host name.", f"{path}[{index}]"))
            continue
        values.append(value)
    return sorted(set(values))


def parse_manifest(text: str) -> Manifest:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ManifestError([issue("manifest_yaml_invalid", f"{MANIFEST_FILE} is not valid YAML: {error}")]) from None
    if not isinstance(raw, dict):
        raise ManifestError([issue("manifest_yaml_invalid", f"{MANIFEST_FILE} must be a mapping.")])
    issues: list[dict[str, str]] = []
    _keys(raw, TOP_KEYS, "", issues)
    if raw.get("apiVersion") != API_VERSION:
        issues.append(issue("manifest_api_version", f"apiVersion must be '{API_VERSION}'.", "apiVersion"))
    plugin_id = _text(raw, "id", issues, required=True, limit=80)
    if plugin_id and not ID_PATTERN.match(plugin_id):
        issues.append(issue("manifest_id_invalid", "id is '<publisher>.<name>' in a-z, 0-9 and '-', e.g. "
                            "'acme.release-notes'.", "id"))
    version = _text(raw, "version", issues, required=True, limit=40)
    if version and not VERSION_PATTERN.match(version):
        issues.append(issue("manifest_version_invalid", "version is semantic: MAJOR.MINOR.PATCH.", "version"))
    contributes = raw.get("contributes") if isinstance(raw.get("contributes"), dict) else {}
    if raw.get("contributes") is not None and not isinstance(raw.get("contributes"), dict):
        issues.append(issue("manifest_field_invalid", "'contributes' is a mapping.", "contributes"))
    _keys(contributes, CONTRIBUTION_KEYS, "contributes", issues)
    permissions = raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {}
    _keys(permissions, PERMISSION_KEYS, "permissions", issues)

    def paths(key: str) -> list[str]:
        found = [package_path(value, f"contributes.{key}[{index}]", issues)
                 for index, value in enumerate(_list(contributes.get(key), f"contributes.{key}", issues))]
        return [value for value in dict.fromkeys(found) if value]

    manifest = Manifest(
        id=plugin_id, name=_text(raw, "name", issues, required=True, limit=120), version=version,
        publisher=_text(raw, "publisher", issues, required=True, limit=120),
        description=_text(raw, "description", issues, limit=1000), license=_text(raw, "license", issues, limit=60),
        homepage=_text(raw, "homepage", issues, limit=300), compatible=_text(raw, "compatible", issues, limit=40),
        skills=paths("skills"), workflows=paths("workflows"), roles=paths("roles"),
        mcp_servers=_mcp_servers(contributes.get("mcp_servers"), issues),
        server=_server(contributes.get("server"), issues), ui=_ui(contributes.get("ui"), issues),
        connections=_names(permissions.get("connections"), "permissions.connections", CONNECTION_KINDS, issues),
        egress=_names(permissions.get("egress"), "permissions.egress", None, issues),
        writes=_names(permissions.get("writes"), "permissions.writes", CONNECTION_KINDS, issues),
        settings=package_path(raw.get("settings"), "settings", issues) if raw.get("settings") else None,
    )
    _cross_check(manifest, issues)
    if issues:
        raise ManifestError(issues)
    return manifest


def _cross_check(manifest: Manifest, issues: list[dict[str, str]]) -> None:
    for server in manifest.mcp_servers:
        if server.host and not _egress_allows(manifest.egress, server.host):
            issues.append(issue("manifest_egress_missing",
                                f"MCP server '{server.name}' is on {server.host}; list it in permissions.egress.",
                                "permissions.egress"))
    servers = {server.name: server for server in manifest.mcp_servers}
    for method in (manifest.ui or {}).get("methods") or []:
        if method != SETTINGS_METHOD and MCP_METHOD.fullmatch(method):
            server_name, tool = method.split(".", 1)
            server = servers.get(server_name)
            if server is None or (server.tools and tool not in server.tools):
                issues.append(issue("manifest_ui_method_unknown",
                                    f"'{method}' is not a tool of an MCP server this plugin declares.",
                                    "contributes.ui.methods"))
    for kind in manifest.writes:
        if kind not in manifest.connections:
            issues.append(issue("manifest_write_without_connection",
                                f"writes '{kind}' needs '{kind}' in permissions.connections.", "permissions.writes"))
    if not any((manifest.skills, manifest.workflows, manifest.roles, manifest.mcp_servers, manifest.server,
                manifest.ui)):
        issues.append(issue("manifest_empty", "The plugin contributes nothing.", "contributes"))


def _egress_allows(egress: list[str], host: str) -> bool:
    return any(host == entry or (entry.startswith("*.") and host.endswith(entry[1:])) for entry in egress)


__all__ = ["parse_manifest"]
