"""The ``job_offer`` a device receives for a turn (``devices.jobs``)."""

from __future__ import annotations

from typing import Any

from ...models import DeviceJob


def offer_body(job: DeviceJob, *, limits: dict[str, Any], workflow_run_id: str | None = None,
               slot_exempt: bool = False, subagents: bool = False, browser: bool = False,
               local_decisions: dict[str, Any] | None = None, engine: str = "", review_call: bool = False,
               web: bool = False, browser_external: bool = False, builtin_tools: list[str] | None = None,
               system_prompt: str = "", compact_window: int | None = None, story_prompt: str = "",
               plain_prompt: str = "", context_window: int = 0, context_pack: dict[str, Any] | None = None,
               session_state: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        **({"slot_exempt": True} if slot_exempt else {}),
        "workflow_run_id": workflow_run_id,
        "job_id": job.id, "turn_id": job.turn_id, "prompt": job.turn_prompt or "", "folder": job.folder,
        "profile": job.profile, "model": job.turn_model or "", "workspace_id": job.workspace_id,
        "owner_user_id": getattr(job, "owner_user_id", None) or "",
        "permission_mode": getattr(job, "turn_permission_mode", None) or "",
        "effort": getattr(job, "turn_effort", None) or "", "chat_session_id": job.session_id,
        # The resumed session's files as the platform holds them (``engine_state``): a device without them restores.
        **_resume(job), **({"session_state": dict(session_state)} if session_state else {}),
        "policy_decision_id": job.policy_decision_id, "limits": limits,
        # A turn on the Workspace's governed models starts lean: Claude Code's own six tools, no user settings or
        # plugins (a plain Gemma turn can otherwise carry 123 tools / 149k characters and the upstream refuses).
        "lean": str(job.profile or "") == "governed",
        **({"engine": engine} if engine else {}),
        **({"subagents": True} if subagents else {}),
        **({"builtin_tools": list(builtin_tools)} if builtin_tools else {}),
        **({"system_prompt": system_prompt} if system_prompt else {}),
        **({"story_prompt": story_prompt} if story_prompt and subagents else {}),
        **({"plain_prompt": plain_prompt} if plain_prompt and subagents else {}),
        **({"compact_window": compact_window} if compact_window else {}),
        **({"model_context_window": context_window} if context_window > 0 else {}),
        **({"browser": True} if browser else {}), **({"review_call": True} if review_call else {}),
        **({"local_decisions": local_decisions} if isinstance(local_decisions, dict) else {}),
        # Allow by default: ``web``: the turn may use the web (Claude Code's WebSearch / WebFetch,
        # Codex's search), by the Workspace's ``tool_defaults.web_tools``; ``browser_external``: its browser may read
        # external pages (``tool_defaults.browser``).
        **({"web": True} if web else {}),
        **({"browser_external": True} if browser_external else {}),
        **({"context_pack": dict(context_pack)} if context_pack else {}),  # a writing phase's item and app folder
    }


def _resume(job: DeviceJob) -> dict[str, Any]:
    if job.claude_session_id:
        return {"resume_session_id": job.claude_session_id}
    resume = job.resume_claude_session_id or None
    if resume and resume.startswith("fork:"):
        return {"resume_session_id": resume.removeprefix("fork:"), "fork_session": True}
    return {"resume_session_id": resume}
