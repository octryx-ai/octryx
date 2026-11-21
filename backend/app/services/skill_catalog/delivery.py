"""What an octryx-claude session receives: the manifest and its content-addressed blobs.

The effective set for the surface ``octryx_claude`` (Workspace, user roles) becomes:

- per skill: the delivered files with their sha256 and size — ``SKILL.md`` rebuilt with the **frontmatter
  allowlist** (everything that grants tools or changes execution is dropped) plus the catalog metadata
  (``octryx-skill-id``, ``octryx-version``, ``octryx-digest``, ``octryx-workspace``, ``octryx-category``), the body
  plus the output
  contract and safety rules; references, assets and the LICENSE; scripts only when the version allows them;
- per MCP server entry allowed by the Workspace ``mcp_policy``: the launch spec with the image **by digest**.
  Variables the upstream spec takes from the user's shell are never passed through; values from named connections
  are not delivered in this version either (they would be readable by the agent inside the session), so they stay
  unset and are listed as such;
- ``withheld``: what is assigned but not delivered, with the reason.

The rebuilt files are stored as blobs, so ``GET …/skills/blobs/{sha256}`` serves exactly what the manifest
lists; a blob is served only when it belongs to the requesting session's manifest.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, Skill, SkillCategory, SkillVersion
from ...models.agent.skill_catalog import SKILL_KIND_MCP_SERVER
from ..mcp_access_policy import mcp_server_access_decision
from .bundle import KIND_MANIFEST, KIND_SCRIPT, BundleFile, bundle_digest, bundle_files, manifest, store_blobs
from .effective import Candidate, effective_skills
from .extension import SURFACE_OCTRYX_CLAUDE, delivered_body, normalize_extension
from .mcp_entry import delivered_server
from .spec import DELIVERY_FRONTMATTER_KEYS, SKILL_FILE, delivery_frontmatter, name_issue, render_skill_md

PLUGIN_NAME = "octryx"


def _metadata(candidate: Candidate, project_id: str | None) -> dict[str, str]:
    metadata = {"octryx-skill-id": candidate.skill.id, "octryx-version": str(candidate.version.version),
                "octryx-digest": candidate.version.bundle_digest}
    if project_id:
        metadata["octryx-workspace"] = project_id
    if candidate.category is not None:
        metadata["octryx-category"] = candidate.category.key
    return metadata


async def delivered_files(db: AsyncSession, candidate: Candidate, project_id: str | None
                          ) -> tuple[list[BundleFile], list[str]]:
    """``(files, withheld script paths)`` of one skill as Claude Code receives it."""
    version: SkillVersion = candidate.version
    files: list[BundleFile] = []
    withheld: list[str] = []
    for item in await bundle_files(db, version.files or []):
        kind = next(entry["kind"] for entry in version.files if entry["path"] == item.path)
        if item.path == SKILL_FILE:
            frontmatter = delivery_frontmatter(version.frontmatter or {}, _metadata(candidate, project_id))
            body = delivered_body(str(version.body or ""), normalize_extension(version.extension))
            files.append(BundleFile(SKILL_FILE, render_skill_md(frontmatter, body)))
        elif kind == KIND_SCRIPT and not version.scripts_allowed:
            withheld.append(item.path)
        elif kind != KIND_MANIFEST:
            # Delivered files are never executable on disk; an allowed script runs only as a governed Bash call.
            files.append(BundleFile(item.path, item.content))
    return files, withheld


def _server(candidate: Candidate, project: Project | None) -> tuple[dict[str, Any] | None, str]:
    decision = mcp_server_access_decision(candidate.skill.name, dict(project.config or {}) if project else {})
    if not decision.allowed:
        return None, "needs_mcp_policy"
    spec = candidate.version.launch_spec if isinstance(candidate.version.launch_spec, dict) else {}
    if spec.get("image") and not spec.get("image_digest"):
        return None, "image_digest_missing"
    return {
        "name": candidate.skill.name, "skill_id": candidate.skill.id, "version": candidate.version.version,
        "digest": candidate.version.bundle_digest, "server": delivered_server(spec, {}),
        "env_unset": sorted(set(spec.get("passthrough") or [])),
    }, ""


async def build_manifest(db: AsyncSession, *, project_id: str | None, user_roles: list[str]) -> dict[str, Any]:
    project = await db.get(Project, project_id) if project_id else None
    skills: list[dict[str, Any]] = []
    servers: list[dict[str, Any]] = []
    withheld: list[dict[str, str]] = []
    for candidate in await effective_skills(db, project_id=project_id, surface=SURFACE_OCTRYX_CLAUDE,
                                            user_roles=user_roles):
        if candidate.skill.kind == SKILL_KIND_MCP_SERVER:
            server, reason = _server(candidate, project)
            if server is None:
                withheld.append({"name": candidate.skill.name, "reason": reason})
            else:
                servers.append(server)
            continue
        if name_issue(candidate.skill.name) is not None:
            withheld.append({"name": candidate.skill.name, "reason": "name_not_deliverable"})
            continue
        files, scripts = await delivered_files(db, candidate, project_id)
        await store_blobs(db, files)
        entries = manifest(files)
        skills.append({
            "name": candidate.skill.name, "skill_id": candidate.skill.id, "version": candidate.version.version,
            "source_digest": candidate.version.bundle_digest, "bundle_digest": bundle_digest(entries),
            "category": candidate.category.key if candidate.category else None,
            "files": [{"path": entry["path"], "sha256": entry["sha256"], "size": entry["size"]} for entry in entries],
            "scripts_withheld": scripts,
        })
    body = {"plugin": PLUGIN_NAME, "workspace_id": project_id, "skills": skills, "mcp_servers": servers,
            "withheld": withheld}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return {**body, "manifest_digest": f"sha256:{hashlib.sha256(encoded).hexdigest()}"}


async def delivery_preview(db: AsyncSession, skill: Skill, version: SkillVersion) -> dict[str, Any]:
    """What an octryx-claude session would receive from this version (admin detail → Delivery; no Workspace)."""
    category = await db.get(SkillCategory, version.category_id) if version.category_id else None
    parent = await db.get(SkillCategory, category.parent_id) if category is not None and category.parent_id else None
    stripped = sorted(set(version.frontmatter or {}) - set(DELIVERY_FRONTMATTER_KEYS))
    if skill.kind == SKILL_KIND_MCP_SERVER:
        spec = version.launch_spec if isinstance(version.launch_spec, dict) else {}
        return {"kind": skill.kind, "plugin": PLUGIN_NAME, "server": delivered_server(spec, {}),
                "image_digest": spec.get("image_digest"), "env_unset": sorted(set(spec.get("passthrough") or [])),
                "files": [], "skill_md": None, "scripts_withheld": [], "stripped_keys": stripped}
    candidate = Candidate(skill, version, category, parent, delivered=True, reason="", assigned_by="all")
    files, withheld = await delivered_files(db, candidate, None)
    skill_md = next((item.content for item in files if item.path == SKILL_FILE), "")
    return {"kind": skill.kind, "plugin": PLUGIN_NAME, "command": f"/{PLUGIN_NAME}:{skill.name}",
            "deliverable": name_issue(skill.name) is None,
            "files": [{"path": entry["path"], "size": entry["size"]} for entry in manifest(files)],
            "skill_md": skill_md, "scripts_withheld": withheld, "stripped_keys": stripped}


def manifest_blobs(manifest_body: dict[str, Any]) -> set[str]:
    return {entry["sha256"] for skill in manifest_body.get("skills") or [] for entry in skill.get("files") or []}


__all__ = ["PLUGIN_NAME", "build_manifest", "delivered_files", "delivery_preview", "manifest_blobs"]
