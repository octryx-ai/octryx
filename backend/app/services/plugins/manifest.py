"""``octryx-plugin.yaml``: what a plugin package brings, checked without a database (also by the validate CLI)."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

MANIFEST_FILE = "octryx-plugin.yaml"
API_VERSION = "octryx.ai/plugin/v1"
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
HOST_PATTERN = re.compile(r"^(?:\*\.)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")
CONNECTION_KINDS = ("jira", "confluence", "github", "gitlab", "bitbucket", "slack", "teams", "servicenow", "jenkins",
                    "knowledge")
UI_SLOTS = {"pages": ("work", "knowledge", "operations", "admin"), "tiles": ("workspace", "operations"),
            "tabs": ("work_item", "run", "repository"), "phone": ()}
MCP_TRANSPORTS = ("streamable-http", "sse")
TOP_KEYS = {"apiVersion", "id", "name", "version", "publisher", "description", "license", "homepage", "compatible",
            "contributes", "permissions", "settings"}
CONTRIBUTION_KEYS = {"skills", "workflows", "roles", "mcp_servers", "server", "ui"}
PERMISSION_KEYS = {"connections", "egress", "writes"}
MAX_ITEMS = 20
SETTINGS_METHOD = "settings.get"
MCP_METHOD = re.compile(r"[a-z0-9][a-z0-9-]{1,62}\.[A-Za-z0-9_-]{1,80}")
TOOL_METHOD = re.compile(r"[a-z][a-z0-9_]{1,80}")


@dataclass(slots=True)
class McpServer:
    name: str
    url: str
    transport: str
    description: str
    tools: list[str]

    @property
    def host(self) -> str:
        return (urlparse(self.url).hostname or "").lower()


@dataclass(slots=True)
class Manifest:
    id: str
    name: str
    version: str
    publisher: str
    description: str
    license: str
    homepage: str
    compatible: str
    skills: list[str] = field(default_factory=list)
    workflows: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    mcp_servers: list[McpServer] = field(default_factory=list)
    server: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None
    connections: list[str] = field(default_factory=list)
    egress: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    settings: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "version": self.version, "publisher": self.publisher,
            "description": self.description, "license": self.license, "homepage": self.homepage,
            "compatible": self.compatible,
            "contributes": {"skills": self.skills, "workflows": self.workflows, "roles": self.roles,
                            "mcp_servers": [{"name": s.name, "url": s.url, "transport": s.transport,
                                             "description": s.description, "tools": s.tools}
                                            for s in self.mcp_servers],
                            "server": self.server, "ui": self.ui},
            "permissions": {"connections": self.connections, "egress": self.egress, "writes": self.writes},
            "settings": self.settings,
        }


class ManifestError(Exception):
    def __init__(self, issues: list[dict[str, str]]) -> None:
        super().__init__("; ".join(issue["message"] for issue in issues))
        self.issues = issues


def issue(code: str, message: str, path: str = "") -> dict[str, str]:
    return {"code": code, "message": message, "path": path}


def _text(raw: dict[str, Any], key: str, issues: list[dict[str, str]], *, required: bool = False, limit: int = 200
          ) -> str:
    value = raw.get(key)
    if value is None or value == "":
        if required:
            issues.append(issue("manifest_field_missing", f"'{key}' is required.", key))
        return ""
    if not isinstance(value, str | int | float):
        issues.append(issue("manifest_field_invalid", f"'{key}' must be text.", key))
        return ""
    text = str(value).strip()
    if len(text) > limit:
        issues.append(issue("manifest_field_too_long", f"'{key}' is at most {limit} characters.", key))
    return text[:limit]


def _list(raw: Any, path: str, issues: list[dict[str, str]]) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        issues.append(issue("manifest_field_invalid", f"'{path}' must be a list.", path))
        return []
    if len(raw) > MAX_ITEMS:
        issues.append(issue("manifest_too_many", f"'{path}' has at most {MAX_ITEMS} entries.", path))
    return raw[:MAX_ITEMS]


def package_path(value: Any, path: str, issues: list[dict[str, str]]) -> str | None:
    text = str(value or "").strip().strip("/") if isinstance(value, str) else ""
    normal = posixpath.normpath(text) if text else ""
    if not text or normal.startswith("..") or text.startswith("/") or "\\" in text or normal == ".":
        issues.append(issue("manifest_path_invalid", f"'{path}' must be a relative path inside the package.", path))
        return None
    return normal


def _keys(raw: dict[str, Any], allowed: set[str], path: str, issues: list[dict[str, str]]) -> None:
    for key in sorted(set(raw) - allowed):
        issues.append(issue("manifest_unknown_key", f"Unknown key '{key}'.", f"{path}.{key}" if path else key))


__all__ = ["API_VERSION", "MANIFEST_FILE", "MCP_METHOD", "SETTINGS_METHOD", "TOOL_METHOD", "Manifest",
           "ManifestError", "McpServer", "issue", "package_path"]
