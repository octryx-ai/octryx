"""Recording an audience receipt (the search route's ``proof_request``): the challenge's query set, run as the
authenticated caller with their real Knowledge authorization (``issued -> recorded``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import DocumentationAudienceReceipt, User, WorkflowRun
from ....models.runtime.documentation_publication import (
    RECEIPT_EXPIRED,
    RECEIPT_ISSUED,
    RECEIPT_OUTCOME_NEGATIVE,
    RECEIPT_OUTCOME_POSITIVE,
    RECEIPT_RECORDED,
)
from ....time_utils import utc_now
from .audience_contract import (
    CODE_BINDING,
    CODE_CONCURRENT,
    CODE_EXPIRED,
    CODE_STATE,
    CODE_UNKNOWN,
    QUERY_LIMIT,
    REFUSAL_WORKSPACE,
    ROLE_OUTSIDER,
    AudienceProofError,
)
from .audience_query_set import normalized
from .receipt_store import _fresh_run, _hit_fact, _locked, _recheck, _transition, result_digest


async def _claimed_receipt(db: AsyncSession, *, current_user: User, workspace_id: str,
                           proof_request: dict[str, Any]) -> DocumentationAudienceReceipt:
    """The caller's own open challenge, locked after its run and re-checked, or :class:`AudienceProofError`."""
    unknown = AudienceProofError(CODE_UNKNOWN, "no such audience challenge", status=404)
    challenge = str(proof_request.get("challenge_id") or "")
    receipt = (await db.execute(select(DocumentationAudienceReceipt).where(
        DocumentationAudienceReceipt.challenge_id == challenge))).scalar_one_or_none()
    # The caller must be P, on P's Workspace: anything else is indistinguishable from an unknown challenge.
    if receipt is None or receipt.workspace_id != str(workspace_id) or current_user is None \
            or current_user.id != receipt.expected_principal_id:
        raise unknown
    run = await db.get(WorkflowRun, receipt.run_id)
    if run is None:
        raise unknown
    run = await _fresh_run(db, run)
    receipt = await _locked(db, select(DocumentationAudienceReceipt).where(
        DocumentationAudienceReceipt.challenge_id == challenge))
    if receipt is None or receipt.expected_principal_id != current_user.id:
        raise unknown
    for field, column in (("run_id", "run_id"), ("pass_key", "pass_key"),
                          ("publication_card_hash", "publication_card_hash")):
        claimed = proof_request.get(field)
        if claimed is not None and claimed != getattr(receipt, column):
            raise AudienceProofError(CODE_BINDING, f"the proof request names another {field} than the challenge")
    if receipt.state != RECEIPT_ISSUED:
        raise AudienceProofError(CODE_STATE, f"the challenge is {receipt.state}, not open for a result")
    if utc_now() >= receipt.expires_at:
        await _transition(db, receipt, RECEIPT_EXPIRED)
        raise AudienceProofError(CODE_EXPIRED, "the challenge expired", status=410)
    await _recheck(db, receipt, run, phase="record")
    return receipt


async def _run_queries(db: AsyncSession, receipt: DocumentationAudienceReceipt, *, current_user: User,
                       runtime: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(hits, assertion results)`` of the query set, searched with the caller's real Workspace authorization."""
    from ...knowledge.access.authorization import authorize_workspace
    from ...knowledge.ledger.errors import WorkspaceNotAccessibleError
    from ...knowledge.retrieval.evidence import LEXICAL_MODES, retrieve_workspace_evidence

    source_id = str(dict(receipt.issue_checks or {}).get("source_id") or "")
    hits: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    refusal = None
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=receipt.workspace_id)
    except WorkspaceNotAccessibleError:
        authorized, refusal = None, REFUSAL_WORKSPACE
    for assertion in receipt.query_set:
        if authorized is None:
            results.append({"id": assertion["id"], "passed": False, "hit_keys": [], "refused": refusal})
            continue
        found = await retrieve_workspace_evidence(db, runtime=runtime, authorized=authorized,
                                                  query_text=assertion["query"], limit=QUERY_LIMIT,
                                                  modes=LEXICAL_MODES)
        passed_keys = []
        for item in found.evidence:
            fact = _hit_fact(item, receipt, source_id)
            hits.setdefault(item.evidence_key, fact)
            if fact["bound"] and all(probe in normalized(item.text) for probe in assertion["expect"]):
                passed_keys.append(item.evidence_key)
        results.append({"id": assertion["id"], "passed": bool(passed_keys), "hit_keys": sorted(passed_keys)})
    hit_list = [hits[key] for key in sorted(hits)]
    return hit_list, results


async def record_audience_receipt(db: AsyncSession, *, current_user: User, workspace_id: str,
                                  proof_request: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """Run the challenge's query set as the authenticated caller and record the result (``issued -> recorded``)."""
    receipt = await _claimed_receipt(db, current_user=current_user, workspace_id=workspace_id,
                                     proof_request=proof_request)
    role = receipt.pass_key.rsplit("@", 1)[-1]
    hit_list, results = await _run_queries(db, receipt, current_user=current_user, runtime=runtime)
    outcome = RECEIPT_OUTCOME_POSITIVE if any(hit["bound"] for hit in hit_list) else RECEIPT_OUTCOME_NEGATIVE
    digest = result_digest(receipt, outcome=outcome, hits=hit_list, assertion_results=results)
    if not await _transition(db, receipt, RECEIPT_RECORDED, {
            "recorded_at": utc_now(), "recorded_by": current_user.id, "outcome": outcome, "hits": hit_list,
            "assertion_results": results, "result_digest": digest}):
        raise AudienceProofError(CODE_CONCURRENT, "the challenge changed while the result was recorded")
    if role == ROLE_OUTSIDER:
        # Even an expected outsider must not learn section names, criteria or page bindings.
        return {"challenge_id": receipt.challenge_id, "state": RECEIPT_RECORDED,
                "principal_role": role, "outcome": outcome}
    return {"challenge_id": receipt.challenge_id, "state": RECEIPT_RECORDED, "principal_role": role,
            "query_source": "server_challenge", "outcome": outcome, "result_digest": digest,
            "assertions": [{"id": item["id"], "passed": item["passed"]} for item in results],
            "bound_hits": sum(1 for hit in hit_list if hit["bound"]), "other_hits": sum(
                1 for hit in hit_list if not hit["bound"])}
