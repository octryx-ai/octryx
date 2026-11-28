"""The Workspace switch ``knowledge_source_acl.enforce``: read it, change it (audited), and what it would release. Only
a platform admin changes it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models import AuditLog, Project
from .....models.project.knowledge_source_sync import KnowledgeSourceConnector
from ...access.source_acl import ACL_CONFIG_KEY, acl_enforcement_enabled
from .contract import REASON_RESTRICTED_ACL
from .items import ConnectorRef
from .run_report import current_withheld

ENFORCE_AUDIT_ACTION = "knowledge_source_acl_enforce_changed"
RELEASE_NOTE = ("Each source's next sync ingests these items with their restriction; an item whose restriction its "
                "source cannot expand (e.g. a Jira security level) stays withheld.")


async def withheld_restricted_items(db: AsyncSession, project_id: str) -> int:
    rows = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == project_id))).scalars().all()
    total = 0
    for row in rows:
        total += (await current_withheld(db, ConnectorRef.of(row))).get(REASON_RESTRICTED_ACL, 0)
    return total


async def enforcement_state(db: AsyncSession, project_id: str) -> dict[str, Any]:
    enforce = await acl_enforcement_enabled(db, project_id)
    withheld = await withheld_restricted_items(db, project_id)
    return {"workspace_id": project_id, "enforce": enforce, "withheld_restricted_items": withheld,
            "released_when_enabled": 0 if enforce else withheld, "note": RELEASE_NOTE}


async def set_enforcement(db: AsyncSession, *, project_id: str, enforce: bool, reason: str, actor_id: str,
                          dry_run: bool) -> dict[str, Any]:
    state = await enforcement_state(db, project_id)
    before = state["enforce"]
    changed = before != enforce
    answer = {**state, "enforce": enforce if not dry_run else before, "requested": enforce, "changed": changed,
              "dry_run": dry_run, "released_when_enabled": state["withheld_restricted_items"]
              if enforce and not before else 0}
    if dry_run or not changed:
        return answer
    project = await db.get(Project, project_id)
    config = dict(project.config) if isinstance(project.config, Mapping) else {}
    section = config.get(ACL_CONFIG_KEY)
    config[ACL_CONFIG_KEY] = {**(dict(section) if isinstance(section, Mapping) else {}), "enforce": enforce}
    project.config = config  # a new object: the JSON column sees the change
    db.add(AuditLog(user_id=actor_id, action=ENFORCE_AUDIT_ACTION, resource_type="project", resource_id=project_id,
                    details={"workspace_id": project_id, "before": before, "after": enforce, "reason": reason,
                             "withheld_restricted_items": state["withheld_restricted_items"]}))
    await db.commit()
    return answer


__all__ = ["ENFORCE_AUDIT_ACTION", "enforcement_state", "set_enforcement", "withheld_restricted_items"]
