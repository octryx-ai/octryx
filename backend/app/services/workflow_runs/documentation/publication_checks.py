"""Publish & prove checks: the approved body, dispatch stop/drift, pre-send reads and the read-back proof."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkflowRunDecision
from ....time_utils import utc_now
from ....tools._confluence_storage import normalize_storage_content
from ...ai_marking import facts_from_dict, with_storage_marker
from ...project.service import get_project_config
from ..graph import CONFIRMED
from .decision_authority import publication_decision_problem
from .page import documentation_settings
from .target import MODE_CREATE


def _version_message(intent: Any) -> str:
    return f"Octryx publication {intent.operation_id}"


# AI output marking (EU AI Act Art. 50(2)): the marker facts are decided once per send and frozen in the
# intent's ``dispatch_check`` (``ai_marking``). Every later comparison (reply, read-back, reconcile, verify)
# rebuilds the sent body from the approved body plus exactly those frozen facts, so the digests compare the
# body as sent and a re-check never reports a false change. An intent sent without facts stays unmarked.
def _frozen_facts(intent: Any) -> Any:
    return facts_from_dict(dict(intent.dispatch_check or {}).get("ai_marking"))


def _sent_body(intent: Any, body: str) -> str:
    return with_storage_marker(body, _frozen_facts(intent))


def _location(intent: Any, page_id: str, url: str) -> dict[str, Any]:
    return {"instance": intent.instance, "connection_id": intent.connection_id, "space_id": intent.space_id,
            "space_key": intent.space_key, "parent_id": intent.parent_id, "page_id": page_id, "url": url}


async def _approved_body(db: AsyncSession, run: WorkflowRun, intent: Any) -> tuple[str, str]:
    """``(body as sent, '')`` from the approving (b) decision, or ``('', why it does not bind)``."""
    from .write_intent import PUBLICATION_SUBJECT, confirmed_binding_problem

    decision = await db.get(WorkflowRunDecision, intent.decision_id) if intent.decision_id else None
    if (decision is None or decision.run_id != run.id or decision.subject != PUBLICATION_SUBJECT
            or decision.action != CONFIRMED or decision.kind != "confirmation"):
        return "", "the intent's approval is not this run's confirmed publication decision"
    authority_problem = await publication_decision_problem(db, run, decision)
    if authority_problem:
        return "", authority_problem
    payload = dict(decision.payload or {})
    body = payload.get("body")
    if not decision.payload_hash or decision.payload_hash != intent.card_hash:
        return "", "the confirmed card is not the approved card hash"
    problem = confirmed_binding_problem(intent, payload, output_hash=intent.output_hash, body_hash=intent.body_hash,
                                        workspace_id=run.project_id)
    if problem:
        return "", problem
    return normalize_storage_content(body), ""


async def _dispatch_check(db: AsyncSession, run: WorkflowRun, intent: Any, key: str
                          ) -> tuple[dict[str, Any], str, list[str], Any]:
    """``(record, stop reason, drift, served connection)``: stop and drift at dispatch."""
    from ..states import STATUS_RUNNING
    from .target import ConnectionUnavailableError, served_confluence
    from .write_intent import latest_publication_decision

    stopped = ""
    if run.status != STATUS_RUNNING:
        stopped = f"the run is {run.status}"
    latest = await latest_publication_decision(db, run)
    if not stopped and (latest is None or latest.id != intent.decision_id):
        stopped = (f"the latest publication decision is '{latest.action}', not the approval of this intent"
                   if latest is not None else "no publication decision approves this intent")
    drift: list[str] = []
    config = await get_project_config(run.project_id, db)
    from .audience_binding import audience_binding_problem

    audience_problem = audience_binding_problem(dict(latest.payload or {}) if latest else {}, config,
                                               run.project_id)
    if audience_problem:
        drift.append(audience_problem)
    settings = documentation_settings(config)
    if settings is None or settings.space_key != intent.space_key:
        drift.append(f"space_key: {intent.space_key!r} → {settings.space_key if settings else None!r}")
    elif intent.operation == MODE_CREATE and (settings.parent_page_id or None) != (intent.parent_id or None):
        drift.append(f"parent_page_id: {intent.parent_id!r} → {settings.parent_page_id or None!r}")
    served = None
    try:
        served = await served_confluence(db, run, intent.space_key)
    except ConnectionUnavailableError as error:
        drift.append(f"connection: {error.code}")
    else:
        from .target import _space_allowed

        if not _space_allowed(served.config, intent.space_key):
            drift.append("the confirmed space is no longer allowed on the serving connection")
        if served.connection_id != intent.connection_id:
            drift.append(f"connection_id: {intent.connection_id!r} → {served.connection_id!r}")
        if served.instance != intent.instance:
            drift.append(f"instance: {intent.instance!r} → {served.instance!r}")
    record = {"pass_key": key, "checked_at": utc_now().isoformat(), "run_status": run.status,
              "run_state_version": int(run.state_version or 0), "decision_id": intent.decision_id,
              "latest_decision_id": latest.id if latest is not None else None, "stopped": stopped or None,
              "drift": drift}
    return record, stopped, drift, served


async def _presend_problems(client: Any, intent: Any) -> list[tuple[str, str]]:
    """Read-only checks of the pinned space, parent and base version right before the send."""
    from .confluence_v2 import STATUS_CURRENT
    from .failure_routes import PAGE_CHANGED, TARGET_DRIFT

    space = await client.get_space(intent.space_id)
    if space.key.upper() != str(intent.space_key or "").upper():  # Confluence keys match without case
        return [(TARGET_DRIFT, f"space {intent.space_id} is now {space.key}, not {intent.space_key}")]
    if intent.operation == MODE_CREATE:
        parent = await client.get_page(intent.parent_id, storage=False)
        if parent.space_id != intent.space_id or parent.status != STATUS_CURRENT:
            return [(TARGET_DRIFT, f"the parent page {intent.parent_id} is no longer a current page in "
                                   f"{intent.space_key}")]
        return []
    page = await client.get_page(intent.page_id, storage=False)
    if page.space_id != intent.space_id or page.status != STATUS_CURRENT or page.parent_id != intent.parent_id:
        return [(TARGET_DRIFT, f"page {intent.page_id} moved or is no longer current")]
    if page.version != intent.base_version:
        return [(PAGE_CHANGED, f"page {intent.page_id} is at version {page.version}, not the confirmed "
                               f"{intent.base_version}")]
    return []


def _content_match(storage: str | None, body: str, *extra: str | None) -> str:
    """``exact`` / ``canonical`` when the stored body is the approved body, else ``''``."""
    from .confluence_v2_storage import canonical_digest, storage_digest

    if storage is None:
        return ""
    if storage_digest(storage) == storage_digest(body):
        return "exact"
    return "canonical" if canonical_digest(storage) == canonical_digest(body) else ""


def _head_problem(intent: Any, page: Any, body: str, *extra: str | None) -> tuple[str, str]:
    """``(class, why)`` when the current page does not prove the approved write at the expected version."""
    from .confluence_v2 import STATUS_CURRENT
    from .failure_routes import PAGE_CHANGED, PUBLISH_UNVERIFIED, TARGET_DRIFT

    if page.space_id != intent.space_id or page.parent_id != intent.parent_id or page.status != STATUS_CURRENT:
        return TARGET_DRIFT, f"page {page.id} is not at the pinned location (space, parent, status current)"
    if page.version > intent.expected_version:
        return PAGE_CHANGED, f"page {page.id} moved on to version {page.version} after this write"
    if page.version < intent.expected_version:
        return PUBLISH_UNVERIFIED, f"page {page.id} reads version {page.version}, not {intent.expected_version}"
    if page.title != intent.title:
        return PUBLISH_UNVERIFIED, f"page {page.id} has another title than the approved one"
    if not _content_match(page.storage, body, *extra):
        return PUBLISH_UNVERIFIED, f"page {page.id} at version {page.version} does not hold the approved body"
    return "", ""


def _reply_problem(intent: Any, reply: Any) -> str:
    from .confluence_v2 import STATUS_CURRENT

    checks = (("version", reply.version != intent.expected_version), ("space", reply.space_id != intent.space_id),
              ("parent", reply.parent_id != intent.parent_id), ("status", reply.status != STATUS_CURRENT),
              ("title", reply.title != intent.title),
              ("page", intent.operation != MODE_CREATE and reply.id != intent.page_id))
    return ", ".join(label for label, failed in checks if failed)
