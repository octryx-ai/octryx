"""``documentation.sync_published_version``: make sure the published documentation page is in Knowledge, and prove it.

The run's requester runs the Workspace's confirmed Confluence Knowledge source (the Source Sync's own
``run_connector``, a full pass of its scope, under the requester's Knowledge author rights). ``run_connector``
commits on its own, so it never runs inside the run's transaction (``external_step``): the step leases its pass,
commits (the claim ends explicitly), runs the sync in its own session, then re-claims the run only if status, node,
entry, lease and the publication are unchanged — else ``run_moved_on`` and nothing is recorded.

The published facts come from the run's approved, sent-confirmed write intent, never from a sync marker. After the
sync the page is read **once more at exactly the published version** through the bounded legacy-view profile
(``sources/sync/confluence.py``, ``ConfluenceConnector.fetch_pinned_view``) on the very connection the sync reads
the space with — pinned to the intent's instance and connection. A different version refuses and relists
(``index_timeout``); a malformed answer or bytes that are not the ingested revision refuse as ``parse_failed``. Four
separate digests are recorded and compared only within their own representation:

- ``storage_digest``: the publication's read-back ``body.storage`` (from the intent);
- ``view_raw_digest``: ``body.view`` as fetched at the pinned version;
- ``document_html_digest``: the generated HTML document (title + canonical link + view), equal to the projected
  revision's ``content_sha256``;
- ``index_refs_digest``: the projected revision id and its span keys.

The proof summary lives in ``run.context.documentation.provenance``. The search-hit ``version`` is a product
version and is never called the page version (``page_version`` always comes from the intent).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun
from ....models.project.knowledge_source_sync import KnowledgeSourceConnector
from ....time_utils import utc_now
from ....tools._confluence_instance import confluence_instance
from ...project.service import get_project_config
from ..platform.dispatch import (
    CLASS_INVALID,
    CLASS_NOT_CONFIGURED,
    CLASS_PERMISSION,
    CLASS_SAFETY,
    FAILED,
    SUCCEEDED,
    ToolOutcome,
)
from ..records import record_event
from .knowledge_proof import (
    BINDING_HEAD,
    CLASS_INDEX_TIMEOUT,
    CLASS_PARSE_FAILED,
    REASON_SOURCE_CONNECTION,
    REASON_SOURCE_INSTANCE,
    BindingRefusedError,
    as_digest,
    binding_class,
    ledger_binding,
    publication_pin,
    publication_source_refusal,
    published_intent,
)
from .page import DocumentationSettings, documentation_settings
from .publish import DOCUMENTATION_KEY

EVENT_PROVENANCE = "documentation_provenance_pinned"
EVENT_PROVENANCE_REFUSED = "documentation_provenance_refused"
PROVENANCE_KEY = "provenance"


def evidence_runtime():
    """The Knowledge runtime the sync runs on (a seam: tests pass the stub runtime)."""
    from ...knowledge.runtime import get_evidence_runtime

    return get_evidence_runtime()


def sync_transport():
    """The source transport (``None`` = the governed egress; a seam for the acceptance stub)."""
    return None


def _covers(row: KnowledgeSourceConnector, settings: DocumentationSettings) -> bool:
    scope = dict(row.scope or {})
    if settings.space_key in {str(item).upper() for item in scope.get("spaces") or []}:
        return True
    return any(isinstance(tree, dict) and str(tree.get("space_key") or "").upper() == settings.space_key
               and settings.parent_page_id and str(tree.get("root_page_id") or "") == settings.parent_page_id
               for tree in scope.get("page_trees") or [])


def source_sync_session():
    """The Source Sync's own session: its commits never touch the run's transaction. A seam: the test
    harness shares its single-connection session."""
    from ....db.core import async_session_factory

    return async_session_factory()


async def _run_source(db: AsyncSession, run: WorkflowRun, row: KnowledgeSourceConnector,
                      page: dict[str, Any]) -> str:
    """The sync run's state, or a fixed refusal reason. Runs in its own session (``db`` is not used for writes).

    ``page``: the published page facts the publication pin reads."""
    from app.services.knowledge.sources.sync.service_run import run_connector

    from ...knowledge.access.authorization import WorkspaceWriteForbiddenError, authorize_workspace
    from ...knowledge.ledger.errors import EvidenceLedgerError
    from ...knowledge.sources.sync.runner import SyncRefusedError

    del db
    async with source_sync_session() as sync_db:
        requester = await sync_db.get(User, run.requested_by)
        source = await sync_db.get(KnowledgeSourceConnector, row.id)
        if requester is None or source is None:
            return "source_unavailable"
        try:
            authorized = await authorize_workspace(sync_db, current_user=requester, workspace_id=run.project_id,
                                                   require_author=True)
        except (WorkspaceWriteForbiddenError, EvidenceLedgerError):
            return "requester_not_knowledge_author"
        try:
            # The run reads the page's instance and connection or nothing: pinned where its connections are fixed.
            sync = await run_connector(sync_db, runtime=evidence_runtime(), authorized=authorized, row=source,
                                       actor_id=requester.id, transport=sync_transport(), pin=publication_pin(page))
        except SyncRefusedError as error:
            return str(error.reason)
        await sync_db.commit()
        # A refused run names its reason (the publication pin), else its state.
        return str(sync.reason or sync.state) if sync.state == "needs_configuration" else str(sync.state)


# --- Publish & prove: sync_published_version ----------------------------------------------------------------------


def _intent_page(intent, space_key: str) -> dict[str, Any]:
    return {"page_id": str(intent.result_page_id or ""), "version": intent.result_version,
            "instance": str(intent.instance or ""), "connection_id": str(intent.connection_id or ""),
            "space_key": space_key, "parent_id": intent.parent_id}


def _intent_facts(intent) -> dict[str, Any]:
    if intent is None:
        return {"intent_id": None, "page_id": None, "page_version": None}
    return {"intent_id": intent.id, "page_id": intent.result_page_id, "page_version": intent.result_version}


async def _pinned_reader(db: AsyncSession, row: KnowledgeSourceConnector, page: dict[str, Any]):
    """``(connector, "")`` bound to the connection the source reads the page's space with, pinned to the intent's
    instance and connection; ``(None, refusal)`` otherwise. Reads the database only (no request)."""
    from ...knowledge.sources.sync.confluence import ConfluenceConnector
    from ...knowledge.sources.sync.contract import ConnectorError
    from ...knowledge.sources.sync.provenance import scope_connection
    from ...knowledge.sources.sync.scope_connections import resolve_scope_connections
    from ...named_connections.contract import DEFAULT_CONNECTION_NAME

    space = str(page.get("space_key") or "").upper()
    try:
        scoped = await resolve_scope_connections(db, kind=row.kind, project_id=row.project_id,
                                                 scope=dict(row.scope or {}), connection_id=row.connection_id)
    except ConnectorError as error:
        return None, f"the Knowledge source has no usable connection ({error.reason})"
    connection = scope_connection(scoped, space)
    ref = next((ref for key, ref in scoped.by_key.items() if str(key).upper() == space), None)
    if ref is None and len(set(scoped.by_key.values()) or set(scoped.connections)) == 1:
        ref = next(iter(set(scoped.by_key.values()) or set(scoped.connections)), DEFAULT_CONNECTION_NAME)
    if connection is None:
        return None, f"no connection of the Knowledge source serves the space {space}"
    if confluence_instance(connection.base_url) != page["instance"]:
        return None, f"the Knowledge source reads {space} from another instance than {page['instance']}"
    if str(ref or "") != page["connection_id"]:
        return None, f"the Knowledge source reads {space} through connection {ref}, not the published " \
                     f"{page['connection_id']}"
    return ConfluenceConnector(connection, spaces=(space,), transport=sync_transport()), ""


def _pinned_refusal(error) -> tuple[str, str, dict[str, Any]]:
    """``(failure class, reason, facts)`` of a refused pinned read."""
    from ...knowledge.sources.sync import confluence as source

    facts: dict[str, Any] = {"pinned_read": error.reason, "source_reason": error.source_reason or None}
    if error.reason == source.PINNED_REFUSED_VERSION:
        facts["fetched_version"] = error.fetched_version
        return CLASS_INDEX_TIMEOUT, "the page answered at another version than the published one", facts
    if error.reason == source.PINNED_REFUSED_INSTANCE:
        return CLASS_NOT_CONFIGURED, "the S1 source read supports Confluence Cloud (*.atlassian.net/wiki) only", facts
    if error.reason == source.PINNED_REFUSED_READ:
        if error.source_reason == "source_unauthorized":
            return CLASS_PERMISSION, "the Knowledge connection may not read the published page", facts
        if error.source_reason in ("source_unavailable", "source_rate_limited"):
            return CLASS_INDEX_TIMEOUT, "Confluence was unavailable for the pinned read", facts
        return CLASS_PARSE_FAILED, "the legacy view read is unavailable for this page (profile removal " \
                                   "dependency, or the page is gone)", facts
    return CLASS_PARSE_FAILED, "the pinned read answered outside the legacy-view profile", facts


def _refused(db: AsyncSession, run: WorkflowRun, failure_class: str, reason: str, facts: dict[str, Any]
             ) -> ToolOutcome:
    record_event(db, run, EVENT_PROVENANCE_REFUSED, node_id=run.current_node_id,
                 detail={"failure_class": failure_class, **facts})
    return ToolOutcome(FAILED, {"proven": False, **facts}, reason, failure_class=failure_class)


# The index projects an ingested revision asynchronously, seconds after the sync (~11 s). The step waits for it,
# bounded and outside the run's claim, instead of failing every first attempt with ``index_timeout``.
PROJECTION_WAIT_SECONDS = 90.0
PROJECTION_POLL_SECONDS = 2.0


async def await_projection(probe: Callable[[], Awaitable[Any]], *, timeout: float = PROJECTION_WAIT_SECONDS,
                           interval: float = PROJECTION_POLL_SECONDS,
                           sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> bool:
    """Poll ``probe`` while it refuses only because the head is not projected yet; ``True`` once it binds.

    Any other refusal ends the wait at once (``False``): the authoritative binding afterwards reports it."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            await probe()
            return True
        except BindingRefusedError as error:
            if error.reason != BINDING_HEAD or time.monotonic() >= deadline:
                return False
        await sleep(interval)


async def sync_published_version(db: AsyncSession, run: WorkflowRun, params: dict[str, Any] | None = None
                                 ) -> ToolOutcome:
    """Sync the configured source, pin the fetched version to the published one and record the four digests."""
    from app.services.knowledge.sources.sync.confluence_pinned import LEGACY_VIEW_PROFILE, PinnedViewRefusedError

    from ...knowledge.sources.sync.items import ConnectorRef
    from ..external_step import pass_key, release_for_external_work, resume_after_external_work

    del params
    intent = await published_intent(db, run)
    if intent is None or not intent.result_page_id or not intent.result_version:
        return ToolOutcome(FAILED, {}, "no approved, sent-confirmed documentation publication on this run",
                           failure_class=CLASS_INVALID)
    if not intent.result_storage_digest:
        return ToolOutcome(FAILED, {}, "the publication recorded no read-back storage digest",
                           failure_class=CLASS_INVALID)
    from ....models import WorkflowRunDecision
    from .audience_binding import audience_binding_problem
    from .knowledge_proof import CLASS_AUDIENCE_UNPROVEN

    config = await get_project_config(run.project_id, db)
    decision = await db.get(WorkflowRunDecision, intent.decision_id)
    problem = audience_binding_problem(dict(decision.payload or {}) if decision else {}, config, run.project_id)
    if problem:
        return ToolOutcome(FAILED, {}, problem, failure_class=CLASS_AUDIENCE_UNPROVEN)
    settings = documentation_settings(config)
    space = str(intent.space_key or (settings.space_key if settings is not None else "")).upper()
    page = _intent_page(intent, space)
    known = dict(dict(run.context or {}).get(DOCUMENTATION_KEY) or {})
    if known.get("page_id") and (str(known["page_id"]) != page["page_id"]
                                 or str(known.get("version")) != str(page["version"])):
        return ToolOutcome(FAILED, {"page_id": page["page_id"]}, "the run's recorded page is not the approved "
                           "publication's page/version", failure_class=CLASS_SAFETY)
    if settings is not None and space != settings.space_key:
        return ToolOutcome(FAILED, {"space_key": space}, "the publication's space is not the documentation space",
                           failure_class=CLASS_SAFETY)
    approved_source = dict(decision.payload.get("audience") or {}).get("source_key")
    row = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == run.project_id,
        KnowledgeSourceConnector.kind == "confluence",
        KnowledgeSourceConnector.connector_key == approved_source))).scalar_one_or_none()
    if row is None or settings is None or not _covers(row, settings):
        return ToolOutcome(FAILED, {}, f"the confirmed Confluence Knowledge source does not cover the documentation "
                                       f"space {space}", failure_class=CLASS_NOT_CONFIGURED)
    refused = await publication_source_refusal(db, page, row)
    if refused:
        return ToolOutcome(FAILED, {"instance": page["instance"]}, refused, failure_class=CLASS_SAFETY)
    reader, refused = await _pinned_reader(db, row, page)
    if reader is None:
        return ToolOutcome(FAILED, {"instance": page["instance"]}, refused, failure_class=CLASS_SAFETY)
    ref = ConnectorRef.of(row)
    held = await release_for_external_work(db, run, key=pass_key(run), facts=_intent_facts(intent))
    state = await _run_source(db, run, row, page=page)
    view, refusal = None, None
    try:
        view = await reader.fetch_pinned_view(page["page_id"], version=int(page["version"]))
    except PinnedViewRefusedError as error:
        refusal = error
    if refusal is None and state not in (REASON_SOURCE_INSTANCE, REASON_SOURCE_CONNECTION,
                                         "requester_not_knowledge_author"):
        project_id = run.project_id

        async def probe() -> None:
            async with source_sync_session() as probe_db:  # read-only, fresh: sees the projector's latest commit
                await ledger_binding(probe_db, connector_id=ref.id, project_id=project_id, page_id=page["page_id"],
                                     page_version=int(page["version"]), instance=page["instance"])

        await await_projection(probe)
    await resume_after_external_work(db, run, held, _intent_facts(await published_intent(db, run)))
    facts: dict[str, Any] = {"profile": LEGACY_VIEW_PROFILE["id"], "intent_id": intent.id,
                             "connector_key": ref.connector_key, "sync_state": state, "page_id": page["page_id"],
                             "page_version": int(page["version"]), "instance": page["instance"],
                             "connection_id": page["connection_id"]}
    if state in (REASON_SOURCE_INSTANCE, REASON_SOURCE_CONNECTION):
        return _refused(db, run, CLASS_SAFETY, f"the Knowledge source no longer reads {page['instance']}", facts)
    if state == "requester_not_knowledge_author":
        return _refused(db, run, CLASS_PERMISSION, "the requester may not run this Workspace's Knowledge sync", facts)
    if refusal is not None:
        failure_class, reason, more = _pinned_refusal(refusal)
        return _refused(db, run, failure_class, reason, {**facts, **more})
    current_source = await db.get(KnowledgeSourceConnector, ref.id, populate_existing=True)
    if current_source is None or await publication_source_refusal(db, page, current_source):
        return _refused(db, run, CLASS_SAFETY, "the Knowledge serving connection changed during sync", facts)
    facts["fetched_version"] = view.version
    try:
        binding = await ledger_binding(db, connector_id=ref.id, project_id=run.project_id, page_id=page["page_id"],
                                       page_version=int(page["version"]), instance=page["instance"])
    except BindingRefusedError as error:
        return _refused(db, run, binding_class(error.reason), error.detail, {**facts, "ledger": error.reason})
    if as_digest(view.document_sha256) != binding.revision_digest:
        return _refused(db, run, CLASS_PARSE_FAILED, "the ingested revision is not the generated document of the "
                        f"published version {page['version']}", {**facts, "ledger": "document_digest_mismatch"})
    provenance = {
        **facts, "proven": True, "space_key": space, "card_hash": intent.card_hash,
        "operation_id": intent.operation_id, "source_key": binding.source_key, "source_id": binding.source_id,
        "revision_id": binding.revision_id, "read_base": confluence_instance(view.read_base),
        "digests": {"storage_digest": as_digest(intent.result_storage_digest),
                    "view_raw_digest": view.view_raw_digest,
                    "document_html_digest": view.document_digest,
                    "index_refs_digest": binding.index_refs_digest},
        "index_refs": {"revision_id": binding.revision_id, "span_count": len(binding.span_keys)},
        "at": utc_now().isoformat(),
    }
    documentation = dict(dict(run.context or {}).get(DOCUMENTATION_KEY) or {})
    run.context = {**dict(run.context or {}), DOCUMENTATION_KEY: {**documentation, PROVENANCE_KEY: provenance}}
    record_event(db, run, EVENT_PROVENANCE, node_id=run.current_node_id, detail=provenance)
    return ToolOutcome(SUCCEEDED, provenance)
