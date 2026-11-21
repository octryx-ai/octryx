"""The ``job_offer`` a device receives for a turn (``devices.jobs``)."""

from __future__ import annotations

from typing import Any

from ...models import DeviceJob


def offer_body(job: DeviceJob, *, limits: dict[str, Any], workflow_run_id: str | None = None,
               slot_exempt: bool = False, subagents: bool = False, browser: bool = False,
               local_decisions: dict[str, Any] | None = None, engine: str = "",
               review_call: bool = False, web: bool = False,
               browser_external: bool = False, builtin_tools: list[str] | None = None,
               system_prompt: str = "", compact_window: int | None = None, story_prompt: str = "",
               plain_prompt: str = "") -> dict[str, Any]:
    """The ``job_offer`` the device gets: a prompt and its target; never settings, rules or a permission mode.

    ``workflow_run_id``: the run the chat thread follows; the device's session binds to it (checked again on
    the server), so the device job works on the run's current phase. ``slot_exempt``: a team's platform turn on its
    run's main thread, which the device does not count against its parallel limit (``teamwork.slots``).

    ``subagents``: the run's current phase opted in to Claude Code's own sub-agents (``workflow_runs.octryx.
    subagents``); only then the offer carries ``subagents: true`` and the launcher runs the turn as a whole-story
    Claude Code session (full tool set, ``Agent`` included). ``browser``: that phase also opted in to a browser of its
    own (``config.browser``, ``workflow_runs.octryx.browser``); the launcher then adds the Playwright MCP server, which
    starts an isolated headless browser for that session only. ``local_decisions``: that phase decides its tool calls
    on the device (``config.tool_decisions: "local"``, ``workflow_runs.octryx.local_decisions``): the data the
    launcher's hard-deny rules need; the launcher asks the platform for every call it cannot decide. ``engine``: the
    coding engine the turn runs on (``claude_code`` or ``codex``, ``devices.job_engine``); empty means Claude Code.
    ``review_call``: the turn is the independent reviewer's call on the person's seat (``workflow_runs.review.seat``):
    the launcher fetches the request from the platform and answers it with one tool-less model call.
    ``web``: the turn may use the web (the Workspace's ``tool_defaults.web_tools``: every turn, or only the phases
    its Workspace lists for research, ``device_runs.research_phases``); the launcher adds Claude Code's own
    WebSearch / WebFetch to the turn's built-in tools and Codex's search on a seat (when the platform's web tools fail
    with ``transport``, the session still has WebSearch to fall back on)."""
    return {
        **({"slot_exempt": True} if slot_exempt else {}),
        "workflow_run_id": workflow_run_id,
        "job_id": job.id, "turn_id": job.turn_id, "prompt": job.turn_prompt or "", "folder": job.folder,
        "profile": job.profile, "model": job.turn_model or "", "workspace_id": job.workspace_id,
        "permission_mode": getattr(job, "turn_permission_mode", None) or "",
        "effort": getattr(job, "turn_effort", None) or "",
        "chat_session_id": job.session_id,
        **_resume(job),
        "policy_decision_id": job.policy_decision_id, "limits": limits,
        # A turn on the Workspace's governed models starts lean: Claude Code's own six tools, no user settings or
        # plugins (a plain Gemma turn can otherwise carry 123 tools / 149k characters and the upstream refuses).
        "lean": str(job.profile or "") == "governed",
        **({"engine": engine} if engine else {}),
        **({"subagents": True} if subagents else {}),
        # A run turn's built-in tools and system prompt are data (``octryx.turn_tools``).
        **({"builtin_tools": list(builtin_tools)} if builtin_tools else {}),
        **({"system_prompt": system_prompt} if system_prompt else {}),
        # The story and plain session paragraphs from the catalog (``run.device.*_session_prompt``, prompt audit #4).
        **({"story_prompt": story_prompt} if story_prompt and subagents else {}),
        **({"plain_prompt": plain_prompt} if plain_prompt and subagents else {}),
        **({"compact_window": compact_window} if compact_window else {}),
        **({"browser": True} if browser else {}),
        **({"local_decisions": local_decisions} if isinstance(local_decisions, dict) else {}),
        **({"review_call": True} if review_call else {}),
        # Allow by default: ``web``: the turn may use the web (Claude Code's WebSearch / WebFetch,
        # Codex's search), by the Workspace's ``tool_defaults.web_tools``; ``browser_external``: its browser may read
        # external pages (``tool_defaults.browser``).
        **({"web": True} if web else {}),
        **({"browser_external": True} if browser_external else {}),
    }


def _resume(job: DeviceJob) -> dict[str, Any]:
    """The Claude Code session a turn continues; a fork's first turn (``fork:<id>``) resumes a copy of ``<id>``."""
    if job.claude_session_id:
        return {"resume_session_id": job.claude_session_id}
    resume = job.resume_claude_session_id or None
    if resume and resume.startswith("fork:"):
        return {"resume_session_id": resume.removeprefix("fork:"), "fork_session": True}
    return {"resume_session_id": resume}
