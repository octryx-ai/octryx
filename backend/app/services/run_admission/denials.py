"""The typed denials of run admission."""

from __future__ import annotations

from fastapi import HTTPException

WORKFLOW_ARCHIVED = "workflow_archived"
ACTION_AGENT_AND_WORKFLOW = "action_agent_and_workflow"
WORKSPACE_REQUIRED = "workspace_required"
STATE_DENIED = "denied"
STATE_NEEDS_CONFIGURATION = "needs_configuration"

MESSAGES = {
    WORKFLOW_ARCHIVED: "This workflow is archived or switched off. Start one of the published workflows instead.",
    ACTION_AGENT_AND_WORKFLOW: "An Action runs either a workflow run or an agent with a prompt, never both.",
    WORKSPACE_REQUIRED: "A workflow run needs a Workspace. Choose a Workspace (for the chat, the Work item or the "
                        "Action) and start the run again.",
}


def workspace_required_detail(message: str = MESSAGES[WORKSPACE_REQUIRED]) -> dict[str, object]:
    return {"state": STATE_NEEDS_CONFIGURATION, "code": WORKSPACE_REQUIRED, "reason": WORKSPACE_REQUIRED,
            "message": message}


def denial(code: str, **extra: object) -> dict[str, object]:
    return {"state": STATE_DENIED, "code": code, "reason": code, "message": MESSAGES[code], **extra}


def denial_http(code: str, *, status_code: int = 409, **extra: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail=denial(code, **extra))
