"""The device channel's job layer: deliver turns, stops and decisions; store and publish device events."""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, DeviceJobApproval, UserDevice
from ...time_utils import utc_now
from ..session.stream import session_stream_manager
from .channel_protocol import RESULT_DUPLICATE, RESULT_STORED, ChannelHandlers, DeviceChannelConnection
from .job_approvals import expire_due_approvals
from .job_events import apply_event, store_event
from .job_files import FILE_MESSAGE_TYPES, FileTransfers
from .job_files import deliver_pending as deliver_pending_files
from .job_offer import offer_body
from .job_recovery import REASON_TURN_STALLED, fail_stalled_turns
from .job_state import ACTIVE_STATUSES, OPEN_STATUSES, serialize_approval, serialize_job
from .live_device import deliver_pending, handle_device_message
from .live_values import LIVE_MESSAGE_TYPES
from .local_sessions import MESSAGE_TYPE as LOCAL_SESSIONS_MESSAGE
from .local_sessions import apply_report as apply_local_report
from .runner_queue import claim_waiting
from .tool_jobs import MESSAGE_TYPES as TOOL_JOB_MESSAGE_TYPES
from .tool_jobs import apply_message as apply_tool_job
from .tool_jobs import deliver as deliver_tool_jobs

logger = logging.getLogger(__name__)

STALL_CHECK_SECONDS = 30.0
# Runs waiting for a device (``waiting_for_device``) are checked at its first tick and then this often.
RESUME_CHECK_SECONDS = 30.0
EVENT_TYPE = "device_job_event"
JOB_MESSAGE_TYPES = frozenset({"job_accepted", "job_rejected", "job_event", "approval_request", "approval_resolved",
                               "turn_finished", "job_failed"})



async def _with_remedy(db: AsyncSession, body: dict[str, Any]) -> dict[str, Any]:
    tool_use_id = str(body.get("tool_use_id") or "")[:64]
    if body.get("kind") != "tool_result" or body.get("is_error") is not True or not tool_use_id:
        return body
    from ...models import ToolCall
    from ..agent_gateway.contract import TOOL_CALL_STATUS_DENIED

    row = (await db.execute(select(ToolCall).where(
        ToolCall.status == TOOL_CALL_STATUS_DENIED,
        ToolCall.parameters["tool_use_id"].as_string() == tool_use_id,
    ).order_by(ToolCall.created_at.desc()).limit(1))).scalar_one_or_none()
    remedy = (row.result or {}).get("remedy") if row is not None and isinstance(row.result, dict) else None
    return {**body, "remedy": dict(remedy)} if isinstance(remedy, dict) else body


async def _thread_run(db, job) -> dict[str, Any]:
    from ...models import Session
    from ..workflow_runs.octryx.browser import phase_allows_browser
    from ..workflow_runs.octryx.context_pack import context_pack_request
    from ..workflow_runs.octryx.local_decisions import local_decisions_offer
    from ..workflow_runs.octryx.research import research_min_sources
    from ..workflow_runs.octryx.subagents import node_allows_subagents, turn_phase
    from ..workflow_runs.records import active_run_for_session
    from ..workflow_runs.review.seat import is_review_thread

    if is_review_thread(await db.get(Session, job.session_id)):
        # The independent reviewer's seat call: bound to no run, no sub-agents, browser or tools of a phase.
        return {"workflow_run_id": None, "review_call": True}
    run = await active_run_for_session(db, job.session_id)
    phase = await turn_phase(db, run)
    research = bool(await research_min_sources(db, run, phase))
    defaults = await _tool_defaults(db, job.workspace_id)
    from ..workflow_runs.octryx.compaction import window
    from ..workflow_runs.octryx.turn_tools import builtin_tools, device_session_prompts, device_system_prompt

    tools = builtin_tools(run, phase)  # the phase's or its size class's built-in tools (data), else the default
    compact = window(run)  # Claude Code compacts there itself (``octryx.compaction``)
    return {"workflow_run_id": run.id if run is not None else None,
            **({"builtin_tools": tools} if tools else {}),
            **({"compact_window": compact} if compact else {}),
            "system_prompt": await device_system_prompt(db, run),
            **await device_session_prompts(db, run),
            "subagents": node_allows_subagents(phase), "browser": await phase_allows_browser(db, run, phase),
            "local_decisions": await local_decisions_offer(db, run, phase, job.owner_user_id),
            "web": defaults["web_tools"] == "all" or (defaults["web_tools"] == "research_only" and research),
            "browser_external": defaults["browser"] == "read_external",
            "context_pack": await context_pack_request(db, run, phase, job.session_id)}


async def _context_window(db, job) -> int:
    # The turn model's context window, for engines that do not know a gateway alias (the chat's context meter).
    from ...models import LLMModel

    model = job.turn_model or job.model
    if not model:
        return 0
    length = (await db.execute(select(LLMModel.context_length).where(LLMModel.model_id == model)
                               .limit(1))).scalar_one_or_none()
    return int(length or 0)


async def _tool_defaults(db, workspace_id: str | None) -> dict[str, Any]:
    from ..agent_gateway.policy import load_workspace_policy
    from .device_runs_keys import device_runs_section, tool_defaults

    loaded = await load_workspace_policy(db, workspace_id) if workspace_id else None
    raw = loaded.policy.raw if loaded is not None and loaded.policy is not None else {}
    return tool_defaults(device_runs_section(raw))

async def job_limits(db: AsyncSession, job: DeviceJob) -> dict[str, Any]:
    from ..agent_gateway.local_models import permissive_only
    from .workspace_policy import workspace_device_limits

    limits = await workspace_device_limits(db, job.workspace_id)
    return {**limits, "local_models_permissive_only": await permissive_only(db)}


async def publish(job: DeviceJob, payload: dict[str, Any], *, device_name: str = "") -> None:
    await session_stream_manager.publish(job.session_id, EVENT_TYPE,
                                         {"job": serialize_job(job, device_name=device_name), **payload})


class DeviceJobHandlers(ChannelHandlers):
    def __init__(self, *, clock: Any = time.monotonic) -> None:
        self.clock = clock
        self._stall_checked: dict[str, float] = {}
        self._resume_checked: dict[str, tuple[Any, float]] = {}
        self._files = FileTransfers()

    async def _stalled(self, db: AsyncSession, device_id: str) -> None:
        now = self.clock()
        if now - self._stall_checked.get(device_id, float("-inf")) < STALL_CHECK_SECONDS:
            return
        self._stall_checked[device_id] = now
        for job in await fail_stalled_turns(db, device_id=device_id):
            await publish(job, {"eventType": REASON_TURN_STALLED})

    async def welcome_streams(self, db: AsyncSession, device: UserDevice) -> dict[str, int]:
        jobs = list((await db.execute(
            select(DeviceJob).where(DeviceJob.device_id == device.id, DeviceJob.status.in_(OPEN_STATUSES))
        )).scalars().all())
        for job in jobs:
            job.disconnected_at = None
            if job.turn_state == "sent":
                job.turn_state = "pending"
            if job.stop_state == "sent":
                job.stop_state = "pending"
        approvals = (await db.execute(
            select(DeviceJobApproval).join(DeviceJob, DeviceJob.id == DeviceJobApproval.job_id).where(
                DeviceJob.device_id == device.id, DeviceJobApproval.decision_state == "sent")
        )).scalars().all()
        for approval in approvals:
            approval.decision_state = "pending"
        await db.flush()
        return {job.id: int(job.last_event_seq or 0) for job in jobs}

    async def stream_event(self, db: AsyncSession, connection: DeviceChannelConnection,
                           message: dict[str, Any]) -> str | int:
        job = await db.get(DeviceJob, str(message.get("stream") or ""))
        if job is None or job.device_id != connection.device_id:
            # Not this device's job: acknowledged so the device drops it, never stored.
            logger.warning("device_channel.foreign_stream device=%s", connection.device_id)
            return RESULT_DUPLICATE
        seq = int(message["seq"])
        last = int(job.last_event_seq or 0)
        if seq <= last:
            return RESULT_DUPLICATE
        if seq != last + 1:
            return last + 1
        message_type = str(message.get("type") or "")
        if message_type not in JOB_MESSAGE_TYPES:
            await store_event(db, job, seq, "ignored", {})
            return RESULT_STORED
        body = message.get("body") if isinstance(message.get("body"), dict) else {}
        body = await _with_remedy(db, body)
        event = await store_event(db, job, seq, message_type, body)
        published = await apply_event(db, job, message_type, body, limits=await job_limits(db, job))
        device = await db.get(UserDevice, job.device_id)
        await publish(job, {"seq": seq, "eventType": message_type, "body": event.body, **published},
                      device_name=device.name if device else "")
        return RESULT_STORED

    async def message(self, db: AsyncSession, connection: DeviceChannelConnection, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "")
        if message_type in TOOL_JOB_MESSAGE_TYPES:  # a tool job's answer (``tool_jobs``)
            body = message.get("body") if isinstance(message.get("body"), dict) else {}
            await apply_tool_job(db, connection.device_id, message_type, body)
            return
        if message_type in FILE_MESSAGE_TYPES:  # a file the owner asked for (``job_files``)
            body = message.get("body") if isinstance(message.get("body"), dict) else {}
            await self._files.handle(db, connection.device_id, message_type, body)
            return
        if message_type != LOCAL_SESSIONS_MESSAGE and message_type not in LIVE_MESSAGE_TYPES:
            return
        device = await db.get(UserDevice, connection.device_id)
        if device is None:
            return
        if message_type == LOCAL_SESSIONS_MESSAGE:
            await apply_local_report(db, device, message.get("body"))
        else:
            body = message.get("body") if isinstance(message.get("body"), dict) else {}
            await handle_device_message(db, device, message_type, body)

    async def _resume_runs(self, db: AsyncSession, connection: DeviceChannelConnection) -> None:
        from ..workflow_runs.runtime_target.device_wait import resume_for_device

        now = self.clock()
        seen = self._resume_checked.get(connection.device_id)
        if seen is not None and seen[0] is connection and now - seen[1] < RESUME_CHECK_SECONDS:
            return
        self._resume_checked[connection.device_id] = (connection, now)
        try:
            await resume_for_device(db, connection.device_id)
        except Exception:  # noqa: BLE001 - a run that cannot resume never breaks the channel; the next check retries
            logger.warning("device_channel.resume_runs_failed device=%s", connection.device_id, exc_info=True)
            await db.rollback()
        from ..workflow_runs.teamwork.scheduler import advance_due

        try:
            async with db.begin_nested():  # a run that cannot advance never undoes the resumed ones
                await advance_due(db)  # teamwork items whose retry time came, or that waited for a busy device
        except Exception:  # noqa: BLE001 - same: the next check retries
            logger.warning("device_channel.teamwork_due_failed device=%s", connection.device_id, exc_info=True)

    async def tick(self, db: AsyncSession, connection: DeviceChannelConnection) -> None:
        await self._stalled(db, connection.device_id)  # first, so its cancel goes out on this tick
        await self._resume_runs(db, connection)  # a resumed run's turn is offered on this tick
        await claim_waiting(db, await db.get(UserDevice, connection.device_id))  # chat turns waiting for a runner
        jobs = list((await db.execute(
            select(DeviceJob).where(DeviceJob.device_id == connection.device_id,
                                    (DeviceJob.turn_state == "pending") | (DeviceJob.stop_state == "pending"))
        )).scalars().all())
        for job in jobs:
            if job.turn_state == "pending" and job.status in ACTIVE_STATUSES:
                from ..workflow_runs.teamwork.slots import slot_free
                from .engine_state import offer_session_state
                from .job_engine import job_engine

                await connection.send("job_offer", offer_body(job, limits=await job_limits(db, job),
                                                              **await _thread_run(db, job),
                                                              slot_exempt=await slot_free(db, job.session_id),
                                                              engine=await job_engine(db, job),
                                                              context_window=await _context_window(db, job),
                                                              session_state=await offer_session_state(db, job)))
                job.turn_state = "sent"
            if job.stop_state == "pending":
                await connection.send("cancel", {"job_id": job.id, "turn_id": job.turn_id})
                job.stop_state = "sent"
        decided = (await db.execute(
            select(DeviceJobApproval, DeviceJob).join(DeviceJob, DeviceJob.id == DeviceJobApproval.job_id).where(
                DeviceJob.device_id == connection.device_id, DeviceJobApproval.decision_state == "pending")
        )).all()
        for approval, job in decided:
            await connection.send("approval_decision", {"job_id": job.id, "approval_id": approval.request_id,
                                                        "decision": approval.status})
            approval.decision_state = "sent"
        await deliver_pending(db, connection)
        await deliver_pending_files(db, connection)
        await deliver_tool_jobs(db, connection)
        for approval in await expire_due_approvals(db, device_id=connection.device_id):
            job = await db.get(DeviceJob, approval.job_id)
            await publish(job, {"eventType": "approval_expired", "approval": serialize_approval(approval)})
        await db.flush()

    async def disconnected(self, db: AsyncSession, device_id: str) -> None:
        jobs = (await db.execute(
            select(DeviceJob).where(DeviceJob.device_id == device_id, DeviceJob.status.in_(ACTIVE_STATUSES))
        )).scalars().all()
        for job in jobs:
            job.disconnected_at = job.disconnected_at or utc_now()
        await db.flush()


__all__ = ["DeviceJobHandlers", "EVENT_TYPE", "job_limits", "publish"]
