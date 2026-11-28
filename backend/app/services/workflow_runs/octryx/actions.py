"""``workflow_action_request``: Jira, pull request and CI on the server for an octryx-claude session."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..platform.catalog import ACTIONS, validate_action_config
from ..records import lock_run, record_event
from ..states import EVENT_ACTION, STATUS_RUNNING
from .contract import contract_summary, run_contract

_RANK = {"read_only": 0, "change": 1, "deliver": 2}
MAX_RESULT_KEYS = 12


def _bounded(result: dict[str, Any]) -> dict[str, Any]:
    keep = {}
    for key in list(result)[:MAX_RESULT_KEYS]:
        value = result[key]
        if isinstance(value, str | int | float | bool) or value is None:
            keep[str(key)[:60]] = value if not isinstance(value, str) else value[:500]
    return keep


async def request_action(db: AsyncSession, run: WorkflowRun, *, action: str, params: Any,
                         principal: Any = None, session: Any = None) -> dict[str, Any]:
    from ..platform.dispatch import APPROVAL_PENDING
    from ..platform_actions import typed_action

    params = dict(params) if isinstance(params, dict) else {}
    spec = ACTIONS.get(str(action or "").strip())
    if spec is None or not spec.requestable:
        return {"state": "invalid_request", "reason": "unknown_action",
                "actions": sorted(key for key, item in ACTIONS.items() if item.requestable)}
    errors = validate_action_config("request", {"action": spec.key, "params": params})
    if errors:
        return {"state": "invalid_request", "reason": errors[0]["code"], "message": errors[0]["message"]}
    run = await lock_run(db, run)
    contract = await run_contract(db, run, principal=principal, session=session)
    phase = contract.get("phase")
    if run.status != STATUS_RUNNING or phase is None:
        return {"state": "denied", "reason": "run_not_at_phase", "message": contract_summary(contract)}
    if _RANK.get(spec.capability_class, 9) > _RANK.get(str(phase["capability_class"]), -1):
        return {"state": "denied", "reason": "phase_class_too_low",
                "message": f"{spec.key} needs a {spec.capability_class} phase; '{phase['title']}' is "
                           f"{phase['capability_class']}."}
    digest = sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]
    key = f"request:{run.current_node_id}#{dict(run.node_state or {}).get('entry')}:{spec.key}:{digest}"
    ledger = dict(dict(run.context or {}).get("action_ledger") or {})
    if key in ledger:
        return {**ledger[key], "replayed": True}
    outcome, route = await typed_action(db, run, spec.key, params)
    if outcome.state == APPROVAL_PENDING:
        return {"state": "approval_pending", "approval_id": outcome.approval_id, "decide_in": contract.get("link"),
                "message": "The platform holds this action for your approval; allow it there, then ask again."}
    answer = {"state": route, "reason": outcome.reason or None, "result": _bounded(dict(outcome.result or {}))}
    run.context = {**dict(run.context or {}), "action_ledger": {**ledger, key: answer}}
    record_event(db, run, EVENT_ACTION, node_id=run.current_node_id,
                 detail={"action": spec.key, "result": route, "requested_by": "octryx_claude"})
    return answer


__all__ = ["request_action"]
