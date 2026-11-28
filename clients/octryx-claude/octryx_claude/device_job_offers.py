"""A job offer on the device: the local checks it must pass, the fields read from it, and its turn.
The checks run whatever the platform decided; only the fields :func:`offer_fields` names are read."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from . import device_folder_access, device_state, local_profiles, model_picker
from .profile_choice import seat_logged_in

# The chat's permission mode and effort for the turn ("": the defaults); anything else is refused.
PERMISSION_MODES = frozenset({"", "default", "acceptEdits", "plan", "bypassPermissions"})
EFFORTS = frozenset({"", "low", "medium", "high", "xhigh", "max"})
LOCAL_PREFIX = "local:"  # a Claude Code profile outside octryx (``local_profiles``)

DEFAULT_APPROVAL_TIMEOUT_S = 300
DEFAULT_MAX_JOB_MINUTES = 60
MAX_APPROVAL_TIMEOUT_S = 3600
MAX_JOB_MINUTES = 24 * 60
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _bounded(value: Any, default: int, maximum: int) -> int:
    return value if type(value) is int and 0 < value <= maximum else default


def slot_exempt(body: dict[str, Any]) -> bool:
    # These turns take seconds and must never wait behind a work item; they are bounded among themselves.
    return body.get("slot_exempt") is True and bool(str(body.get("workflow_run_id") or ""))


class Turn:
    def __init__(self, job_id: str, turn_id: str, *, limits: dict[str, Any]) -> None:
        self.job_id = job_id
        self.turn_id = turn_id
        self.approval_timeout_s = _bounded(limits.get("approval_timeout_s"), DEFAULT_APPROVAL_TIMEOUT_S,
                                           MAX_APPROVAL_TIMEOUT_S)
        self.max_job_minutes = _bounded(limits.get("max_job_minutes"), DEFAULT_MAX_JOB_MINUTES, MAX_JOB_MINUTES)
        self.driver: Any = None
        self.task: asyncio.Task | None = None
        self.stop_reason = ""
        self.slot_exempt = False  # a team's platform turn on its run's main thread (``slot_exempt``): no slot
        # ``turn_finished`` was sent; only the clean-up (left-over processes, uploads, the signer) is still running.
        self.finished = False


def offer_fields(body: dict[str, Any], folder: str, device: dict[str, Any], job_id: str) -> dict[str, Any]:
    return {"job_id": job_id, "prompt": str(body.get("prompt") or ""), "folder": folder,
            "profile": str(body["profile"]),
            "model": str(body.get("model") or ""),
            "permission_mode": str(body.get("permission_mode") or ""), "effort": str(body.get("effort") or ""),
            "workspace_id": str(body.get("workspace_id") or ""),
            "resume": str(body.get("resume_session_id") or "") or None,
            # Continue a copy of that session; the running original stays untouched.
            "fork": body.get("fork_session") is True and bool(body.get("resume_session_id")),
            # The resumed session's files as the platform holds them (``engine_state``).
            "session_state": body.get("session_state") if isinstance(body.get("session_state"), dict) else None,
            "workflow_run": str(body.get("workflow_run_id") or ""),
            "lean": body.get("lean") is True,
            "subagents": body.get("subagents") is True,
            "browser": body.get("browser") is True,
            "builtin_tools": [str(name) for name in body.get("builtin_tools") or [] if isinstance(name, str) and name],
            "compact_window": body.get("compact_window") if type(body.get("compact_window")) is int else None,
            "model_context_window": body.get("model_context_window")
            if type(body.get("model_context_window")) is int else None,
            "system_prompt": str(body.get("system_prompt") or ""),
            "story_prompt": str(body.get("story_prompt") or ""),
            "plain_prompt": str(body.get("plain_prompt") or ""),
            # A writing phase's first turn starts with the context pack built here (``context_pack``).
            "context_pack": body.get("context_pack") if isinstance(body.get("context_pack"), dict) else None,
            # The turn may use the web (allow by default, block as an admin option; the platform decides it from
            # the Workspace's tool defaults and a research phase): Claude Code's own WebSearch / WebFetch join its
            # tools.
            "web": body.get("web") is True,
            # The session's browser may open external pages to read them; absent: loopback only.
            "browser_external": body.get("browser_external") is True,
            # The phase decides its tool calls on this device (``local_decisions``: the hard-deny list only).
            "local_decisions": body.get("local_decisions") if isinstance(body.get("local_decisions"), dict)
            else None,
            "base_url": str(device.get("base_url") or ""),
            # The coding engine the platform chose for this job (``claude_code`` | ``codex``; empty: Claude Code).
            "engine": str(body.get("engine") or ""),
            # The independent reviewer's call on this seat (``review_call``): one tool-less model call.
            "review_call": body.get("review_call") is True}


class OfferChecks:

    def _rejection(self, body: dict[str, Any], device: dict[str, Any]) -> tuple[str, str]:
        if self.draining:
            return "device_updating", ""
        if (self.channel is not None and self.channel.paused) or device.get("paused"):
            return "device_paused", ""
        limit = int(device.get("max_parallel_jobs") or device_state.DEFAULT_PARALLEL_JOBS)
        exempt = slot_exempt(body)
        if sum(1 for turn in self.turns.values() if turn.slot_exempt == exempt) >= limit:
            return "device_busy", ""
        if str(body.get("job_id")) in self.turns:
            return "device_job_busy", ""
        if str(body.get("profile") or "").startswith(LOCAL_PREFIX):
            return self._local_rejection(body)
        if device.get("runner"):
            from .runner import admit_tenant, ensure_job_folder  # noqa: PLC0415

            if not admit_tenant(self.state, body, busy=bool(self.turns)):
                return "runner_tenant_switch_refused", ""
            ensure_job_folder(str(body.get("folder") or ""))
        folder = device_state.folder_allowed(str(body.get("folder") or ""), list(device.get("folders") or []))
        if not folder:
            return "folder_not_allowlisted_on_device", ""
        if problem := device_folder_access.access_problem(folder):
            return problem, ""
        profile = str(body.get("profile") or "")
        if profile not in ("governed", "seat") or (profile == "seat" and not seat_logged_in(self.state)):
            return "profile_unavailable_on_device", ""
        model = body.get("model") or ""
        if model and not model_picker.valid_model_id(model):
            return "model_invalid", ""
        if str(body.get("permission_mode") or "") not in PERMISSION_MODES or \
                str(body.get("effort") or "") not in EFFORTS:
            return "turn_options_invalid", ""
        return "", folder

    def _local_rejection(self, body: dict[str, Any]) -> tuple[str, str]:  # noqa: PLR0911
        # Re-checked here whatever the platform said; the folder allowlist is for octryx's own runs only.
        profile = local_profiles.find(self.state, str(body.get("profile") or "")[len(LOCAL_PREFIX):])
        if profile is None:
            return "profile_unavailable_on_device", ""
        if not profile.allow_takeover:  # the person's explicit opt-in on this Mac
            return "takeover_not_allowed_on_device", ""
        session_id = str(body.get("resume_session_id") or "")
        folder = local_profiles.session_folder(profile, session_id)
        if not folder:
            return "local_session_not_on_device", ""
        if os.path.realpath(folder) != os.path.realpath(str(body.get("folder") or "")):
            return "folder_not_allowlisted_on_device", ""
        if problem := device_folder_access.access_problem(folder):
            return problem, ""
        return "", folder
