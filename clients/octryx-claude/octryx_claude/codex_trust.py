"""What a session's Codex may load: only the launcher's own hooks, MCP servers and settings, never the repository's."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HookDeclaration:
    event: str
    command: str
    timeout: int

    @property
    def label(self) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", self.event).lower()

    @property
    def listed_event(self) -> str:
        return self.event[0].lower() + self.event[1:]


def declaration_hash(hook: HookDeclaration) -> str:
    # Codex 0.169 hooks/engine/discovery.rs hook_hash: sha256 of the sorted, compact JSON of the normalized identity.
    identity = {"event_name": hook.label,
                "hooks": [{"type": "command", "command": hook.command, "timeout": hook.timeout, "async": False}]}
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def hook_key(config: Path, hook: HookDeclaration) -> str:
    return f"{os.path.realpath(config)}:{hook.label}:0:0"


def pin_hooks(config: Path, hooks: list[HookDeclaration]) -> None:
    entries = "".join(f"\n[hooks.state.{json.dumps(hook_key(config, hook))}]\n"
                      f"trusted_hash = {json.dumps(declaration_hash(hook))}\n" for hook in hooks)
    with config.open("a", encoding="utf-8") as handle:
        handle.write(entries)


def repository_folders(folder: str) -> list[str]:
    real = os.path.realpath(folder)
    try:
        top = subprocess.run(["git", "-C", real, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=20, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        top = ""
    folders = [real]
    if top and os.path.realpath(top) != real:
        folders.append(os.path.realpath(top))
    return folders


def untrust_folders(config: Path, folders: list[str]) -> None:
    # Without an explicit refusal Codex may apply a repository's .codex/config.toml (MCP servers, approval, sandbox).
    entries = "".join(f'\n[projects.{json.dumps(folder)}]\ntrust_level = "untrusted"\n' for folder in folders)
    with config.open("a", encoding="utf-8") as handle:
        handle.write(entries)


def hooks_refusal(listed: dict[str, Any], config: Path, hooks: list[HookDeclaration]) -> tuple[str, str]:
    entries = [entry for entry in listed.get("data") or [] if isinstance(entry, dict)]
    if any(entry.get("errors") for entry in entries):
        return "codex_hooks_untrusted", "load_error"
    found = [hook for entry in entries for hook in entry.get("hooks") or [] if isinstance(hook, dict)]
    expected = {hook_key(config, hook): hook for hook in hooks}
    for seen in found:
        if seen.get("key") not in expected:
            return "codex_hooks_untrusted", "foreign_hook"
    for key, hook in expected.items():
        matches = [seen for seen in found if seen.get("key") == key]
        if len(matches) != 1:
            return "codex_hooks_missing", f"missing:{hook.label}"
        seen = matches[0]
        if (seen.get("eventName") != hook.listed_event or seen.get("command") != hook.command
                or seen.get("timeoutSec") != hook.timeout or seen.get("matcher") is not None
                or seen.get("handlerType") != "command" or seen.get("source") != "user"
                or seen.get("isManaged") or os.path.realpath(str(seen.get("sourcePath") or "")) != str(
                    os.path.realpath(config))):
            return "codex_hooks_untrusted", f"changed:{hook.label}"
        if seen.get("enabled") is not True:
            return "codex_hooks_untrusted", f"disabled:{hook.label}"
        if seen.get("trustStatus") != "trusted" or seen.get("currentHash") != declaration_hash(hook):
            return "codex_hooks_untrusted", f"untrusted:{hook.label}"
    return "", ""


def launcher_servers(config: Path) -> dict[str, dict[str, Any]]:
    servers = tomllib.loads(config.read_text(encoding="utf-8")).get("mcp_servers") or {}
    return {name: spec for name, spec in servers.items() if isinstance(spec, dict)}


# Fields Codex 0.169 adds to every server in config/read, at these values when nobody set them.
_FILLED_IN = {"enabled": True, "environment_id": "local", "tool_timeout_sec": None, "startup_timeout_sec": None}


def _same_server(effective: Any, declared: dict[str, Any]) -> bool:
    if not isinstance(effective, dict):
        return False
    return all(effective.get(key) == value for key, value in declared.items()) and all(
        key in declared or (key in _FILLED_IN and value == _FILLED_IN[key]) or value is None
        for key, value in effective.items())


def layers_refusal(read: dict[str, Any], *, mcp_servers: dict[str, dict[str, Any]], approval: str,
                   sandbox: str) -> str:
    for layer in read.get("layers") or []:
        name = layer.get("name") if isinstance(layer, dict) else None
        if isinstance(name, dict) and name.get("type") == "project" and layer.get("disabledReason") is None:
            return "project_layer_active"
    config = read.get("config") if isinstance(read.get("config"), dict) else {}
    servers = config.get("mcp_servers") if isinstance(config.get("mcp_servers"), dict) else {}
    enabled = {name for name, server in servers.items() if not (isinstance(server, dict)
                                                                 and server.get("enabled") is False)}
    if enabled != set(mcp_servers):
        return "mcp_servers_changed"
    if not all(_same_server(servers.get(name), spec) for name, spec in mcp_servers.items()):
        return "mcp_server_changed"
    if config.get("approval_policy") != approval or config.get("sandbox_mode") != sandbox:
        return "settings_changed"
    return ""


def unexpected_servers(listed: dict[str, Any], expected: set[str]) -> str:
    rows = [row for row in listed.get("data") or [] if isinstance(row, dict)]
    extra = {str(row.get("name")) for row in rows if row.get("runtimeStatus") != "disabled"} - expected
    return "mcp_servers_changed" if extra else ""


def guard_runs(command: list[str]) -> bool:
    interpreter, flag, guard, _deadline, wrapper, *_ = command
    try:
        done = subprocess.run([interpreter, flag, guard, "--probe", wrapper], capture_output=True, timeout=20,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def sandbox_roots(sandbox: dict[str, Any], cwd: str) -> list[str]:
    roots = [cwd, *[str(root) for root in sandbox.get("writableRoots") or [] if isinstance(root, str)]]
    if not sandbox.get("excludeTmpdirEnvVar"):
        roots.append(tempfile.gettempdir())
    if not sandbox.get("excludeSlashTmp"):
        roots.append("/tmp")
    return roots


def writable_in_sandbox(paths: list[Path], roots: list[str]) -> bool:
    # A file is replaceable when it or any folder above it lies in a writable root, by its own path or by the path
    # its links lead to.
    real_roots = {os.path.realpath(root) for root in roots} | {os.path.abspath(root) for root in roots}
    for path in paths:
        for candidate in (os.path.abspath(path), os.path.realpath(path)):
            if any(candidate == root or candidate.startswith(root.rstrip("/") + "/") for root in real_roots):
                return True
    return False


def content_hashes(files: list[Path]) -> dict[str, str]:
    hashes = {}
    for file in files:
        try:
            hashes[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
        except OSError:
            hashes[str(file)] = ""
    return hashes


__all__ = [
    "HookDeclaration",
    "content_hashes",
    "declaration_hash",
    "hook_key",
    "hooks_refusal",
    "guard_runs",
    "launcher_servers",
    "layers_refusal",
    "pin_hooks",
    "repository_folders",
    "sandbox_roots",
    "unexpected_servers",
    "untrust_folders",
    "writable_in_sandbox",
]
