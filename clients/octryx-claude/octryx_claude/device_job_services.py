"""What a running device turn uses besides its driver: approvals, the local-decision audit upload, the review call's
control plane and the local decision model's route suggestion (mixed into ``device_jobs.JobManager``)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from octryx_claude import local_policy

from . import device_state
from .device_outbox import OutboxFullError
from .device_sdk_events import input_preview

if TYPE_CHECKING:
    from .device_job_offers import Turn
    from .device_session import PreparedSession

logger = logging.getLogger("octryx_claude.device")

# The audit of a session that decides locally goes up in batches this often (``local_decisions``).
AUDIT_UPLOAD_SECONDS = 5.0
AUDIT_UPLOAD_TIMEOUT = 15.0
REVIEW_CONTROL_TIMEOUT = 60.0  # the review request carries the screenshots (``review_call``)
QUESTION_TOOLS = frozenset({"AskUserQuestion"})


class TurnServices:
    def _start_audit_upload(self, prepared: PreparedSession, offer: dict[str, Any]) -> asyncio.Task | None:
        """A phase that decides its tool calls on this device (``local_decisions``): the policy goes next to the
        session's state for its hooks, and the audit they spool goes to the platform every
        :data:`AUDIT_UPLOAD_SECONDS` while the turn runs, never in a tool call's way."""
        offered = offer.get("local_decisions")
        if not isinstance(offered, dict) or not offer.get("workflow_run") or not getattr(prepared, "session_key", ""):
            return None

        try:
            local_policy.write_policy(self.state.session_dir(prepared.session_key), offered, root=offer["folder"],
                                         state_root=str(self.state.root))
        except OSError:
            logger.warning("job %s: no local tool decisions (policy not written); the platform decides each call",
                           offer.get("job_id"))
            return None

        async def upload() -> None:
            while True:
                await asyncio.sleep(AUDIT_UPLOAD_SECONDS)
                await asyncio.to_thread(self._drain_audit, prepared, offer)

        return asyncio.create_task(upload())

    def _review_control(self, offer: dict[str, Any], prepared: PreparedSession) -> Callable[..., tuple[bool, Any]]:
        """The control plane for a review call's session (``review_call``): its request and its answer."""
        from .platform import SessionContext, call_control_plane  # noqa: PLC0415
        from .state import CREDENTIAL_SET_DEVICE  # noqa: PLC0415

        context = SessionContext(offer["base_url"], prepared.session_key, offer["workspace_id"], "", "")

        def control(method: str, path: str, body: dict[str, Any] | None) -> tuple[bool, Any]:
            with self.http_factory() as http:
                result = call_control_plane(self.state.with_credential_set(CREDENTIAL_SET_DEVICE), context, method,
                                            path, http=http, timeout=REVIEW_CONTROL_TIMEOUT, body=body, retry=True)
            return result.outcome == "ok", result.body if result.outcome == "ok" else result.reason

        return control

    def _drain_audit(self, prepared: PreparedSession, offer: dict[str, Any]) -> None:
        from . import hooks  # noqa: PLC0415
        from .platform import SessionContext  # noqa: PLC0415
        from .state import CREDENTIAL_SET_DEVICE  # noqa: PLC0415

        context = SessionContext(offer["base_url"], prepared.session_key, offer["workspace_id"], "",
                                 offer.get("workflow_run", ""))
        with self.http_factory() as http:
            hooks.drain_audit(self.state.with_credential_set(CREDENTIAL_SET_DEVICE), context, http,
                              timeout=AUDIT_UPLOAD_TIMEOUT)

    def _suggest_route(self, offer: dict[str, Any], emit: Callable[[dict[str, Any]], Any]) -> None:
        """The local decision model's suggestion for this turn, sent as a ``route`` event (measured before it is
        used). Only when switched on on this Mac (``octryx-claude device router on``); it never changes the turn."""
        device = device_state.load_device(self.state)
        if not device.get("router"):
            return
        from .local_model import LocalModel, chosen_model, usable
        from .router import suggest

        spec = chosen_model(device)
        # The platform's licence switch travels with every offer (default: permissive licences only).
        permissive_only = (offer.get("limits") or {}).get("local_models_permissive_only") is not False
        if device.get("local_models_permissive_only") != permissive_only:
            device_state.save_device(self.state, {**device, "local_models_permissive_only": permissive_only})
        if not usable(spec, device, permissive_only=permissive_only):
            return  # a restricted model the platform does not allow, or whose licence was not accepted here
        if self.local_model is None or self.local_model.spec != spec:
            self.local_model = LocalModel(self.state.root / "models", spec=spec)

        async def run() -> None:
            route = await asyncio.wait_for(suggest(self.local_model, offer["prompt"]), timeout=60)
            if route is not None:
                with contextlib.suppress(OutboxFullError):
                    await emit({"kind": "route", **route, "chosen_model": offer.get("model") or "",
                                "chosen_effort": offer.get("effort") or ""})

        task = asyncio.create_task(run())
        self._route_tasks.add(task)
        task.add_done_callback(lambda done: (self._route_tasks.discard(done),
                                             done.cancelled() or done.exception()))

    async def stop_local_model(self, *, only_idle: bool = False) -> None:
        if self.local_model is None:
            return
        if only_idle:
            await self.local_model.stop_when_idle()
        else:
            await self.local_model.stop()

    async def _decide(self, turn: Turn, tool: str, tool_input: dict[str, Any]) -> tuple[str, str]:
        if tool in QUESTION_TOOLS:
            return "deny", "Questions cannot be answered from the chat yet; continue with your best judgement."
        approval_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._approvals[approval_id] = (turn.job_id, future)
        expires_at = self.clock() + turn.approval_timeout_s
        await self._send(turn.job_id, "approval_request", {
            "turn_id": turn.turn_id, "approval_id": approval_id, "tool": tool,
            "input_preview": input_preview(tool, tool_input), "expires_at": expires_at,
        })
        try:
            decision = await asyncio.wait_for(future, timeout=turn.approval_timeout_s)
        except TimeoutError:
            await self._send(turn.job_id, "approval_resolved", {"approval_id": approval_id, "outcome": "timed_out"})
            minutes = max(1, round(turn.approval_timeout_s / 60))
            return "deny", f"No decision within {minutes} min; denied."
        finally:
            self._approvals.pop(approval_id, None)
        if decision == "allowed":
            return "allow", ""
        if decision == "allowed_job_edits":
            return "allow_job_edits", ""
        return "deny", "Denied by the owner in the chat."
