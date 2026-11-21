"""Audience receipt state: compare-and-set transitions, locks, the result digest and the binding re-checks."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import DocumentationAudienceReceipt, WorkflowRun
from ....models.runtime.documentation_publication import (
    RECEIPT_ISSUED,
    RECEIPT_OUTCOME_NEGATIVE,
    RECEIPT_OUTCOME_POSITIVE,
    RECEIPT_RECORDED,
    RECEIPT_REVOKED,
    receipt_transition_allowed,
)
from ....time_utils import utc_now
from .audience_contract import (
    CODE_BINDING,
    CODE_PRINCIPAL,
    CODE_STATE,
    REFUSAL_WORKSPACE,
    ROLE_AUDIENCE,
    SEMANTICS_SOURCE,
    SEMANTICS_WORKSPACE,
    AudienceProofError,
    role_pass_key,
)
from .audience_principals import _configured, principal_checks
from .audience_publication import ConfirmedPublication, confirmed_publication
from .knowledge_proof import CLASS_AUDIENCE_UNPROVEN, sha256_json


async def _open_receipts(db: AsyncSession, run: WorkflowRun, role: str) -> list[DocumentationAudienceReceipt]:
    return list((await db.execute(select(DocumentationAudienceReceipt).where(
        DocumentationAudienceReceipt.run_id == run.id,
        DocumentationAudienceReceipt.pass_key.like(f"%@{role}"),
        DocumentationAudienceReceipt.state.in_((RECEIPT_ISSUED, RECEIPT_RECORDED))))).scalars().all())


async def _transition(db: AsyncSession, receipt: DocumentationAudienceReceipt, target: str,
                      values: dict[str, Any] | None = None) -> bool:
    """Compare-and-set ``receipt`` to ``target`` on its current state and ``state_version``."""
    if not receipt_transition_allowed(receipt.state, target):
        return False
    current, version = receipt.state, int(receipt.state_version or 0)
    result = await db.execute(
        update(DocumentationAudienceReceipt)
        .where(DocumentationAudienceReceipt.id == receipt.id, DocumentationAudienceReceipt.state == current,
               DocumentationAudienceReceipt.state_version == version)
        .values(state=target, state_version=version + 1, updated_at=utc_now(), **dict(values or {}))
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        return False
    await db.refresh(receipt)
    return True


async def _revoke(db: AsyncSession, receipt: DocumentationAudienceReceipt, reason: str) -> None:
    await _transition(db, receipt, RECEIPT_REVOKED, {"revoked_at": utc_now(), "revoke_reason": reason[:64]})


def _hit_fact(item: Any, publication_or_receipt: Any, source_id: str) -> dict[str, Any]:
    return {"evidence_key": item.evidence_key, "source_id": item.source_id, "revision_id": item.revision_id,
            "span_ordinal": item.span_ordinal, "content_sha256": item.content_sha256,
            "bound": (item.source_id == source_id and item.revision_id == publication_or_receipt.revision_id
                      and f"sha256:{item.content_sha256}" == publication_or_receipt.revision_digest)}


def result_digest(receipt: DocumentationAudienceReceipt, *, outcome: str, hits: list, assertion_results: list
                  ) -> str:
    return sha256_json({"challenge_id": receipt.challenge_id, "principal_id": receipt.expected_principal_id,
                        "query_set_digest": receipt.query_set_digest, "revision_id": receipt.revision_id,
                        "outcome": outcome, "hits": hits, "assertion_results": assertion_results})


def _same_bindings(receipt: DocumentationAudienceReceipt, publication: ConfirmedPublication) -> list[str]:
    """The binding names whose current value differs from the receipt's."""
    drift = [key for key, value in publication.bindings().items() if getattr(receipt, key) != value]
    if sha256_json(receipt.query_set) != receipt.query_set_digest:
        drift.append("query_set")
    return drift


async def _locked(db: AsyncSession, statement) -> DocumentationAudienceReceipt | None:
    return (await db.execute(statement.with_for_update().execution_options(populate_existing=True))
            ).scalars().first()


async def _fresh_run(db: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    """Claim fresh Run before receipt: this lock order matches the workflow engine."""
    coordinates = (run.project_id, run.current_node_id, dict(run.node_state or {}).get("entry"))
    await db.flush()
    fresh = (await db.execute(select(WorkflowRun).where(WorkflowRun.id == run.id)
                             .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if fresh is None or fresh.status not in ("running", "waiting"):
        raise AudienceProofError(CODE_STATE, "the run is not eligible for an audience proof")
    if coordinates != (fresh.project_id, fresh.current_node_id, dict(fresh.node_state or {}).get("entry")):
        raise AudienceProofError(CODE_BINDING, "the run moved before the audience proof")
    return fresh


async def _recheck(db: AsyncSession, receipt: DocumentationAudienceReceipt, run: WorkflowRun | None, *,
                   phase: str) -> ConfirmedPublication:
    """Every binding of ``receipt`` against the database now; a failed re-check revokes it."""
    role = receipt.pass_key.rsplit("@", 1)[-1]
    try:
        if run is None or run.id != receipt.run_id:
            raise AudienceProofError(CODE_BINDING, "the receipt belongs to another run")
        if run.current_node_id != receipt.node_id or role_pass_key(run, role) != receipt.pass_key:
            raise AudienceProofError(CODE_BINDING, "the receipt is stale: the run is in another node or pass")
        settings, principal = await _configured(db, run, role)
        if principal != receipt.expected_principal_id:
            raise AudienceProofError(CODE_BINDING, "the configured principal changed since the challenge")
        publication = await confirmed_publication(db, run)
        drift = _same_bindings(receipt, publication)
        if drift or publication.query_set_digest != sha256_json(publication.query_set):
            raise AudienceProofError(CODE_BINDING, f"the confirmed publication changed ({', '.join(drift)})")
        checks = await principal_checks(db, role=role, user_id=principal, settings=settings,
                                        publication=publication, requester_id=run.requested_by,
                                        refusal_class=CLASS_AUDIENCE_UNPROVEN)
        issued = dict(receipt.issue_checks or {})
        if (checks["semantics"] != issued.get("semantics") or checks["workspace_role"] != issued.get("workspace_role")
                or checks["principal_admitted"] != issued.get("principal_admitted")):
            raise AudienceProofError(CODE_PRINCIPAL, f"the {role} principal's access changed since the challenge")
    except AudienceProofError as error:
        await _revoke(db, receipt, f"{phase}:{error.code}")
        raise
    return publication


def _expected_met(receipt: DocumentationAudienceReceipt, role: str) -> str:
    """``""`` when the recorded result is the proof the role owes, else why not."""
    results = list(receipt.assertion_results or [])
    hits = list(receipt.hits or [])
    semantics = dict(receipt.issue_checks or {}).get("semantics")
    if role == ROLE_AUDIENCE:
        if receipt.outcome != RECEIPT_OUTCOME_POSITIVE:
            return "P retrieved nothing of the published page"
        missing = [item["id"] for item in results if not item.get("passed")]
        if missing or len(results) != len(receipt.query_set):
            return f"P's retrieval misses {', '.join(missing) or 'assertions'}"
        return ""
    if receipt.outcome != RECEIPT_OUTCOME_NEGATIVE or any(hit.get("bound") for hit in hits):
        return "the outsider retrieved content of the published page"
    refused = {item.get("refused") for item in results}
    if semantics == SEMANTICS_WORKSPACE and refused != {REFUSAL_WORKSPACE}:
        return "the outsider was not refused by the Workspace"
    if semantics == SEMANTICS_SOURCE and refused != {None}:
        return "the source-restricted outsider must be a Workspace reader whose search ran"
    return ""
