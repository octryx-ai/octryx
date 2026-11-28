"""The optional deploy phase of Feature delivery: the Workspace's deploy job on its CI connection."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import utc_now
from .dispatch import (
    CLASS_EXTERNAL,
    CLASS_NOT_CONFIGURED,
    CLASS_SAFETY,
    FAILED,
    SUCCEEDED,
    ToolOutcome,
    class_of_exception,
)

DEPLOY_CONFIG_KEY = "deploy_job"


async def deploy_job(db: AsyncSession, run: WorkflowRun) -> str:
    from ...project.service import get_project_config

    config = await get_project_config(run.project_id, db) if run.project_id else {}
    return str(dict(config or {}).get(DEPLOY_CONFIG_KEY) or "").strip()[:200]


async def jenkins_client(db: AsyncSession, run: WorkflowRun) -> Any | None:
    from ...named_connections.service_connection import service_connection
    from ...secure_work.cicd.jenkins_client import JenkinsClient, JenkinsRuntimeConfig

    found = await service_connection(db, "jenkins", run.project_id)
    if found is None:
        return None
    _connection, config = found
    return JenkinsClient(JenkinsRuntimeConfig(base_url=str(config.get("jenkins_url") or ""),
                                              username=config.get("jenkins_username"),
                                              token=config.get("jenkins_token")))


async def configured(db: AsyncSession, run: WorkflowRun) -> tuple[ToolOutcome, str]:
    job = await deploy_job(db, run)
    if job and await jenkins_client(db, run) is not None:
        return ToolOutcome(SUCCEEDED, {"job": job}), "configured"
    return ToolOutcome(SUCCEEDED, {"job": None}), "not_configured"


async def run_deploy(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    from ..deploy_four_eyes import CONTEXT_KEY, deploy_approval_refusal

    del params
    refused = await deploy_approval_refusal(db, run)
    if refused:
        return ToolOutcome(FAILED, reason=refused, failure_class=CLASS_SAFETY)
    job = await deploy_job(db, run)
    client = await jenkins_client(db, run) if job else None
    if client is None:
        return ToolOutcome(FAILED, reason="the Workspace has no deploy job on a Jenkins connection",
                           failure_class=CLASS_NOT_CONFIGURED)
    started = utc_now()
    try:
        result = await client.trigger_build(job)
    except Exception as error:  # an unreachable CI is a failed start, recorded with its reason
        return ToolOutcome(FAILED, reason=f"{type(error).__name__}: {error}"[:300],
                           failure_class=class_of_exception(error))
    if not result.get("queued") or not result.get("queue_url"):
        return ToolOutcome(FAILED, dict(result), "the deploy job was not queued with a queue item to watch",
                           failure_class=CLASS_EXTERNAL)
    approval_id = dict(dict(run.context or {}).get(CONTEXT_KEY) or {}).get("approval_id")
    run.context = {**dict(run.context or {}), "deploy": {"job": job, "queued_at": started.isoformat(),
                                                        "queue_url": result.get("queue_url"),
                                                        "approval_id": approval_id}}
    return ToolOutcome(SUCCEEDED, {"job": job, "queued": True})


__all__ = ["DEPLOY_CONFIG_KEY", "configured", "deploy_job", "jenkins_client", "run_deploy"]
