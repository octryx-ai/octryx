"""First-run setup status for the Setup guide.

Seven steps in the order a new installation needs them: Workspace → Connectors → Sources → Models → SSO →
Roles → Agents. Workspace, Models and SSO are platform steps; Connectors, Sources, Roles and Agents are steps of
one Workspace (the one the person has switched to). Each step is ``done``, ``open`` or ``attention`` (something
exists but does not work, with a one-sentence reason); SSO and Roles are recommended, not required. Every state is
read from stored rows; nothing is guessed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AgentDefinition,
    ConnectorHealth,
    ConnectorNamedConnection,
    IdentityProvider,
    KnowledgeSourceConnector,
    KnowledgeSourceRevision,
    KnowledgeSourceSyncRun,
    Project,
    ProjectGroupRoleAssignment,
    ProjectUserRoleAssignment,
)
from ...models.project.knowledge_evidence import REVISION_STATE_PROJECTED
from ...models.project.knowledge_source_sync import RUN_STATE_COMPLETED, RUN_STATE_FAILED
from ..access_control import _user_is_admin
from ..knowledge.sources.sync.items import served_item_count
from ..workspace_models.store import read_models
from .service import get_setup_guide_status

DONE = "done"
OPEN = "open"
ATTENTION = "attention"

STEP_ORDER = ("workspace", "connectors", "sources", "models", "sso", "roles", "agents")
PLATFORM_STEPS = {"workspace", "models", "sso"}
RECOMMENDED_STEPS = {"sso", "roles"}


def _step(
    key: str, status: str, reason: str = "", *, scope: str | None = None, target: str | None = None
) -> dict[str, Any]:
    """``scope`` overrides the step's level when the fact that decides it lives elsewhere (a shared connection is a
    platform fact); ``target`` names the admin page that fixes the step when it is not the step's usual one."""
    return {
        "key": key,
        "scope": scope or ("platform" if key in PLATFORM_STEPS else "workspace"),
        "status": status,
        "reason": reason,
        "recommended": key in RECOMMENDED_STEPS,
        "target": target,
    }


async def _workspace_step(db: AsyncSession) -> dict[str, Any]:
    # The protected system Workspace ("default") does not count: a team needs a Workspace of its own.
    found = (
        await db.execute(
            select(Project.id).where(Project.is_active.is_(True), Project.is_system.is_(False)).limit(1)
        )
    ).scalar_one_or_none()
    return _step("workspace", DONE if found else OPEN)


async def _connectors_step(db: AsyncSession, workspace_id: str) -> dict[str, Any]:
    connections = (
        await db.execute(
            select(ConnectorNamedConnection).where(
                or_(ConnectorNamedConnection.project_id == workspace_id, ConnectorNamedConnection.project_id.is_(None))
            )
        )
    ).scalars().all()
    health = (
        await db.execute(select(ConnectorHealth).where(ConnectorHealth.project_id.in_([workspace_id, ""])))
    ).scalars().all()
    tested_ok = [row for row in connections if isinstance(row.last_test, dict) and row.last_test.get("ok") is True]
    healthy = [row for row in health if row.status == "ok"]
    # A connection of the Workspace itself makes the step a Workspace fact; one shared by the whole platform is
    # shown as such, never as the Workspace's own.
    if any(row.project_id == workspace_id for row in [*tested_ok, *healthy]):
        return _step("connectors", DONE)
    if tested_ok or healthy:
        return _step("connectors", DONE, "Uses a shared connection of the platform.", scope="platform")
    if connections or health:
        failed_test = any(isinstance(row.last_test, dict) and row.last_test.get("ok") is False for row in connections)
        failed = failed_test or any(row.status not in ("ok", "unknown") for row in health)
        reason = (
            "The last connection test failed; open the connection and test it again."
            if failed
            else "The connection has not been tested yet; test it before Workspaces use it."
        )
        return _step("connectors", ATTENTION, reason)
    return _step("connectors", OPEN)


async def _repository_indexed(db: AsyncSession, workspace_id: str) -> bool:
    from ...models.runtime.code_intelligence import CodeRepository

    indexed = (await db.execute(select(CodeRepository.id).where(CodeRepository.project_id == workspace_id,
                                                                CodeRepository.last_indexed_at.isnot(None))
                                .limit(1))).scalar_one_or_none()
    return indexed is not None


async def _sources_step(db: AsyncSession, workspace_id: str) -> dict[str, Any]:
    connectors = (
        await db.execute(select(KnowledgeSourceConnector).where(KnowledgeSourceConnector.project_id == workspace_id))
    ).scalars().all()
    indexed_document = (
        await db.execute(
            select(KnowledgeSourceRevision.id)
            .where(
                KnowledgeSourceRevision.project_id == workspace_id,
                KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    last_runs = {}
    run_ids = [connector.last_run_id for connector in connectors if connector.last_run_id]
    if run_ids:
        query = select(KnowledgeSourceSyncRun).where(KnowledgeSourceSyncRun.id.in_(run_ids))
        rows = (await db.execute(query)).scalars()
        last_runs = {run.id: run for run in rows}
    if indexed_document or any(run.state == RUN_STATE_COMPLETED for run in last_runs.values()):
        return _step("sources", DONE)
    # A repository is knowledge too: its code is indexed or held as central code sources (fresh-install finding C).
    if await _repository_indexed(db, workspace_id):
        return _step("sources", DONE)
    # A launcher snapshot completes passes without a sync run: a source that serves items has synced.
    for connector in connectors:
        if await served_item_count(db, connector) > 0:
            return _step("sources", DONE)
    if any(run.state == RUN_STATE_FAILED for run in last_runs.values()):
        return _step("sources", ATTENTION, "The last sync of a source failed; open Sources and sync it again.")
    if connectors:
        return _step("sources", ATTENTION, "A source is set up but has not synced yet; run it once.")
    return _step("sources", OPEN)


async def _models_step(db: AsyncSession) -> dict[str, Any]:
    guide = await get_setup_guide_status(db)
    if guide.get("ready"):
        return _step("models", DONE)
    if not (guide.get("stats") or {}).get("active_provider_count"):
        return _step("models", OPEN)
    pending = next(
        (step for step in guide.get("steps") or [] if step.get("blocking") and step.get("status") != "completed"),
        None,
    )
    # The pending step's own detail names the model and the problem ("Claude Sonnet 5.5 is #1 but not cleared for
    # data."); the button opens the page that fixes it.
    detail = str((pending or {}).get("detail") or "").strip()
    if (pending or {}).get("key") == "default":
        reason = f"{detail} Clear it for data or choose another default.".strip()
        return _step("models", ATTENTION, reason, target="modelOrder")
    title = str((pending or {}).get("title") or "A required model step").strip()
    reason = f"{title}: {detail}" if detail else f"{title} still needs action."
    return _step("models", ATTENTION, reason, target="providers")


async def _sso_step(db: AsyncSession) -> dict[str, Any]:
    found = (
        await db.execute(select(IdentityProvider.id).where(IdentityProvider.is_active.is_(True)).limit(1))
    ).scalar_one_or_none()
    return _step("sso", DONE if found else OPEN)


async def _roles_step(db: AsyncSession, workspace_id: str) -> dict[str, Any]:
    group = (
        await db.execute(
            select(ProjectGroupRoleAssignment.group_id)
            .where(ProjectGroupRoleAssignment.project_id == workspace_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if group:
        return _step("roles", DONE)
    users = (
        await db.execute(
            select(ProjectUserRoleAssignment.user_id).where(ProjectUserRoleAssignment.project_id == workspace_id)
        )
    ).scalars().all()
    for user_id in dict.fromkeys(users):
        if not await _user_is_admin(db, user_id):
            return _step("roles", DONE)
    return _step("roles", OPEN)


async def _agents_step(db: AsyncSession, workspace_id: str) -> dict[str, Any]:
    agent = (
        await db.execute(
            select(AgentDefinition.id)
            .where(
                AgentDefinition.is_active.is_(True),
                or_(AgentDefinition.project_id.is_(None), AgentDefinition.project_id == workspace_id),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    try:
        models = await read_models(db, workspace_id)
    except Exception:  # noqa: BLE001 - a Workspace whose models cannot be read has no allowed model for the guide
        models = {"models": []}
    allowed = any(row.get("allowed") and "chat" in (row.get("used_in") or []) for row in models.get("models") or [])
    if agent and allowed:
        return _step("agents", DONE)
    if agent:
        return _step("agents", ATTENTION, "No model is allowed for this Workspace, so its agents cannot answer.")
    return _step("agents", OPEN)


async def onboarding_status(db: AsyncSession, *, workspace_id: str | None) -> dict[str, Any]:
    """The seven setup steps; Workspace steps are ``open`` without a Workspace to check."""

    workspace = None
    if workspace_id:
        workspace = (
            await db.execute(select(Project).where(Project.id == workspace_id, Project.is_active.is_(True)))
        ).scalar_one_or_none()
    steps = {
        "workspace": await _workspace_step(db),
        "models": await _models_step(db),
        "sso": await _sso_step(db),
    }
    if workspace is None:
        for key in ("connectors", "sources", "roles", "agents"):
            steps[key] = _step(key, OPEN, "Choose a Workspace to check this step.")
    else:
        steps["connectors"] = await _connectors_step(db, workspace.id)
        steps["sources"] = await _sources_step(db, workspace.id)
        steps["roles"] = await _roles_step(db, workspace.id)
        steps["agents"] = await _agents_step(db, workspace.id)
    ordered = [steps[key] for key in STEP_ORDER]
    return {
        "workspace": {"id": workspace.id, "name": workspace.name} if workspace else None,
        "steps": ordered,
        "done_count": sum(1 for step in ordered if step["status"] == DONE),
        "total": len(ordered),
    }


__all__ = ["ATTENTION", "DONE", "OPEN", "STEP_ORDER", "onboarding_status"]
