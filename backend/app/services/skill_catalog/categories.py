"""Skill categories: an admin-managed tree with two levels and stable keys, plus free tags.

- Keys are lower-case and stable: a top-level key is ``iac``; a child key is ``<parent key>.<name>``
  (``iac.terraform``). Renaming changes only the label, so Workspace assignments by category stay valid.
- Depth is at most two: a child cannot have children.
- A category that still holds skills (published or open versions) or active children cannot be archived
  (``skill_category_not_empty``); an archived category takes no new versions and can be restored.
- Counts: ``skills`` per category is the number of skills whose published version is in it; the tree adds a
  parent's own count and its children's (``total``).
- Tags are identity metadata (free, lower-case, not reviewed) and are set per skill.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Skill, SkillCategory, SkillVersion, SystemConfig, WorkspaceCapabilityBinding
from ...models.runtime.governed_revision import REVISION_STATE_DRAFT, REVISION_STATE_IN_REVIEW
from ...time_utils import utc_now
from .effective import CATEGORY_BINDING_PREFIX, KIND_CATEGORY_BINDING
from .errors import SkillCatalogError
from .spec import normalize_tags, tag_issues

KEY_SEGMENT = r"[a-z0-9]+(?:-[a-z0-9]+)*"
KEY_PATTERN = re.compile(rf"^{KEY_SEGMENT}(?:\.{KEY_SEGMENT})?$")
MAX_LABEL = 120
MAX_DESCRIPTION = 500
MAX_TAGS = 20
STARTER_MARKER = "skill_catalog.starter_categories_seeded"

AUDIT_CATEGORY_SAVED = "skill_catalog.category_saved"
AUDIT_CATEGORY_ARCHIVED = "skill_catalog.category_archived"
AUDIT_TAGS_SAVED = "skill_catalog.tags_saved"

#: Neutral starter tree, seeded once on a fresh catalog; admins rename, extend or archive it.
STARTER_TREE: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("iac", "Infrastructure as code", (("terraform", "Terraform"), ("packer", "Packer"))),
    ("kubernetes", "Kubernetes", (("helm", "Helm"), ("manifests", "Manifests"), ("operations", "Operations"))),
    ("cloud", "Cloud", (("aws", "AWS"),)),
    ("ticketing", "Ticketing", (("servicenow", "ServiceNow"), ("service-desk", "Service desk"))),
    ("engineering", "Engineering", (("documentation", "Documentation"), ("code-review", "Code review"))),
    ("operations", "Operations", (("monitoring", "Monitoring"), ("incident-response", "Incident response"))),
)


def _label(value: Any) -> str:
    label = str(value or "").strip()[:MAX_LABEL]
    if not label:
        raise SkillCatalogError("skill_category_label_required", 422, message="Give the category a label.")
    return label


def _audit(db: AsyncSession, actor_id: str, action: str, resource_type: str, resource_id: str, **details: Any) -> None:
    db.add(AuditLog(user_id=actor_id, action=action, resource_type=resource_type, resource_id=resource_id,
                    details=details))


async def get_category(db: AsyncSession, category_id: str) -> SkillCategory:
    category = await db.get(SkillCategory, category_id)
    if category is None:
        raise SkillCatalogError("skill_category_not_found", 404)
    return category


async def list_categories(db: AsyncSession) -> list[SkillCategory]:
    stmt = select(SkillCategory).order_by(SkillCategory.sort_order, SkillCategory.label, SkillCategory.key)
    return list((await db.execute(stmt)).scalars())


async def subtree_ids(db: AsyncSession, category_id: str) -> set[str]:
    """The category and its children (depth two)."""
    children = (await db.execute(select(SkillCategory.id).where(SkillCategory.parent_id == category_id))).scalars()
    return {category_id, *children}


async def published_counts(db: AsyncSession) -> dict[str, int]:
    stmt = (select(SkillVersion.category_id, func.count(SkillVersion.id))
            .where(SkillVersion.state == "published").group_by(SkillVersion.category_id))
    return {str(category_id): int(count) for category_id, count in (await db.execute(stmt)).all() if category_id}


async def tree(db: AsyncSession, *, include_archived: bool = True) -> list[dict[str, Any]]:
    categories = await list_categories(db)
    counts = await published_counts(db)
    rows = [serialize_category(item, counts.get(item.id, 0)) for item in categories
            if include_archived or item.archived_at is None]
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for row in rows:
        by_parent.setdefault(row["parent_id"], []).append(row)
    roots = by_parent.get(None, [])
    for root in roots:
        root["children"] = by_parent.get(root["id"], [])
        root["total"] = root["skills"] + sum(child["skills"] for child in root["children"])
        for child in root["children"]:
            child["children"], child["total"] = [], child["skills"]
    return roots


def serialize_category(category: SkillCategory, skills: int = 0) -> dict[str, Any]:
    return {
        "id": category.id,
        "key": category.key,
        "label": category.label,
        "description": category.description or "",
        "parent_id": category.parent_id,
        "sort_order": int(category.sort_order or 0),
        "archived": category.archived_at is not None,
        "skills": skills,
    }


async def _parent(db: AsyncSession, parent_id: Any) -> SkillCategory | None:
    if not parent_id:
        return None
    parent = await db.get(SkillCategory, str(parent_id))
    if parent is None:
        raise SkillCatalogError("skill_category_parent_not_found", 422)
    if parent.parent_id is not None:
        raise SkillCatalogError("skill_category_too_deep", 422, message="Categories have at most two levels.")
    if parent.archived_at is not None:
        raise SkillCatalogError("skill_category_archived", 422, message="The parent category is archived.")
    return parent


async def create_category(db: AsyncSession, payload: dict[str, Any], *, actor_id: str) -> SkillCategory:
    parent = await _parent(db, payload.get("parent_id"))
    raw_key = str(payload.get("key") or "").strip().lower()
    key = f"{parent.key}.{raw_key}" if parent is not None and "." not in raw_key else raw_key
    if not KEY_PATTERN.match(key) or (parent is None and "." in key) or (
            parent is not None and not key.startswith(f"{parent.key}.")):
        raise SkillCatalogError("skill_category_key_invalid", 422, message=(
            "Use lower-case letters, digits and hyphens; a child key is <parent key>.<name>."))
    if (await db.execute(select(SkillCategory.id).where(SkillCategory.key == key))).first() is not None:
        raise SkillCatalogError("skill_category_key_exists", 409, key=key)
    now = utc_now()
    category = SkillCategory(key=key, label=_label(payload.get("label")),
                             description=str(payload.get("description") or "").strip()[:MAX_DESCRIPTION],
                             parent_id=parent.id if parent is not None else None,
                             sort_order=int(payload.get("sort_order") or 0), created_at=now, updated_at=now)
    db.add(category)
    await db.flush()
    _audit(db, actor_id, AUDIT_CATEGORY_SAVED, "skill_category", category.id, key=key, created=True)
    return category


async def update_category(
    db: AsyncSession, category: SkillCategory, payload: dict[str, Any], *, actor_id: str
) -> SkillCategory:
    """Label, description and order change; the key and the parent never do (assignments stay valid)."""
    if "key" in payload and str(payload["key"] or "") != category.key:
        raise SkillCatalogError("skill_category_key_immutable", 422, message="The key of a category never changes.")
    if "parent_id" in payload and (payload["parent_id"] or None) != category.parent_id:
        raise SkillCatalogError("skill_category_parent_immutable", 422,
                                message="Create a new category to move skills under another parent.")
    if "label" in payload:
        category.label = _label(payload["label"])
    if "description" in payload:
        category.description = str(payload.get("description") or "").strip()[:MAX_DESCRIPTION]
    if "sort_order" in payload:
        category.sort_order = int(payload.get("sort_order") or 0)
    category.updated_at = utc_now()
    _audit(db, actor_id, AUDIT_CATEGORY_SAVED, "skill_category", category.id, key=category.key, created=False)
    await db.flush()
    return category


async def _in_use(db: AsyncSession, category: SkillCategory) -> dict[str, int]:
    versions = (await db.execute(select(func.count(func.distinct(SkillVersion.skill_id))).where(
        SkillVersion.category_id == category.id,
        SkillVersion.state.in_(["published", REVISION_STATE_DRAFT, REVISION_STATE_IN_REVIEW])))).scalar_one()
    children = (await db.execute(select(func.count(SkillCategory.id)).where(
        SkillCategory.parent_id == category.id, SkillCategory.archived_at.is_(None)))).scalar_one()
    return {"skills": int(versions or 0), "children": int(children or 0)}


async def archive_category(db: AsyncSession, category: SkillCategory, *, actor_id: str) -> SkillCategory:
    use = await _in_use(db, category)
    if use["skills"] or use["children"]:
        raise SkillCatalogError("skill_category_not_empty", 409, **use)
    category.archived_at = category.updated_at = utc_now()
    _audit(db, actor_id, AUDIT_CATEGORY_ARCHIVED, "skill_category", category.id, key=category.key)
    await db.flush()
    return category


async def restore_category(db: AsyncSession, category: SkillCategory, *, actor_id: str) -> SkillCategory:
    if category.parent_id is not None:
        await _parent(db, category.parent_id)
    category.archived_at = None
    category.updated_at = utc_now()
    _audit(db, actor_id, AUDIT_CATEGORY_SAVED, "skill_category", category.id, key=category.key, restored=True)
    await db.flush()
    return category


async def set_tags(db: AsyncSession, skill: Skill, tags: Any, *, actor_id: str) -> list[str]:
    normalized = normalize_tags(tags)
    invalid = tag_issues(normalized)
    if invalid:
        raise SkillCatalogError("skill_tag_invalid", 422, tags=invalid,
                                message="Tags are lower-case letters, digits, '.', '_' or '-' (at most 40).")
    if len(normalized) > MAX_TAGS:
        raise SkillCatalogError("skill_tags_too_many", 422, message=f"At most {MAX_TAGS} tags.")
    skill.tags = normalized
    _audit(db, actor_id, AUDIT_TAGS_SAVED, "skill", skill.id, tags=normalized)
    await db.flush()
    return normalized


async def tag_counts(db: AsyncSession) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for tags in (await db.execute(select(Skill.tags))).scalars():
        for tag in tags or []:
            counts[str(tag)] = counts.get(str(tag), 0) + 1
    return [{"tag": tag, "skills": count} for tag, count in sorted(counts.items())]


async def whole_category_assignments(db: AsyncSession) -> dict[str, int]:
    """``{category key: number of Workspaces that assign the category as a whole}`` (enabled bindings only)."""
    counts: dict[str, int] = {}
    keys = (await db.execute(select(WorkspaceCapabilityBinding.binding_key).where(
        WorkspaceCapabilityBinding.capability_kind == KIND_CATEGORY_BINDING,
        WorkspaceCapabilityBinding.is_enabled.is_(True),
        WorkspaceCapabilityBinding.binding_status != "hidden"))).scalars()
    for key in keys:
        if str(key).startswith(CATEGORY_BINDING_PREFIX):
            name = str(key)[len(CATEGORY_BINDING_PREFIX):]
            counts[name] = counts.get(name, 0) + 1
    return counts


async def ensure_starter_categories(db: AsyncSession) -> int:
    """Seed :data:`STARTER_TREE` once per instance (marker in ``system_config``); existing keys are kept."""
    if await db.get(SystemConfig, STARTER_MARKER) is not None:
        return 0
    existing = {row.key: row for row in await list_categories(db)}
    created = 0
    now = utc_now()
    for order, (key, label, children) in enumerate(STARTER_TREE):
        parent = existing.get(key)
        if parent is None:
            parent = SkillCategory(key=key, label=label, description="", sort_order=order, created_at=now,
                                   updated_at=now)
            db.add(parent)
            await db.flush()
            created += 1
        for child_order, (child_key, child_label) in enumerate(children):
            full_key = f"{key}.{child_key}"
            if full_key not in existing:
                db.add(SkillCategory(key=full_key, label=child_label, description="", parent_id=parent.id,
                                     sort_order=child_order, created_at=now, updated_at=now))
                created += 1
    db.add(SystemConfig(key=STARTER_MARKER, value="1", description="Skill catalog starter categories seeded"))
    await db.flush()
    return created


__all__ = [
    "KEY_PATTERN",
    "STARTER_TREE",
    "archive_category",
    "create_category",
    "ensure_starter_categories",
    "get_category",
    "list_categories",
    "published_counts",
    "restore_category",
    "serialize_category",
    "set_tags",
    "subtree_ids",
    "tag_counts",
    "tree",
    "update_category",
]
