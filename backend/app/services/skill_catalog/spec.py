"""The Agent Skills format (agentskills.io specification, checked 2026-10-07) as the catalog's canonical artefact.

``SKILL.md`` is YAML frontmatter between ``---`` lines plus a Markdown body. Spec rules enforced here:

- ``name``: 1-64 chars of ``a-z0-9-``, no leading, trailing or double hyphen, equal to the skill folder name;
- ``description``: 1-1024 chars;
- optional ``license``, ``compatibility`` (<= 500 chars), ``metadata`` (string map), ``allowed-tools``;
- ``SKILL.md`` should stay under 500 lines (warning); reference files sit one level below the skill root.

Claude Code accepts more frontmatter keys. :data:`DELIVERY_FRONTMATTER_KEYS` is the allowlist the catalog
delivers; every other key is dropped on delivery, and :data:`EXECUTION_FRONTMATTER_KEYS` are the ones that would
widen permissions or change how the skill executes (reported by the scanner so the reviewer sees what upstream
intended). Nothing here guesses: parsing is YAML ``safe_load`` and every refusal carries a fixed code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

SKILL_FILE = "SKILL.md"
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
WHEN_TO_USE_MAX = 1024
SKILL_MD_LINE_WARNING = 500
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")

#: Keys the Agent Skills specification defines (and the only ones the Skills API / claude.ai accept).
SPEC_FRONTMATTER_KEYS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")

#: Keys delivered to Claude Code; everything else is stripped from the delivered SKILL.md.
DELIVERY_FRONTMATTER_KEYS = (
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "paths",
    "license",
    "compatibility",
    "metadata",
)

#: Keys that grant tools, run hooks or change the execution context; never delivered.
EXECUTION_FRONTMATTER_KEYS = (
    "allowed-tools",
    "disallowed-tools",
    "hooks",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "shell",
)

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


class SkillSpecError(Exception):
    """``SKILL.md`` cannot be read as an Agent Skill (no frontmatter, invalid YAML, not a mapping)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ParsedSkill:
    frontmatter: dict[str, Any]
    body: str
    frontmatter_text: str


@dataclass(frozen=True, slots=True)
class SpecIssue:
    code: str
    severity: str  # "error" | "warning"
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "field": self.field, "message": self.message}


def parse_skill_md(text: str) -> ParsedSkill:
    match = _FRONTMATTER_RE.match(text or "")
    if match is None:
        raise SkillSpecError("skill_frontmatter_missing",
                             "SKILL.md must start with YAML frontmatter between --- lines.")
    raw = match.group(1)
    try:
        loaded = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f" (line {mark.line + 2})" if mark is not None else ""
        raise SkillSpecError("skill_frontmatter_invalid", f"The frontmatter is not valid YAML{where}.") from None
    if not isinstance(loaded, dict):
        raise SkillSpecError("skill_frontmatter_invalid", "The frontmatter must be a YAML mapping.")
    body = (text or "")[match.end():]
    return ParsedSkill(frontmatter={str(key): value for key, value in loaded.items()}, body=body,
                       frontmatter_text=raw)


def render_frontmatter(frontmatter: dict[str, Any]) -> str:
    return yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False,
                          width=4096).rstrip("\n")


def render_skill_md(frontmatter: dict[str, Any], body: str) -> str:
    """Inverse of :func:`parse_skill_md`: ``parse_skill_md(render_skill_md(f, b)).body == b``."""
    return f"---\n{render_frontmatter(frontmatter)}\n---\n{body}"


def replace_frontmatter(text: str, frontmatter: dict[str, Any]) -> str:
    """``text`` with only its frontmatter replaced; the body stays byte-for-byte (upstream diffs stay small)."""
    parsed = parse_skill_md(text)
    if parsed.frontmatter == frontmatter:
        return text
    return render_skill_md(frontmatter, parsed.body)


def name_issue(name: Any) -> SpecIssue | None:
    value = str(name or "")
    if not value:
        return SpecIssue("skill_name_missing", "error", "name", "Give the skill a name.")
    if len(value) > NAME_MAX:
        return SpecIssue("skill_name_too_long", "error", "name", f"The name has at most {NAME_MAX} characters.")
    if not NAME_PATTERN.match(value):
        return SpecIssue("skill_name_invalid", "error", "name",
                         "Use lower-case letters, digits and single hyphens; no hyphen at the start or end.")
    return None


def validate_skill(
    frontmatter: dict[str, Any], body: str, *, folder_name: str | None, skill_md_text: str, paths: list[str]
) -> list[SpecIssue]:
    """Spec checks for one skill bundle; ``paths`` are the bundle paths relative to the skill root."""
    issues: list[SpecIssue] = []
    name = frontmatter.get("name")
    found = name_issue(name)
    if found is not None:
        issues.append(found)
    elif folder_name is not None and str(name) != folder_name:
        issues.append(SpecIssue("skill_name_folder_mismatch", "error", "name",
                                f"The name must equal the skill folder name ({folder_name})."))
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        issues.append(SpecIssue("skill_description_missing", "error", "description",
                                "Describe what the skill does and when to use it."))
    elif len(description) > DESCRIPTION_MAX:
        issues.append(SpecIssue("skill_description_too_long", "error", "description",
                                f"The description has at most {DESCRIPTION_MAX} characters."))
    compatibility = frontmatter.get("compatibility")
    if compatibility is not None and (not isinstance(compatibility, str) or len(compatibility) > COMPATIBILITY_MAX):
        issues.append(SpecIssue("skill_compatibility_invalid", "error", "compatibility",
                                f"compatibility is text of at most {COMPATIBILITY_MAX} characters."))
    metadata = frontmatter.get("metadata")
    if metadata is not None and (not isinstance(metadata, dict)
                                 or not all(isinstance(value, str) for value in metadata.values())):
        issues.append(SpecIssue("skill_metadata_invalid", "error", "metadata",
                                "metadata is a map of text keys to text values."))
    when_to_use = frontmatter.get("when_to_use")
    if when_to_use is not None and (not isinstance(when_to_use, str) or len(when_to_use) > WHEN_TO_USE_MAX):
        issues.append(SpecIssue("skill_when_to_use_invalid", "error", "when_to_use",
                                f"when_to_use is text of at most {WHEN_TO_USE_MAX} characters."))
    licence = frontmatter.get("license")
    if licence is not None and not isinstance(licence, str):
        issues.append(SpecIssue("skill_license_invalid", "error", "license", "license is text."))
    if not body.strip():
        issues.append(SpecIssue("skill_body_empty", "error", "body", "Write the instructions below the frontmatter."))
    if skill_md_text.count("\n") + 1 > SKILL_MD_LINE_WARNING:
        issues.append(SpecIssue("skill_md_long", "warning", "body",
                                f"Keep SKILL.md under {SKILL_MD_LINE_WARNING} lines; move details into references/."))
    for path in paths:
        parts = path.split("/")
        if len(parts) > 2 and parts[0] in {"references", "assets"}:
            issues.append(SpecIssue("skill_reference_too_deep", "warning", path,
                                    "Reference files sit one level below references/ or assets/."))
    return issues


def delivery_frontmatter(frontmatter: dict[str, Any], metadata_extra: dict[str, str]) -> dict[str, Any]:
    """The allowlisted frontmatter delivered to Claude Code; catalog metadata (``octryx-*``) is added last."""
    delivered: dict[str, Any] = {}
    for key in DELIVERY_FRONTMATTER_KEYS:
        if key in frontmatter:
            delivered[key] = frontmatter[key]
    upstream_metadata = frontmatter.get("metadata")
    metadata = {str(key): str(value) for key, value in upstream_metadata.items()} if isinstance(
        upstream_metadata, dict) else {}
    metadata.update(metadata_extra)
    delivered["metadata"] = metadata
    return delivered


def stripped_keys(frontmatter: dict[str, Any]) -> list[str]:
    return sorted(key for key in frontmatter if key not in DELIVERY_FRONTMATTER_KEYS)


def normalize_tags(value: Any) -> list[str]:
    """Free lower-case tags: deduplicated, sorted, invalid ones refused by the caller via :func:`tag_issues`."""
    if not isinstance(value, list):
        return []
    return sorted({str(item).strip().lower() for item in value if str(item or "").strip()})


def tag_issues(tags: list[str]) -> list[str]:
    return [tag for tag in tags if not TAG_PATTERN.match(tag)]


__all__ = [
    "DELIVERY_FRONTMATTER_KEYS",
    "EXECUTION_FRONTMATTER_KEYS",
    "NAME_PATTERN",
    "SKILL_FILE",
    "SPEC_FRONTMATTER_KEYS",
    "ParsedSkill",
    "SkillSpecError",
    "SpecIssue",
    "delivery_frontmatter",
    "name_issue",
    "normalize_tags",
    "parse_skill_md",
    "render_frontmatter",
    "render_skill_md",
    "replace_frontmatter",
    "stripped_keys",
    "tag_issues",
    "validate_skill",
]
