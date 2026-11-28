"""The run's confirmed publication as server-owned bindings, re-derived from the database (never from a caller)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkflowRunDecision
from ....models.project.knowledge_source_sync import KnowledgeSourceConnector
from ...project.service import get_project_config
from ..graph import CONFIRMED
from ..pause import payload_hash
from ..platform.dispatch import CLASS_INVALID, CLASS_SAFETY
from .audience_contract import CODE_BINDING, CODE_NOT_PROVEN, CODE_NOT_PUBLISHED, PROVENANCE_KEY, AudienceProofError
from .audience_query_set import derive_query_set
from .knowledge_proof import (
    CLASS_AUDIENCE_UNPROVEN,
    BindingRefusedError,
    binding_class,
    ledger_binding,
    publication_source_refusal,
    published_intent,
    sha256_json,
)
from .publish import DOCUMENTATION_KEY


@dataclass(frozen=True, slots=True)
class ConfirmedPublication:
    intent_id: str
    card_hash: str
    workspace_id: str
    connection_id: str
    instance: str
    page_id: str
    page_version: int
    connector_id: str
    source_key: str
    source_id: str
    revision_id: str
    revision_digest: str
    index_refs_digest: str
    query_set: list[dict[str, Any]]
    query_set_digest: str

    def bindings(self) -> dict[str, Any]:
        return {"intent_id": self.intent_id, "publication_card_hash": self.card_hash,
                "workspace_id": self.workspace_id, "connection_id": self.connection_id, "instance": self.instance,
                "source_key": self.source_key, "page_id": self.page_id, "page_version": self.page_version,
                "revision_id": self.revision_id, "revision_digest": self.revision_digest,
                "query_set_digest": self.query_set_digest}


async def confirmed_publication(db: AsyncSession, run: WorkflowRun) -> ConfirmedPublication:
    # Re-derived from the database, never from a caller.
    intent = await published_intent(db, run)
    if intent is None or not intent.result_page_id or not intent.result_version:
        raise AudienceProofError(CODE_NOT_PUBLISHED, "the run has no approved, sent-confirmed publication",
                                 failure_class=CLASS_INVALID)
    decision = await _confirmed_decision(db, run, intent)
    provenance, digests, connector = await _proven_source(db, run, intent, decision)
    try:
        binding = await ledger_binding(db, connector_id=connector.id, project_id=run.project_id,
                                       page_id=str(intent.result_page_id), page_version=int(intent.result_version),
                                       instance=str(intent.instance), revision_id=str(provenance["revision_id"]),
                                       revision_digest=str(digests["document_html_digest"]))
    except BindingRefusedError as error:
        failure_class = CLASS_SAFETY if binding_class(error.reason) == CLASS_SAFETY else CLASS_AUDIENCE_UNPROVEN
        raise AudienceProofError(CODE_BINDING, f"Knowledge no longer holds the proven version: {error.detail}",
                                 failure_class=failure_class) from None
    if binding.index_refs_digest != digests.get("index_refs_digest"):
        raise AudienceProofError(CODE_BINDING, "the projected spans changed since the provenance was recorded")
    query_set = derive_query_set(dict(decision.payload or {}))
    return ConfirmedPublication(
        intent_id=intent.id, card_hash=str(intent.card_hash), workspace_id=run.project_id,
        connection_id=str(intent.connection_id), instance=str(intent.instance), page_id=str(intent.result_page_id),
        page_version=int(intent.result_version), connector_id=connector.id, source_key=binding.source_key,
        source_id=binding.source_id, revision_id=binding.revision_id, revision_digest=binding.revision_digest,
        index_refs_digest=binding.index_refs_digest, query_set=query_set, query_set_digest=sha256_json(query_set))


async def _confirmed_decision(db: AsyncSession, run: WorkflowRun, intent: Any) -> WorkflowRunDecision:
    decision = await db.get(WorkflowRunDecision, intent.decision_id) if intent.decision_id else None
    if (decision is None or decision.run_id != run.id or decision.action != CONFIRMED or not intent.card_hash
            or decision.payload_hash != intent.card_hash or payload_hash(decision.payload) != intent.card_hash):
        raise AudienceProofError(CODE_BINDING, "the publication intent is not bound to its confirmed (b) card",
                                 failure_class=CLASS_SAFETY)
    latest = (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == run.id, WorkflowRunDecision.kind == "confirmation",
        WorkflowRunDecision.subject == decision.subject,
    ).order_by(WorkflowRunDecision.created_at.desc(), WorkflowRunDecision.id.desc()).limit(1))).scalar_one_or_none()
    if latest is None or latest.id != decision.id or latest.action != CONFIRMED:
        raise AudienceProofError(CODE_BINDING, "the publication card was changed or superseded")
    from .audience_binding import audience_binding_problem

    config = await get_project_config(run.project_id, db)
    problem = audience_binding_problem(dict(decision.payload or {}), config, run.project_id)
    if problem:
        raise AudienceProofError(CODE_BINDING, problem)
    return decision


async def _proven_source(db: AsyncSession, run: WorkflowRun, intent: Any, decision: WorkflowRunDecision
                        ) -> tuple[dict[str, Any], dict[str, Any], KnowledgeSourceConnector]:
    provenance = dict(dict(dict(run.context or {}).get(DOCUMENTATION_KEY) or {}).get(PROVENANCE_KEY) or {})
    digests = dict(provenance.get("digests") or {})
    if (provenance.get("proven") is not True or provenance.get("intent_id") != intent.id
            or str(provenance.get("page_id")) != str(intent.result_page_id)
            or provenance.get("page_version") != intent.result_version
            or not digests.get("document_html_digest") or not provenance.get("revision_id")):
        raise AudienceProofError(CODE_NOT_PROVEN, "the published version has no pinned Knowledge provenance")
    connector = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == run.project_id,
        KnowledgeSourceConnector.connector_key == str(provenance.get("connector_key") or ""))
        .execution_options(populate_existing=True))).scalar_one_or_none()
    if connector is None:
        raise AudienceProofError(CODE_NOT_PROVEN, "the provenance's Knowledge source no longer exists")
    approved_audience = dict(dict(decision.payload or {}).get("audience") or {})
    if connector.connector_key != approved_audience.get("source_key"):
        raise AudienceProofError(CODE_BINDING, "the published page is proven through another Knowledge source")
    page = {"connection_id": intent.connection_id, "instance": intent.instance,
            "space_key": intent.space_key, "parent_id": intent.parent_id}
    if await publication_source_refusal(db, page, connector):
        raise AudienceProofError(CODE_BINDING, "the Knowledge serving connection changed", failure_class=CLASS_SAFETY)
    return provenance, digests, connector
