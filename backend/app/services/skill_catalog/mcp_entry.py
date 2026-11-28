"""MCP server entries: plugins that bring an MCP server instead of a SKILL.md."""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import SkillCatalogError

PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
MCP_FILE = ".mcp.json"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}")
#: ``docker run`` options that take a value (the next argument is that value, not the image).
_DOCKER_VALUE_FLAGS = frozenset({
    "-e", "--env", "--env-file", "-v", "--volume", "--name", "--network", "--net", "-p", "--publish", "-w",
    "--workdir", "-u", "--user", "--entrypoint", "--mount", "--platform", "-l", "--label", "--pull", "--memory",
    "-m", "--cpus", "--add-host", "--hostname", "-h", "--cap-add", "--cap-drop", "--security-opt", "--ulimit",
    "--tmpfs", "--device", "--dns", "--restart", "--runtime", "--log-driver", "--log-opt", "--stop-signal",
})


def _servers(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        return {}
    servers = document.get("mcpServers") if isinstance(document.get("mcpServers"), dict) else document
    return {str(key): value for key, value in servers.items() if isinstance(value, dict)}


def servers_in_plugin(files: dict[str, str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in (MCP_FILE, PLUGIN_MANIFEST):
        if path not in files:
            continue
        try:
            document = json.loads(files[path])
        except ValueError:
            raise SkillCatalogError("skill_mcp_json_invalid", 422, path=path) from None
        if path == PLUGIN_MANIFEST:
            inline = document.get("mcpServers") if isinstance(document, dict) else None
            document = {"mcpServers": inline} if isinstance(inline, dict) else {}
        found.update(_servers(document))
    return found


def _image(args: list[str]) -> str | None:
    if not args or args[0] != "run":
        return None
    index = 1
    while index < len(args):
        token = args[index]
        if token in _DOCKER_VALUE_FLAGS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return None


def launch_spec(server: str, raw: dict[str, Any]) -> dict[str, Any]:
    transport = str(raw.get("type") or ("stdio" if raw.get("command") else "http"))
    if transport != "stdio" or not isinstance(raw.get("command"), str) or not raw["command"].strip():
        raise SkillCatalogError("skill_mcp_remote_not_supported", 422, server=server,
                                message="Only local (stdio) MCP servers are catalog entries; a remote one is a "
                                        "connector.")
    args = [str(item) for item in raw.get("args") or []] if isinstance(raw.get("args"), list) else []
    env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    command = raw["command"].strip()
    referenced = {match.group(1) for value in [*args, *(str(item) for item in env.values())]
                  for match in _VARIABLE.finditer(value)}
    return {
        "server": server,
        "command": command,
        "args": args,
        "env_names": sorted(str(key) for key in env),
        "env_values": {str(key): str(item) for key, item in sorted(env.items()) if not _VARIABLE.search(str(item))},
        "image": _image(args) if command == "docker" else None,
        "image_digest": None,
        "passthrough": sorted(referenced),
        "env_connections": {},
    }


def normalize_launch_spec(value: Any, *, upstream: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or not str(value.get("server") or ""):
        raise SkillCatalogError("skill_mcp_launch_spec_invalid", 422)
    base = dict(upstream or value)
    digest = value.get("image_digest")
    if digest is not None and digest != "" and not DIGEST_PATTERN.match(str(digest)):
        raise SkillCatalogError("skill_mcp_image_digest_invalid", 422,
                                message="Record the image digest as sha256:<64 hex>.")
    connections = value.get("env_connections") if isinstance(value.get("env_connections"), dict) else {}
    passthrough = set(base.get("passthrough") or [])
    unknown = sorted(set(connections) - passthrough - set(base.get("env_names") or []))
    if unknown:
        raise SkillCatalogError("skill_mcp_env_unknown", 422, variables=unknown)
    return {
        "server": str(base.get("server")),
        "command": str(base.get("command") or ""),
        "args": [str(item) for item in base.get("args") or []],
        "env_names": sorted(str(item) for item in base.get("env_names") or []),
        "env_values": {str(key): str(item) for key, item in sorted((base.get("env_values") or {}).items())},
        "image": base.get("image"),
        "image_digest": str(digest) if digest else None,
        "passthrough": sorted(passthrough),
        "env_connections": {str(key): str(item) for key, item in sorted(connections.items()) if str(item)},
    }


def delivered_server(spec: dict[str, Any], resolved_env: dict[str, str]) -> dict[str, Any]:
    args = list(spec.get("args") or [])
    image, digest = spec.get("image"), spec.get("image_digest")
    if image and digest:
        repository = image.split("@", 1)[0]
        last = repository.rsplit("/", 1)[-1]
        if ":" in last:
            repository = repository[: repository.rfind(":")]
        args = [f"{repository}@{digest}" if item == image else item for item in args]
    rewritten: list[str] = []
    for item in args:
        # "-e NAME=${NAME}" becomes "-e NAME": docker then reads NAME from the server's own environment, which
        # holds only the named-connection value (or nothing) — never the user's shell value.
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=\$\{\1\}", item)
        rewritten.append(match.group(1) if match else item)
    env = {**(spec.get("env_values") or {}), **resolved_env}
    return {"command": spec.get("command"), "args": rewritten, "env": dict(sorted(env.items()))}


__all__ = [
    "DIGEST_PATTERN",
    "MCP_FILE",
    "PLUGIN_MANIFEST",
    "delivered_server",
    "launch_spec",
    "normalize_launch_spec",
    "servers_in_plugin",
]
