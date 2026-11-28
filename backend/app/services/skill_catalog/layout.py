"""What a repository (or a plugin folder in it) contains, from its tree listing."""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass, field
from typing import Any

from .errors import SkillCatalogError
from .mcp_entry import MCP_FILE, PLUGIN_MANIFEST
from .spec import SKILL_FILE

MARKETPLACE_FILE = ".claude-plugin/marketplace.json"
IGNORED_COMPONENTS: dict[str, str] = {
    "agents": "Agents are not imported.",
    "commands": "Slash commands are not imported.",
    "hooks": "Hooks would run code outside the tool check; never imported.",
    "bin": "Executables are not imported.",
    ".lsp.json": "LSP servers are not imported.",
    "output-styles": "Output styles are not imported.",
    ".codex-plugin": "Another harness's manifest; ignored.",
    ".cursor-plugin": "Another harness's manifest; ignored.",
}


@dataclass(frozen=True, slots=True)
class FoundSkill:
    path: str
    name: str
    files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FoundPlugin:
    path: str
    files: tuple[str, ...]


@dataclass(slots=True)
class Layout:
    skills: list[FoundSkill] = field(default_factory=list)
    plugins: list[FoundPlugin] = field(default_factory=list)
    ignored: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PluginSource:
    name: str
    path: str
    url: str | None = None
    ref: str | None = None
    entry: dict[str, Any] = field(default_factory=dict)


def _under(path: str, base: str) -> bool:
    return not base or path == base or path.startswith(f"{base}/")


def _relative(path: str, root: str) -> str:
    return path[len(root) + 1:] if root else path


def find_layout(paths: list[str], base: str) -> Layout:
    scoped = [path for path in paths if _under(path, base)]
    layout = Layout()
    skill_roots = sorted({posixpath.dirname(path) for path in scoped if posixpath.basename(path) == SKILL_FILE},
                         key=lambda item: (item.count("/"), item))
    accepted: list[str] = []
    for root in skill_roots:
        outer = next((item for item in accepted if _under(root, item) and root != item), None)
        if outer is not None:
            layout.ignored.append({"path": f"{root}/{SKILL_FILE}", "reason": f"Inside the skill folder {outer}."})
            continue
        accepted.append(root)
        files = tuple(sorted(_relative(path, root) for path in scoped if _under(path, root) and path != root))
        layout.skills.append(FoundSkill(path=root, name=posixpath.basename(root) or root, files=files))
    plugin_roots = set()
    for path in scoped:
        if path.endswith(f"/{PLUGIN_MANIFEST}") or path == PLUGIN_MANIFEST:
            plugin_roots.add(path[: -len(PLUGIN_MANIFEST)].rstrip("/"))
        if posixpath.basename(path) == MCP_FILE:
            plugin_roots.add(posixpath.dirname(path))
    for root in sorted(plugin_roots):
        files = tuple(name for name in (PLUGIN_MANIFEST, MCP_FILE)
                      if (f"{root}/{name}" if root else name) in scoped)
        layout.plugins.append(FoundPlugin(path=root, files=files))
        for component, reason in IGNORED_COMPONENTS.items():
            prefix = f"{root}/{component}" if root else component
            if any(path == prefix or path.startswith(f"{prefix}/") for path in scoped):
                layout.ignored.append({"path": prefix, "reason": reason})
    return layout


def _clean(path: str) -> str:
    text = str(path or "").strip()
    while text.startswith("./"):
        text = text[2:]
    normalized = posixpath.normpath(text or ".")
    if normalized.startswith("..") or normalized.startswith("/"):
        raise SkillCatalogError("plugin_source_invalid", 422)
    return "" if normalized == "." else normalized


def resolve_marketplace_entry(marketplace_text: str, plugin_name: str, paths: set[str]) -> PluginSource:
    try:
        document = json.loads(marketplace_text)
    except ValueError:
        raise SkillCatalogError("marketplace_invalid", 422, message="marketplace.json is not valid JSON.") from None
    plugins = document.get("plugins") if isinstance(document, dict) else None
    entry = next((item for item in plugins or [] if isinstance(item, dict) and item.get("name") == plugin_name), None)
    if entry is None:
        raise SkillCatalogError("marketplace_plugin_not_found", 422, plugin=plugin_name)
    source = entry.get("source")
    if isinstance(source, str):
        metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
        root = metadata.get("pluginRoot")
        relative = _clean(source)
        path = _clean(posixpath.join(_clean(root), relative)) if root and not source.startswith("./") else relative
        if not any(item == path or item.startswith(f"{path}/") for item in paths):
            raise SkillCatalogError("plugin_source_missing", 422, path=path,
                                    message="The marketplace entry points to a folder that does not exist at this "
                                            "commit.")
        return PluginSource(name=plugin_name, path=path, entry=entry)
    if isinstance(source, dict):
        kind = source.get("source")
        pin = str(source.get("sha") or source.get("ref") or "HEAD")
        if kind == "github" and isinstance(source.get("repo"), str):
            return PluginSource(name=plugin_name, path="", url=f"https://github.com/{source['repo']}", ref=pin,
                                entry=entry)
        if kind == "url" and isinstance(source.get("url"), str):
            return PluginSource(name=plugin_name, path="", url=source["url"].removesuffix(".git"), ref=pin,
                                entry=entry)
        if kind == "git-subdir" and isinstance(source.get("url"), str):
            return PluginSource(name=plugin_name, path=_clean(source.get("path") or ""),
                                url=source["url"].removesuffix(".git"), ref=pin, entry=entry)
    raise SkillCatalogError("plugin_source_unsupported", 422, plugin=plugin_name)


__all__ = [
    "IGNORED_COMPONENTS",
    "MARKETPLACE_FILE",
    "FoundPlugin",
    "FoundSkill",
    "Layout",
    "PluginSource",
    "find_layout",
    "resolve_marketplace_entry",
]
