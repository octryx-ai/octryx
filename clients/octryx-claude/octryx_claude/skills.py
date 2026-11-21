"""Catalog skills for a governed session (WP 2.1): a per-session, read-only plugin passed with --plugin-dir.

At every start the launcher

1. reads ``GET /skills/manifest`` (the effective skills of this Workspace for this user);
2. fetches every blob it does not have yet (``GET /skills/blobs/{sha256}``), re-hashes it and checks each skill's
   bundle digest; any mismatch refuses the session (``skill_bundle_digest_mismatch``) — fail closed, like the hooks;
3. checks that every delivered ``SKILL.md`` carries only allowlisted frontmatter keys (the platform already
   rebuilt it; a key outside the allowlist refuses the session: ``skill_frontmatter_not_allowed``);
4. writes ``<home parent>/octryx-skill-plugins/<session>/octryx/`` (files 0444, folders 0555): the plugin
   manifest and ``skills/<name>/…``. It never writes to ``~/.claude*`` or into the repository, and it lives outside
   the launcher state root, so the credential deny rules stay whole.

If the platform cannot be reached, or answers without a manifest, the session starts without catalog skills and
the start line says so (``skills_unavailable``, decision D4): skills never carry permissions. MCP server entries of
the manifest are returned for the session's MCP config (``--strict-mcp-config`` ignores plugin MCP files).
The plugin folder is removed at ``SessionEnd`` and folders of earlier sessions are swept at the next start.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .platform import PlatformResult, SessionContext, call_control_plane
from .state import LocalState

PLUGIN_NAME = "octryx"
PLUGINS_DIR = "octryx-skill-plugins"
CACHE_DIR = "skill-cache"
MANIFEST_TIMEOUT = 15.0
BLOB_TIMEOUT = 15.0
SWEEP_AFTER_SECONDS = 12 * 3600
MAX_SKILLS = 200
MAX_FILES = 200
#: Mirrors the platform's ``spec.DELIVERY_FRONTMATTER_KEYS``.
FRONTMATTER_ALLOWLIST = frozenset({
    "name", "description", "when_to_use", "argument-hint", "arguments", "disable-model-invocation",
    "user-invocable", "paths", "license", "compatibility", "metadata",
})
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_TOP_KEY = re.compile(r"^([A-Za-z0-9_-]+)\s*:")
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


class SkillDeliveryRefusedError(Exception):
    """The session is not started: a delivered skill failed verification. ``code`` is fixed."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SkillDelivery:
    state: str  # delivered | unavailable
    plugin_dir: Path | None = None
    skills: tuple[str, ...] = ()
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    reason: str = ""

    def summary(self) -> str:
        if self.state != "delivered":
            return f"skills_unavailable ({self.reason})" if self.reason else "skills_unavailable"
        return f"{len(self.skills)} catalog skill(s)" + (f", {len(self.mcp_servers)} MCP server(s)"
                                                        if self.mcp_servers else "")


def plugin_root(state: LocalState) -> Path:
    """Next to the state root, never inside it (the state root stays fully denied to the agent)."""
    return state.root.parent / PLUGINS_DIR


def session_plugin_dir(state: LocalState, session_key: str) -> Path:
    return plugin_root(state) / session_key / PLUGIN_NAME


def _safe_relative(path: str) -> bool:
    parts = path.split("/")
    return bool(path) and not path.startswith("/") and all(part not in {"", ".", ".."} and _SEGMENT.match(part)
                                                           for part in parts)


def bundle_digest(files: list[dict[str, Any]]) -> str:
    """Same digest as the platform: sha256 over ``path NUL sha256 LF`` in path order."""
    hasher = hashlib.sha256()
    for entry in sorted(files, key=lambda item: item["path"]):
        hasher.update(f"{entry['path']}\0{entry['sha256']}\n".encode())
    return f"sha256:{hasher.hexdigest()}"


def frontmatter_keys(text: str) -> set[str]:
    match = _FRONTMATTER.match(text)
    if match is None:
        return set()
    return {found.group(1) for line in match.group(1).splitlines() if (found := _TOP_KEY.match(line))}


def _validated(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    skills = manifest.get("skills")
    if manifest.get("plugin") != PLUGIN_NAME or not isinstance(skills, list) or len(skills) > MAX_SKILLS:
        raise ValueError("manifest_invalid")
    for skill in skills:
        files = skill.get("files") if isinstance(skill, dict) else None
        if not isinstance(files, list) or not _NAME.match(str(skill.get("name") or "")) or len(files) > MAX_FILES:
            raise ValueError("manifest_invalid")
        for entry in files:
            if not (isinstance(entry, dict) and _safe_relative(str(entry.get("path") or ""))
                    and _SHA.match(str(entry.get("sha256") or ""))):
                raise ValueError("manifest_invalid")
    return skills


def _blob(state: LocalState, context: SessionContext, http: httpx.Client, sha: str) -> str:
    cached = state.root / CACHE_DIR / sha
    if cached.is_file():
        data = cached.read_bytes()
        if hashlib.sha256(data).hexdigest() == sha:
            return data.decode("utf-8")
        cached.unlink()
    result = call_control_plane(state, context, "GET", f"/skills/blobs/{sha}", http=http, timeout=BLOB_TIMEOUT)
    if result.outcome != "ok":
        raise ConnectionError(result.reason or result.outcome)
    content = result.body.get("content")
    if not isinstance(content, str) or hashlib.sha256(content.encode("utf-8")).hexdigest() != sha:
        raise SkillDeliveryRefusedError("skill_bundle_digest_mismatch", sha[:12])
    cached.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = cached.with_suffix(".tmp")
    temporary.write_bytes(content.encode("utf-8"))
    os.chmod(temporary, 0o400)
    os.replace(temporary, cached)
    return content


def _make_writable(root: Path) -> None:
    for current, folders, files in os.walk(root):
        os.chmod(current, stat.S_IRWXU)
        for name in files:
            os.chmod(os.path.join(current, name), stat.S_IRUSR | stat.S_IWUSR)
        del folders


def remove_tree(path: Path) -> None:
    if not path.exists():
        return
    _make_writable(path)
    shutil.rmtree(path, ignore_errors=True)


def remove_plugin(state: LocalState, session_key: str) -> None:
    remove_tree(plugin_root(state) / session_key)


def sweep(state: LocalState, *, keep: str, now: float | None = None) -> list[str]:
    """Remove plugin folders of earlier sessions older than :data:`SWEEP_AFTER_SECONDS`."""
    root = plugin_root(state)
    removed: list[str] = []
    if not root.is_dir():
        return removed
    moment = time.time() if now is None else now
    for entry in root.iterdir():
        if entry.name != keep and entry.is_dir() and moment - entry.stat().st_mtime > SWEEP_AFTER_SECONDS:
            remove_tree(entry)
            removed.append(entry.name)
    return removed


def _write_plugin(target: Path, manifest: dict[str, Any], contents: dict[str, dict[str, str]]) -> None:
    remove_tree(target.parent)
    (target / ".claude-plugin").mkdir(mode=0o700, parents=True)
    digest = str(manifest.get("manifest_digest") or "")
    plugin = {"name": PLUGIN_NAME, "description": "Octryx skill catalog (this session)",
              "version": f"{manifest.get('workspace_id') or 'workspace'}.{digest.removeprefix('sha256:')[:12]}"}
    (target / ".claude-plugin" / "plugin.json").write_text(json.dumps(plugin, indent=2) + "\n")
    for name, files in contents.items():
        for path, text in files.items():
            destination = target / "skills" / name / path
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
    for current, folders, files in os.walk(target, topdown=False):
        for item in files:
            os.chmod(os.path.join(current, item), 0o444)
        os.chmod(current, 0o555)
        del folders
    os.chmod(target.parent, 0o700)


def _servers(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    servers: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("mcp_servers") or []:
        spec = entry.get("server") if isinstance(entry, dict) else None
        name = str(entry.get("name") or "") if isinstance(entry, dict) else ""
        if not _NAME.match(name) or not isinstance(spec, dict) or not isinstance(spec.get("command"), str):
            continue
        args = [str(item) for item in spec.get("args") or []]
        env = {str(key): str(value) for key, value in (spec.get("env") or {}).items()}
        servers[name] = {"type": "stdio", "command": spec["command"], "args": args, "env": env}
    return servers


def prepare(state: LocalState, context: SessionContext, *, http: httpx.Client) -> SkillDelivery:
    """Fetch, verify and materialize this session's catalog skills; raises :class:`SkillDeliveryRefusedError`."""
    sweep(state, keep=context.session_key)
    result: PlatformResult = call_control_plane(state, context, "GET", "/skills/manifest", http=http,
                                                timeout=MANIFEST_TIMEOUT)
    if result.outcome != "ok":
        return SkillDelivery("unavailable", reason=result.reason or result.outcome)
    try:
        skills = _validated(result.body)
    except ValueError as exc:
        return SkillDelivery("unavailable", reason=str(exc))
    contents: dict[str, dict[str, str]] = {}
    try:
        for skill in skills:
            if bundle_digest(skill["files"]) != skill.get("bundle_digest"):
                raise SkillDeliveryRefusedError("skill_bundle_digest_mismatch", skill["name"])
            files = {entry["path"]: _blob(state, context, http, entry["sha256"]) for entry in skill["files"]}
            outside = frontmatter_keys(files.get("SKILL.md", "")) - FRONTMATTER_ALLOWLIST
            if "SKILL.md" not in files or outside:
                raise SkillDeliveryRefusedError("skill_frontmatter_not_allowed", skill["name"])
            contents[skill["name"]] = files
    except ConnectionError as exc:
        return SkillDelivery("unavailable", reason=str(exc) or "platform_unreachable")
    target = session_plugin_dir(state, context.session_key)
    _write_plugin(target, result.body, contents)
    return SkillDelivery("delivered", plugin_dir=target, skills=tuple(sorted(contents)),
                         mcp_servers=_servers(result.body))


__all__ = [
    "FRONTMATTER_ALLOWLIST",
    "PLUGIN_NAME",
    "SkillDelivery",
    "SkillDeliveryRefusedError",
    "bundle_digest",
    "frontmatter_keys",
    "plugin_root",
    "prepare",
    "remove_plugin",
    "session_plugin_dir",
    "sweep",
]
