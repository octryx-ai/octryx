"""No Work in a private Workspace.

Work items, workflow runs and Actions (Tasks) are not available in a person's private Workspace yet: the Work and
Action surfaces give platform admins every Workspace (``secure_work.access.work_scope_project_ids`` answers
``None``; the Action panel lists, triggers and edits every Task), so nothing of that kind may ever exist there. Every
insert, and every move of an existing row into a private Workspace, is refused here, at the one place all creation
paths pass (platform items, Jira and ServiceNow imports, workflow and handoff runs, Actions).
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import event, inspect, select

from .project import Project

PRIVATE_ACCESS_MODE = "private"
REASON = "private_workspace_has_no_work"


def _refuse_private(_mapper, connection, target) -> None:
    project_id = getattr(target, "project_id", None)
    if not project_id:
        return
    mode = connection.execute(select(Project.access_mode).where(Project.id == project_id)).scalar_one_or_none()
    if mode == PRIVATE_ACCESS_MODE:
        raise HTTPException(status_code=409, detail={
            "reason": REASON,
            "message": "Work items, workflow runs and Actions are not available in a private Workspace."})


def _refuse_move(mapper, connection, target) -> None:
    if inspect(target).attrs.project_id.history.has_changes():  # only a move costs a lookup
        _refuse_private(mapper, connection, target)


def install(model_class: type) -> None:
    event.listen(model_class, "before_insert", _refuse_private)
    event.listen(model_class, "before_update", _refuse_move)


__all__ = ["REASON", "install"]
