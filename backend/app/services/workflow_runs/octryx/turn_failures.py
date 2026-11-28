"""A failed or unfinished continuation turn: retry a temporary failure, wait for a busy device, or pause the run."""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ..records import main_session_id, record_event
from .continuation_marker import (
    BUSY_SINCE_KEY,
    FRESH_KEY,
    STATE_PENDING,
    _current_pass_started,
    _device_target,
    _marker,
    _set_marker,
)
from .phase_sessions import _remember_phase_session

CODE_SEAT_LIMIT = "device_turn_usage_limit"


def failed_turn_explanation(failure: str, said: str, *, rejected: bool = False) -> tuple[str, str]:
    words = " ".join(str(said or "").split())[:240]
    if rejected:
        code = f"device_turn_{failure}"[:80]
        hint = (" The device could not reach the platform, also when the turn was offered again: check that the "
                "platform is reachable from the device." if is_transient_rejection(failure) else "")
        return code, (f"The device could not start the turn of this phase ({code}).{hint} Continue to run the phase "
                      "again, or abort the run.")
    from ...devices.seat_quota import is_limit_failure

    if is_limit_failure(failure, words):
        said_part = f'"{words}"' if words else f"({failure})"
        return CODE_SEAT_LIMIT, (f"The seat account on the device reached its usage limit: {said_part}. Change the "
                                 "runtime to governed (the Workspace's models) to go on now, or continue after the "
                                 "reset.")
    code = f"device_turn_{failure}"[:80]
    said_part = f' The device said: "{words}".' if words else ""
    return code, (f"The device turn of this phase ended without finishing it ({code}).{said_part} "
                  "Continue to run the phase again, or abort the run.")


# A platform deploy's 503, the gateway's 5xx and timeouts pass by themselves and must not pause the run for a person.
_TRANSIENT = re.compile(
    r"api[ _]error[:_\s]*5\d\d|no available server|overloaded|"
    r"timed?[ _-]?out|timeout|bad gateway|service unavailable|gateway timeout|connection (?:error|reset|refused)|"
    r"econnreset|econnrefused|socket hang up|"
    # A launcher restart or a stalled turn runs once more by itself and resumes its session; a second failure pauses.
    r"service_restarted|turn_stalled", re.IGNORECASE)
ATTEMPT_RETRY = "retry"
EVENT_TRANSIENT_RETRY = "device_turn_retry"


#: The wait before the one automatic retry; the device's channel checks waiting runs every 30 s
#: (``devices.jobs_channel.RESUME_CHECK_SECONDS``), so the turn starts again within about a minute.
TRANSIENT_RETRY_AFTER_SECONDS = 20


def is_transient_failure(failure: str, said: str) -> bool:
    # A usage limit is never transient: it has its own handling.
    if failed_turn_explanation(failure, said)[0] == CODE_SEAT_LIMIT:
        return False
    return bool(_TRANSIENT.search(f"{failure or ''} {said or ''}"))


# The launcher's refusals of a turn that a moment later may pass (octryx-claude ``device_session.prepare_session``:
# ``<step>_<reason>`` of a control-plane call, ``platform.call_control_plane``): the platform was unreachable or did
# not answer in time, or answered without the gateway's state header (a 5xx or a proxy: ``<step>_refused``); or the
# launcher was restarting for an update. Everything else (a folder, a profile, a policy, a missing CLI) is permanent.
_TRANSIENT_REJECTION = re.compile(
    r"(?:^|_)(?:platform_unreachable|platform_connect_failed|unreachable|timed_out|timeout)$|"
    r"^(?:workspace_preparation|registration|client_policy|hook_key)_refused$|^device_(?:updating|restarted)$")
ATTEMPT_REOFFER = "reoffer"


def is_transient_rejection(reason: str) -> bool:
    return bool(_TRANSIENT_REJECTION.search(str(reason or "")))


async def _retry_after_transient_failure(db: AsyncSession, run: WorkflowRun, failure: str, said: str, *,
                                         rejected: bool = False) -> bool:
    from datetime import timedelta

    from ....time_utils import utc_now
    from ..runtime_target.device_wait import REASON_MODEL_RETRY, REASON_PLATFORM_RETRY, wait_for_device

    marker = _marker(run)
    transient = is_transient_rejection(failure) if rejected else is_transient_failure(failure, said)
    if not _current_pass_started(run, marker) or marker.get("retried") or not transient:
        return False
    await _remember_phase_session(db, run)
    words = " ".join(str(said or "").split())[:200]
    # The retry resumes the session the pass started (a pass a person restarted fresh included).
    _set_marker(run, {**{key: value for key, value in marker.items() if key != FRESH_KEY}, "state": STATE_PENDING,
                      "attempt": ATTEMPT_REOFFER if rejected else ATTEMPT_RETRY, "retried": True})
    record_event(db, run, EVENT_TRANSIENT_RETRY, node_id=run.current_node_id,
                 detail={"failure": str(failure or "")[:80], "said": words, **({"rejected": True} if rejected else {})})
    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    wait_for_device(db, run, node_id=str(run.current_node_id),
                    reason=REASON_PLATFORM_RETRY if rejected else REASON_MODEL_RETRY,
                    thread_target=_device_target(thread),
                    retry_after=(utc_now() + timedelta(seconds=TRANSIENT_RETRY_AFTER_SECONDS)).isoformat())
    return True


async def _wait_while_device_busy(db: AsyncSession, run: WorkflowRun, failure: str) -> bool:
    from datetime import timedelta

    from ....time_utils import utc_now
    from ...devices import busy_wait
    from ..limits import pause_run
    from ..runtime_target.device_wait import wait_for_device
    from ..states import PAUSE_RUNTIME_FAILED

    marker = _marker(run)
    if not busy_wait.is_busy(failure) or not _current_pass_started(run, marker):
        return False
    since = marker.get(BUSY_SINCE_KEY) or utc_now().isoformat()
    waited = busy_wait.waited_seconds(since)
    if busy_wait.saturated(waited):
        busy_wait.observe("phase", "saturated", waited)
        _set_marker(run, None)
        await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
            "message": busy_wait.saturated_message(waited), "code": busy_wait.CODE_SATURATED,
            "resume": {"kind": "restart", "node_id": run.current_node_id}})
        return True
    await _remember_phase_session(db, run)
    _set_marker(run, {**marker, "state": STATE_PENDING, "attempt": ATTEMPT_REOFFER, BUSY_SINCE_KEY: since})
    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    wait_for_device(db, run, node_id=str(run.current_node_id), reason=busy_wait.REASON,
                    thread_target=_device_target(thread),
                    retry_after=(utc_now() + timedelta(seconds=busy_wait.RETRY_SECONDS)).isoformat())
    return True


CODE_PHASE_NOT_FINISHED = "phase_not_finished"


async def _pause_unfinished_phase_turn(db: AsyncSession, run: WorkflowRun, said: str) -> None:
    from ..limits import pause_run
    from ..states import PAUSE_RUNTIME_FAILED

    if not _current_pass_started(run, _marker(run)):
        return
    words = " ".join(str(said or "").split())[:400]
    _set_marker(run, None)
    from .same_pass import keep_delta, resume
    from .stop_stall import STALL_KEY

    node_id = str(run.current_node_id or "")
    stall = dict(dict(run.context or {}).get(STALL_KEY) or {})
    keep_delta(run, node_id, str(stall.get("missing") or "") if stall.get("node_id") == node_id else "")
    from .same_pass import continue_unfinished

    if await continue_unfinished(db, run, node_id):
        return
    from ..binding import failed_checks, failed_checks_text

    # The pause names the check that failed (not just "its checks did not pass").
    failed = failed_checks(dict(dict(run.gate_results or {}).get(node_id) or {}).get("results") or [])
    await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
        "message": (f"The agent ended its turn without finishing this phase ({failed_checks_text(failed)})."
                    + (f' It said: "{words}".' if words else "")
                    + " Run the phase again, change the workflow's rules, or abort the run."),
        "code": CODE_PHASE_NOT_FINISHED, "resume": resume(node_id), "failed_checks": failed,
    })


async def _pause_failed_phase_turn(db: AsyncSession, run: WorkflowRun, failure: str, said: str = "", *,
                                   rejected: bool = False) -> None:
    from ..limits import pause_run
    from ..states import PAUSE_RUNTIME_FAILED

    if not _current_pass_started(run, _marker(run)):
        return  # the run moved on while the claim was taken
    code, message = failed_turn_explanation(failure, said, rejected=rejected)
    _set_marker(run, None)
    await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
        "message": message, "code": code, "resume": {"kind": "restart", "node_id": run.current_node_id},
    })
