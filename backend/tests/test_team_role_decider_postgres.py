"""Real PostgreSQL: membership authority stays locked until the human decision transaction ends."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete

from app.models import AuditLog, FlowDefinition, FlowDefinitionVersion, Project, User, UserProject, WorkflowRun
from app.models.runtime.work_role_model import WorkRoleAssignment
from app.services.workflow_runs.decider import require_node_decider
from app.services.workflow_runs.records import WorkflowRunError
from tests.knowledge_retention_postgres_support import (
    UNGRANTED_ROW_WAIT,
    postgres_sessions,
    requires_postgres,
    until,
)
from tests.test_team_role_decider_policy import setup_case
from tests.work_role_support import assign_seed_role, set_seed_role_active

pytestmark = pytest.mark.asyncio


@requires_postgres
async def test_current_role_revocation_waits_for_final_decision_and_next_attempt_is_refused():
    engine, factory = postgres_sessions()
    case = None
    try:
        async with factory() as seed:
            case = await setup_case(seed)
            role = await assign_seed_role(seed, case.project, "product_manager", user_id=case.pm.id)
            await seed.commit()
            role_id, run_id = role.id, case.run.id
        async with factory() as final, factory() as revoke, factory() as observer:
            run = await final.get(WorkflowRun, run_id)
            pm = await final.get(User, case.pm.id)
            resolution = await require_node_decider(final, run, pm)
            assert resolution.allows(pm.id)
            assignment = await revoke.get(WorkRoleAssignment, role_id)
            pending = asyncio.create_task(set_seed_role_active(revoke, assignment, False))
            await until(observer, UNGRANTED_ROW_WAIT, 1)
            assert not pending.done()
            await final.commit()
            row = await asyncio.wait_for(pending, timeout=10)
            assert not row.is_active
            await revoke.commit()
            with pytest.raises(WorkflowRunError) as refused:
                await require_node_decider(final, run, pm)
            assert refused.value.code == "decider_unresolved"
            await final.rollback()
    finally:
        if case is not None:
            async with factory() as cleanup:
                version = await cleanup.get(FlowDefinitionVersion, case.run.flow_definition_version_id)
                await cleanup.execute(delete(WorkflowRun).where(WorkflowRun.id == case.run.id))
                await cleanup.execute(delete(FlowDefinitionVersion).where(FlowDefinitionVersion.id == version.id))
                await cleanup.execute(delete(FlowDefinition).where(FlowDefinition.id == version.flow_id))
                await cleanup.execute(delete(WorkRoleAssignment).where(WorkRoleAssignment.project_id == case.project))
                await cleanup.execute(delete(AuditLog).where(AuditLog.user_id.in_(
                    [case.admin.id, case.pm.id, case.requester.id])))
                await cleanup.execute(delete(UserProject).where(UserProject.project_id == case.project))
                await cleanup.execute(delete(Project).where(Project.id == case.project))
                await cleanup.execute(delete(User).where(User.id.in_([case.admin.id, case.pm.id, case.requester.id])))
                await cleanup.commit()
        await engine.dispose()
