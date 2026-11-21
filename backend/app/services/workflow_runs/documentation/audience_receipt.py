"""Authenticated audience receipts: issue, consume and current-proof validation.

Server-owned contract checks live in audience_contract (and its ``audience_*`` modules); recording runs in
receipt_record. Run is locked before receipt; recording uses the caller's real Knowledge authorization, and
consumption is CAS protected. Only blind acknowledgements are returned to outsiders. No tokens are stored.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import DocumentationAudienceReceipt, WorkflowRun
from ....models.runtime.documentation_publication import (
    RECEIPT_CONSUMED,
    RECEIPT_EXPIRED,
    RECEIPT_ISSUED,
    RECEIPT_RECORDED,
    RECEIPT_REVOKED,
)
from ....time_utils import utc_now
from ..platform.dispatch import CLASS_SAFETY, FAILED, SUCCEEDED, ToolOutcome
from ..records import record_event
from .audience_contract import (
    CODE_BINDING,
    CODE_CONCURRENT,
    CODE_PRINCIPAL,
    CODE_UNPROVEN,
    EVENT_CONSUMED,
    EVENT_ISSUED,
    EVENT_REFUSED,
    EXPECTED_OUTCOME,
    PROOF_CONTEXT_KEY,
    QUERY_LIMIT,
    QUERY_MODE,
    ROLE_AUDIENCE,
    ROLES,
    AudienceProofError,
    role_pass_key,
)
from .audience_principals import _configured, principal_checks
from .audience_publication import (
    confirmed_publication,
)
from .knowledge_proof import CLASS_AUDIENCE_UNPROVEN, CLASS_NEEDS_CONFIGURATION
from .publish import DOCUMENTATION_KEY
from .receipt_store import (
    _expected_met,
    _fresh_run,
    _locked,
    _open_receipts,
    _recheck,
    _revoke,
    _same_bindings,
    _transition,
    result_digest,
)

# --- issue -----------------------------------------------------------------------------------------------------


async def issue_audience_challenge(db: AsyncSession, run: WorkflowRun, *, principal_role: str = ROLE_AUDIENCE
                                   ) -> DocumentationAudienceReceipt:
    """Issue (or return, within the same pass) the server-owned challenge for the configured principal."""
    if principal_role not in ROLES:
        raise ValueError(f"unknown principal role {principal_role!r}")
    run = await _fresh_run(db, run)
    settings, principal = await _configured(db, run, principal_role)
    publication = await confirmed_publication(db, run)
    checks = await principal_checks(db, role=principal_role, user_id=principal, settings=settings,
                                    publication=publication, requester_id=run.requested_by,
                                    refusal_class=CLASS_NEEDS_CONFIGURATION)
    node_id, pass_key = str(run.current_node_id or ""), role_pass_key(run, principal_role)
    now = utc_now()
    for open_receipt in await _open_receipts(db, run, principal_role):
        same = (open_receipt.node_id == node_id and open_receipt.pass_key == pass_key
                and open_receipt.expected_principal_id == principal and open_receipt.state == RECEIPT_ISSUED
                and open_receipt.expires_at > now
                and all(getattr(open_receipt, key) == value for key, value in publication.bindings().items()))
        if same:
            return open_receipt
        await _revoke(db, open_receipt, "superseded")
    receipt = DocumentationAudienceReceipt(
        challenge_id=uuid.uuid4().hex, run_id=run.id, node_id=node_id, pass_key=pass_key,
        query_set=publication.query_set, expected_principal_id=principal,
        issue_checks={**checks, "expected_outcome": EXPECTED_OUTCOME[principal_role], "query_mode": QUERY_MODE,
                      "query_limit": QUERY_LIMIT, "requester_id": run.requested_by,
                      "index_refs_digest": publication.index_refs_digest, "source_id": publication.source_id},
        state=RECEIPT_ISSUED, issued_at=now, expires_at=now + timedelta(hours=settings.ttl_hours),
        **publication.bindings())
    db.add(receipt)
    await db.flush()
    record_event(db, run, EVENT_ISSUED, node_id=run.current_node_id, detail={
        "challenge_id": receipt.challenge_id, "principal_role": principal_role, "expected_principal_id": principal,
        "page_id": publication.page_id, "page_version": publication.page_version,
        "revision_id": publication.revision_id, "query_set_digest": publication.query_set_digest,
        "expires_at": receipt.expires_at.isoformat()})
    return receipt


async def issue_audience_challenge_action(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    """Platform-action form of :func:`issue_audience_challenge` (``params.principal_role``, default audience)."""
    role = str(dict(params or {}).get("principal_role") or ROLE_AUDIENCE)
    try:
        receipt = await issue_audience_challenge(db, run, principal_role=role)
    except AudienceProofError as error:
        return ToolOutcome(FAILED, {"code": error.code}, error.detail, failure_class=error.failure_class)
    return ToolOutcome(SUCCEEDED, {"challenge_id": receipt.challenge_id, "principal_role": role,
                                   "expected_principal_id": receipt.expected_principal_id,
                                   "expires_at": receipt.expires_at.isoformat()})


# --- consume ----------------------------------------------------------------------------------------------------


async def consume_audience_receipt(db: AsyncSession, run: WorkflowRun, *, principal_role: str = ROLE_AUDIENCE
                                   ) -> ToolOutcome:
    """Consume this pass's recorded receipt once, under a lock, after re-checking every binding."""
    if principal_role not in ROLES:
        raise ValueError(f"unknown principal role {principal_role!r}")
    try:
        run = await _fresh_run(db, run)
    except AudienceProofError as error:
        return ToolOutcome(FAILED, {"code": error.code}, error.detail, failure_class=error.failure_class)
    receipt = await _locked(db, select(DocumentationAudienceReceipt).where(
        DocumentationAudienceReceipt.run_id == run.id,
        DocumentationAudienceReceipt.node_id == str(run.current_node_id or ""),
        DocumentationAudienceReceipt.pass_key == role_pass_key(run, principal_role),
    ).order_by(DocumentationAudienceReceipt.issued_at.desc()).limit(1))
    refused = _refuser(db, run, receipt, principal_role)
    checked = await _consumable(db, run, receipt, principal_role, refused)
    if isinstance(checked, ToolOutcome):
        return checked
    publication, expected = checked
    checks = {"at": utc_now().isoformat(), "bindings": publication.bindings(), "result_digest": expected,
              "expected_outcome": EXPECTED_OUTCOME[principal_role]}
    try:
        async with db.begin_nested():
            consumed = await _transition(db, receipt, RECEIPT_CONSUMED, {
                "consumed_at": utc_now(), "consumed_by_run_id": run.id, "consume_checks": checks})
    except IntegrityError:
        consumed = False
    if not consumed:
        return refused(CODE_CONCURRENT, "another consumer took this receipt first")
    return _record_proof(db, run, receipt, principal_role, checks)


def _refuser(db: AsyncSession, run: WorkflowRun, receipt: DocumentationAudienceReceipt | None,
             principal_role: str) -> Any:
    """The refusal answer of a consume (an event, then a ``failed`` outcome with the fixed code)."""

    def refused(code: str, reason: str, failure_class: str = CLASS_AUDIENCE_UNPROVEN) -> ToolOutcome:
        record_event(db, run, EVENT_REFUSED, node_id=run.current_node_id, detail={
            "principal_role": principal_role, "code": code,
            "challenge_id": receipt.challenge_id if receipt is not None else None})
        return ToolOutcome(FAILED, {"code": code, "principal_role": principal_role,
                                    "pending": code == "not_recorded"}, reason, failure_class=failure_class)

    return refused


async def _consumable(db: AsyncSession, run: WorkflowRun, receipt: DocumentationAudienceReceipt | None,
                      principal_role: str, refused: Any) -> ToolOutcome | tuple[Any, str]:
    """The refusal, or ``(publication, result digest)`` of a recorded receipt that proves what the role owes."""
    if receipt is None:
        return refused("no_receipt", f"no {principal_role} receipt was issued in this pass")
    if receipt.state == RECEIPT_CONSUMED:
        return refused("replayed", "the receipt was already consumed")
    if receipt.state in (RECEIPT_REVOKED, RECEIPT_EXPIRED):
        return refused(receipt.state, f"the receipt is {receipt.state}")
    if utc_now() >= receipt.expires_at:
        await _transition(db, receipt, RECEIPT_EXPIRED)
        return refused(RECEIPT_EXPIRED, "the receipt expired")
    if receipt.state != RECEIPT_RECORDED:
        return refused("not_recorded", f"the {principal_role} principal has not run the audience check yet")
    if receipt.recorded_by != receipt.expected_principal_id:
        await _revoke(db, receipt, "consume:actor")
        return refused(CODE_PRINCIPAL, "the receipt was not recorded by its expected principal", CLASS_SAFETY)
    try:
        publication = await _recheck(db, receipt, run, phase="consume")
    except AudienceProofError as error:
        return refused(error.code, error.detail, error.failure_class)
    expected = result_digest(receipt, outcome=str(receipt.outcome), hits=list(receipt.hits or []),
                             assertion_results=list(receipt.assertion_results or []))
    if expected != receipt.result_digest:
        await _revoke(db, receipt, "consume:result_digest")
        return refused(CODE_BINDING, "the recorded result does not match its digest", CLASS_SAFETY)
    unmet = _expected_met(receipt, principal_role)
    if unmet:
        await _revoke(db, receipt, f"consume:{CODE_UNPROVEN}")
        return refused(CODE_UNPROVEN, unmet)
    return publication, expected


def _record_proof(db: AsyncSession, run: WorkflowRun, receipt: DocumentationAudienceReceipt, principal_role: str,
                  checks: dict[str, Any]) -> ToolOutcome:
    """The consumed proof on the run's documentation context, with its event."""
    proof = {"challenge_id": receipt.challenge_id, "principal_role": principal_role,
             "principal_id": receipt.expected_principal_id, "outcome": receipt.outcome,
             "receipt_id": receipt.id, "node_id": receipt.node_id, "pass_key": receipt.pass_key,
             "intent_id": receipt.intent_id, "card_hash": receipt.publication_card_hash,
             "semantics": dict(receipt.issue_checks or {}).get("semantics"), "page_id": receipt.page_id,
             "page_version": receipt.page_version, "revision_id": receipt.revision_id,
             "result_digest": receipt.result_digest, "consumed_at": checks["at"]}
    documentation = dict(dict(run.context or {}).get(DOCUMENTATION_KEY) or {})
    proofs = {**dict(documentation.get(PROOF_CONTEXT_KEY) or {}), principal_role: proof}
    run.context = {**dict(run.context or {}), DOCUMENTATION_KEY: {**documentation, PROOF_CONTEXT_KEY: proofs}}
    record_event(db, run, EVENT_CONSUMED, node_id=run.current_node_id, detail=proof)
    return ToolOutcome(SUCCEEDED, proof)


async def validate_current_publication_proof(db: AsyncSession, run: WorkflowRun) -> ToolOutcome:
    """Revalidate consumed proofs at deferred acceptance; never consume or fabricate retrieval again."""
    try:
        run = await _fresh_run(db, run)
        publication = await confirmed_publication(db, run)
        proofs = dict(dict(dict(run.context or {}).get(DOCUMENTATION_KEY) or {}).get(PROOF_CONTEXT_KEY) or {})
        for role in ROLES:
            proof = dict(proofs.get(role) or {})
            receipt = (await db.execute(select(DocumentationAudienceReceipt).where(
                DocumentationAudienceReceipt.id == str(proof.get("receipt_id") or ""),
                DocumentationAudienceReceipt.run_id == run.id,
            ).execution_options(populate_existing=True))).scalar_one_or_none()
            if (receipt is None or receipt.state != RECEIPT_CONSUMED or receipt.consumed_by_run_id != run.id
                    or receipt.recorded_by != receipt.expected_principal_id
                    or receipt.node_id != proof.get("node_id") or receipt.pass_key != proof.get("pass_key")
                    or receipt.pass_key.rsplit("@", 1)[-1] != role
                    or _same_bindings(receipt, publication)):
                raise AudienceProofError(CODE_BINDING, "the consumed publication proof is not current")
            settings, principal = await _configured(db, run, role)
            if principal != receipt.expected_principal_id:
                raise AudienceProofError(CODE_PRINCIPAL, "the configured proof principal changed")
            checks = await principal_checks(db, role=role, user_id=principal, settings=settings,
                                            publication=publication,
                                   requester_id=run.requested_by, refusal_class=CLASS_AUDIENCE_UNPROVEN)
            issued = dict(receipt.issue_checks or {})
            if any(checks[key] != issued.get(key) for key in ("semantics", "workspace_role", "principal_admitted")):
                raise AudienceProofError(CODE_PRINCIPAL, "the proof principal's access changed")
            digest = result_digest(receipt, outcome=str(receipt.outcome), hits=list(receipt.hits or []),
                                   assertion_results=list(receipt.assertion_results or []))
            if digest != receipt.result_digest or digest != proof.get("result_digest") or _expected_met(receipt, role):
                raise AudienceProofError(CODE_BINDING, "the consumed retrieval result is not valid")
        return ToolOutcome(SUCCEEDED, {"intent_id": publication.intent_id, "page_id": publication.page_id,
                                       "page_version": publication.page_version})
    except AudienceProofError as error:
        return ToolOutcome(FAILED, {"code": error.code}, error.detail, failure_class=error.failure_class)


__all__ = [
    "consume_audience_receipt",
    "issue_audience_challenge",
    "issue_audience_challenge_action",
    "validate_current_publication_proof",
]
