"""Attention entries that are not workflow-run states: agent questions, device and tool approvals."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, ClarificationQuestion, DeviceJob, DeviceJobApproval, Project, Session, User
from ...time_utils import ensure_utc
from .requests import action, text_input

MAX_ITEMS = 50


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def _chat(session_id: str, label: str) -> dict[str, str]:
    return {"href": f"/chat?session_id={session_id}", "label": label}


async def _workspaces(db: AsyncSession, ids: set[str | None]) -> dict[str, dict[str, str]]:
    ids = {value for value in ids if value}
    if not ids:
        return {}
    rows = (await db.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all()
    return {key: {"id": key, "name": name} for key, name in rows}


def _options(question: ClarificationQuestion) -> list[str]:
    raw = dict(question.context_json or {}).get("options") or dict(question.context_json or {}).get("choices") or []
    return [str(option)[:200] for option in raw if isinstance(option, (str, int, float))][:8] if isinstance(
        raw, list) else []


async def question_entries(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(ClarificationQuestion, Session).join(Session, Session.id == ClarificationQuestion.session_id)
        .where(ClarificationQuestion.status == "open", Session.user_id == user.id)
        .order_by(ClarificationQuestion.created_at.desc()).limit(MAX_ITEMS)
    )).all()
    names = await _workspaces(db, {session.project_id for _question, session in rows})
    entries = []
    for question, session in rows:
        path = f"/api/v1/clarifications/{question.id}"
        answers = [action(f"answer:{index}", option, path=f"{path}/answer", body={"answer_text": option},
                          tone="primary" if index == 0 else "neutral")
                   for index, option in enumerate(_options(question))]
        answers.append(action("answer", "Answer", path=f"{path}/answer", body={}, tone="primary" if not answers
                              else "neutral", input_=text_input("answer_text", "Your answer")))
        answers.append(action("skip", "Skip", path=f"{path}/skip", body={}))
        entries.append({
            "key": f"clarification:{question.id}", "kind": "question", "id": question.id,
            "title": question.question_text[:200], "subtitle": "Question from the agent",
            "text": question.question_text, "created_at": _iso(question.created_at),
            "expires_at": _iso(question.expires_at), "severity": "action",
            "workspace": names.get(session.project_id), "run": None, "work_item": None, "session_id": session.id,
            "link": _chat(session.id, "Open the thread"), "actions": answers,
        })
    return entries


async def device_approval_entries(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(DeviceJobApproval, DeviceJob).join(DeviceJob, DeviceJob.id == DeviceJobApproval.job_id)
        .where(DeviceJobApproval.status == "pending", DeviceJobApproval.owner_user_id == user.id)
        .order_by(DeviceJobApproval.created_at.desc()).limit(MAX_ITEMS)
    )).all()
    names = await _workspaces(db, {job.workspace_id for _approval, job in rows})
    entries = []
    for approval, job in rows:
        path = f"/api/v1/device-jobs/{job.id}/approvals/{approval.id}"
        actions = [action("allow_once", "Allow once", path=path, body={"decision": "allow_once"}, tone="primary")]
        if approval.can_allow_job_edits:
            actions.append(action("allow_job_edits", "Allow edits for this job", path=path,
                                  body={"decision": "allow_job_edits"}))
        actions.append(action("deny", "Deny", path=path, body={"decision": "deny"}, tone="danger"))
        entries.append({
            "key": f"device_approval:{approval.id}", "kind": "device_approval", "id": approval.id,
            "title": f"{approval.tool} on your device", "subtitle": job.folder,
            "text": str(approval.input_preview or "")[:400], "created_at": _iso(approval.created_at),
            "expires_at": _iso(approval.expires_at), "severity": "action",
            "workspace": names.get(job.workspace_id), "run": None, "work_item": None, "session_id": job.session_id,
            "link": _chat(job.session_id, "Open the device prompt"), "actions": actions,
        })
    return entries


async def tool_approval_entries(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    from ..approval.decidable import decidable_approvals
    from ..approval.detail import latest_preview_payload
    from ..approval.presentation import approval_texts

    approvals = await decidable_approvals(db, user, limit=MAX_ITEMS)
    sessions = {approval.session_id: await db.get(Session, approval.session_id)
                for approval in approvals if approval.session_id}
    names = await _workspaces(db, {approval.workspace_id or getattr(sessions.get(approval.session_id), "project_id",
                                                                    None) for approval in approvals})
    entries = []
    for approval in approvals:
        session = sessions.get(approval.session_id)
        texts = approval_texts(await latest_preview_payload(db, approval.id), approval.action or "")
        entries.append(_approval_entry(approval, session, user, texts,
                                       names.get(approval.workspace_id or getattr(session, "project_id", None))))
    return entries


def _approval_entry(approval: Approval, session: Session | None, user: User, texts: dict[str, Any],
                    workspace: dict[str, str] | None) -> dict[str, Any]:
    path = f"/api/v1/approvals/{approval.id}"
    own = session is not None and session.user_id == user.id
    governance = not approval.session_id and not approval.task_run_id
    # A governance publication is decided on its publishing page (as on the approval page): no buttons here.
    actions = [] if governance else [action("approve", "Allow", path=f"{path}/approve", tone="primary"),
                                     action("reject", "Do not allow", path=f"{path}/reject", tone="danger")]
    link = (_chat(session.id, "Open the chat card") if own
            else {"href": f"/chat?area=operations&tab=approvalDetail&approval={approval.id}",
                  "label": "Open the approval"})
    return {
        "key": f"tool_approval:{approval.id}", "kind": "gate", "id": approval.id, "title": texts["title"],
        "subtitle": "Approval in your session" if own else "Approval you may decide",
        "text": texts["subtitle"] or texts["title"], "created_at": _iso(approval.created_at), "severity": "action",
        "workspace": workspace, "run": None, "work_item": None,
        "session_id": approval.session_id, "link": link, "actions": actions,
    }


__all__ = ["device_approval_entries", "question_entries", "tool_approval_entries"]
