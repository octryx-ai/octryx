"""The content files of a plugin package read and checked: skills, workflows and roles (no database).

Every issue is appended to the caller's list with a fixed code and the file it is in; ``package.read_package`` reads
the manifest first and raises once with all of them.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from typing import Any

import yaml

from ..skill_catalog.spec import SKILL_FILE, SkillSpecError, parse_skill_md, validate_skill
from .manifest import Manifest, issue

ROLE_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
WORKFLOW_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")
SCM_KINDS = ("github", "gitlab", "bitbucket")


@dataclass(slots=True)
class SkillContent:
    name: str
    path: str
    frontmatter: dict[str, Any]
    body: str
    files: dict[str, str]  # relative to the skill folder, without SKILL.md
    text: str = ""  # SKILL.md as written


@dataclass(slots=True)
class WorkflowContent:
    key: str
    name: str
    description: str
    definition: dict[str, Any]
    path: str
    writes: list[str]


@dataclass(slots=True)
class RoleContent:
    key: str
    name: str
    description: str
    function_keys: list[str]
    functions: list[dict[str, Any]]
    path: str


def _text(files: dict[str, bytes], path: str, issues: list[dict[str, str]]) -> str | None:
    data = files.get(path)
    if data is None:
        issues.append(issue("package_path_missing", f"{path} is not in the package.", path))
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        issues.append(issue("package_not_text", f"{path} is not UTF-8 text.", path))
        return None


def _skill(files: dict[str, bytes], folder: str, issues: list[dict[str, str]]) -> SkillContent | None:
    text = _text(files, f"{folder}/{SKILL_FILE}", issues)
    if text is None:
        return None
    try:
        parsed = parse_skill_md(text)
    except SkillSpecError as error:
        issues.append(issue(error.code, error.message, f"{folder}/{SKILL_FILE}"))
        return None
    prefix = folder + "/"
    extra: dict[str, str] = {}
    for path in sorted(files):
        if path.startswith(prefix) and path != prefix + SKILL_FILE:
            content = _text(files, path, issues)
            if content is not None:
                extra[path[len(prefix):]] = content
    name = posixpath.basename(folder)
    for found in validate_skill(parsed.frontmatter, parsed.body, folder_name=name, skill_md_text=text,
                                paths=[SKILL_FILE, *extra]):
        if found.severity == "error":
            issues.append(issue(found.code, found.message, f"{folder}/{SKILL_FILE}"))
    return SkillContent(name=name, path=folder, frontmatter=parsed.frontmatter, body=parsed.body, files=extra,
                        text=text)


def _document(files: dict[str, bytes], path: str, issues: list[dict[str, str]]) -> dict[str, Any] | None:
    text = _text(files, path, issues)
    if text is None:
        return None
    try:
        loaded = json.loads(text) if path.endswith(".json") else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError):
        issues.append(issue("package_document_invalid", f"{path} is not valid YAML/JSON.", path))
        return None
    if not isinstance(loaded, dict):
        issues.append(issue("package_document_invalid", f"{path} must be a mapping.", path))
        return None
    return loaded


def workflow_writes(definition: dict[str, Any]) -> list[str]:
    """The connection kinds a workflow's platform steps write to (``scm`` = any code host)."""
    found = set()
    for node in definition.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "platform_action":
            action = str((node.get("config") or {}).get("action") or "")
            prefix = action.split(".", 1)[0]
            if prefix in ("jira", "confluence", "scm"):
                found.add(prefix)
    return sorted(found)


def _workflow(files: dict[str, bytes], path: str, manifest: Manifest, issues: list[dict[str, str]]
              ) -> WorkflowContent | None:
    raw = _document(files, path, issues)
    if raw is None:
        return None
    key, name = str(raw.get("key") or "").strip(), str(raw.get("name") or "").strip()
    definition = raw.get("definition")
    if not WORKFLOW_KEY.match(key):
        issues.append(issue("workflow_key_invalid", "A workflow key is 2-80 chars of a-z, 0-9 and '-'.", path))
    if not name:
        issues.append(issue("workflow_name_missing", "A workflow needs a name.", path))
    if not isinstance(definition, dict):
        issues.append(issue("workflow_definition_missing", "A workflow needs a definition mapping.", path))
        return None
    from ..flow_definitions import validate_flow_definition

    report = validate_flow_definition(definition)
    for error in report.get("errors") or []:
        issues.append(issue(f"workflow_{error.get('code') or 'invalid'}", str(error.get("message") or error), path))
    writes = workflow_writes(definition)
    for kind in writes:
        declared = any(item in manifest.writes for item in SCM_KINDS) if kind == "scm" else kind in manifest.writes
        if not declared:
            issues.append(issue("workflow_write_undeclared",
                                f"The workflow writes to {kind}; declare it in permissions.writes.", path))
    return WorkflowContent(key=key, name=name, description=str(raw.get("description") or "").strip(),
                           definition=definition, path=path, writes=writes)


def _role(files: dict[str, bytes], path: str, issues: list[dict[str, str]]) -> RoleContent | None:
    raw = _document(files, path, issues)
    if raw is None:
        return None
    key, name = str(raw.get("key") or "").strip(), str(raw.get("name") or "").strip()
    if not ROLE_KEY.match(key):
        issues.append(issue("role_key_invalid", "A role key is 2-40 chars: a-z first, then a-z, 0-9, '_'.", path))
    if not name:
        issues.append(issue("role_name_missing", "A role needs a name.", path))
    functions = []
    for index, entry in enumerate(raw.get("functions") or []):
        if not isinstance(entry, dict) or not ROLE_KEY.match(str(entry.get("key") or "")) or not entry.get("name"):
            issues.append(issue("role_function_invalid", "A function is {key, name, description?, tools}.",
                                f"{path}:functions[{index}]"))
            continue
        tools = [str(tool).strip() for tool in entry.get("tools") or [] if str(tool).strip()]
        if not tools:
            issues.append(issue("role_function_without_tools", "A function lists its tools.",
                                f"{path}:functions[{index}]"))
        functions.append({"key": entry["key"], "name": str(entry["name"])[:120],
                          "description": str(entry.get("description") or ""), "tools": tools})
    keys = [str(item).strip() for item in raw.get("function_keys") or [] if str(item).strip()]
    keys += [item["key"] for item in functions if item["key"] not in keys]
    return RoleContent(key=key, name=name, description=str(raw.get("description") or "").strip(),
                       function_keys=keys, functions=functions, path=path)


__all__ = ["RoleContent", "SkillContent", "WorkflowContent", "workflow_writes"]
