"""Proving a proposed ast-grep check on a device (From Correction to Check, step 2; one check kind end to end,
``pattern``)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CheckProposal, WorkflowRun
from ...time_utils import utc_now
from ..observability.check_proposal_metrics import count_proof
from . import proof_job

logger = logging.getLogger(__name__)
PURPOSE = "check_proof"
ON_DONE = "check_proposals.proof:record"
MAX_CASES = 4  # occurrences proven per proposal (two archives each)
MAX_PER_PASS = 5
RETRIES = 1


def _not_run(reason: str, attempt: int = 0) -> dict[str, Any]:
    return {"state": "not_run", "reason": reason, "attempt": attempt, "red_on": [], "green_on": None,
            "at": utc_now().isoformat()}


def _side(occurrence: dict[str, Any], side: str) -> str:
    return str(occurrence.get(f"{side}_tree") or occurrence.get(f"{side}_sha") or "")


async def cases_of(db: AsyncSession, signature: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    cases, people = [], []
    for occurrence in [item for item in signature.get("occurrences") or [] if isinstance(item, dict)]:
        paths = [str(path) for path in occurrence.get("paths") or [] if path]
        before, after = _side(occurrence, "before"), _side(occurrence, "after")
        run = await db.get(WorkflowRun, str(occurrence.get("run_id") or "")) if occurrence.get("run_id") else None
        repo = str(dict(getattr(run, "context", None) or {}).get("local_path") or "")
        if not (paths and before and after and repo and (Path(repo) / ".git").exists()):
            continue
        number = len(cases) // 2 + 1
        cases += [{"archive": f"red-{number}", "side": "red", "commit": before, "paths": paths, "repo": repo},
                  {"archive": f"green-{number}", "side": "green", "commit": after, "paths": paths, "repo": repo}]
        people.append(str(run.requested_by))
        if len(cases) >= 2 * MAX_CASES:
            break
    return cases, list(dict.fromkeys(people))


def _archives(cases: list[dict[str, Any]], rule: bytes) -> tuple[list[Any], list[dict[str, Any]]]:
    from ..devices import tree_archive

    archives, kept = [tree_archive.build_archive([(proof_job.RULE_FILE, rule)], name=proof_job.RULE_ARCHIVE)], []
    for case in cases:
        try:
            archive = tree_archive.build_from_git(Path(case["repo"]), case["commit"], name=case["archive"],
                                                  paths=case["paths"])
        except Exception:  # noqa: BLE001 - a pruned tree or a moved working copy: that case is left out
            logger.info("check_proof.case_unavailable archive=%s", case["archive"], exc_info=True)
            continue
        if archive.bytes and not set(case["paths"]) <= set(archive.skipped):
            archives.append(archive)
            kept.append({key: case[key] for key in ("archive", "side", "commit", "paths")})
    return archives, kept


async def offer_proof(db: AsyncSession, proposal: CheckProposal, signature: dict[str, Any] | None) -> dict[str, Any]:
    from ..devices import tool_jobs

    attempt = int(dict(proposal.proof or {}).get("attempt") or 0) + 1
    try:
        rule = proof_job.rule_file(dict(dict(proposal.draft or {}).get("rule") or {}))
    except ValueError as error:
        proposal.proof = _not_run(f"no ast-grep rule to prove: {error}", attempt)
        return proposal.proof
    cases, people = await cases_of(db, signature or {})
    archives, kept = _archives(cases, rule)
    if not {case["side"] for case in kept} >= {"red", "green"}:
        proposal.proof = _not_run("no code state: the corrections carry no code from before and after the fix",
                                  attempt)
        count_proof(proposal.workspace_id, "unavailable")
        return proposal.proof
    candidates = await tool_jobs.devices_of(db, people)
    if not candidates:
        proposal.proof = _not_run("no device: none of the runs' people has an active device", attempt)
        count_proof(proposal.workspace_id, "unavailable")
        return proposal.proof
    job = await tool_jobs.offer(db, purpose=PURPOSE, candidates=candidates, archives=archives,
                                steps=proof_job.steps(kept), needs=[proof_job.TOOL],
                                workspace_id=proposal.workspace_id, on_done=ON_DONE)
    proposal.proof = {"state": "running", "job_id": job.id, "cases": kept, "attempt": attempt, "red_on": [],
                      "green_on": None, "at": utc_now().isoformat()}
    count_proof(proposal.workspace_id, "offered")
    return proposal.proof


async def record(db: AsyncSession, job: Any) -> None:
    rows = (await db.execute(select(CheckProposal).where(CheckProposal.workspace_id == job.workspace_id,
                                                         CheckProposal.state == "proposed"))).scalars()
    proposal = next((row for row in rows if dict(row.proof or {}).get("job_id") == job.id), None)
    if proposal is None:
        return  # decided or edited meanwhile: an edit starts a new proof
    proof = dict(proposal.proof or {})
    if job.state != "done":
        proposal.proof = {**_not_run(f"the device did not finish the proof ({job.state}: {job.reason or ''})".strip(),
                                     int(proof.get("attempt") or 1)), "retry": True}
        count_proof(proposal.workspace_id, "unavailable")
        return
    steps = list(dict(job.result or {}).get("steps") or [])
    proposal.proof = proof_job.verdict(list(proof.get("cases") or []), steps, at=utc_now().isoformat())
    count_proof(proposal.workspace_id, proposal.proof["state"])


def _due(proposal: CheckProposal) -> bool:
    draft, proof = dict(proposal.draft or {}), dict(proposal.proof or {})
    if draft.get("kind") != "pattern" or not draft.get("rule"):
        return False
    if proof.get("state") in (None, "not_run") and not proof.get("attempt"):
        return True  # never offered (new, or edited since)
    return bool(proof.get("retry")) and int(proof.get("attempt") or 0) <= RETRIES


async def prove_due(db: AsyncSession, *, signature_of: Any = None) -> int:
    if signature_of is None:
        from ..workflow_runs.corrections import get_signature as signature_of
    due = list((await db.execute(select(CheckProposal).where(CheckProposal.state == "proposed")
                                 .order_by(CheckProposal.created_at).limit(50))).scalars())
    offered = 0
    for proposal in [item for item in due if _due(item)][:MAX_PER_PASS]:
        try:
            proof = await offer_proof(db, proposal, await signature_of(db, proposal.signature_id))
            offered += int(proof.get("state") == "running")
        except Exception:  # noqa: BLE001 - logged; the proposal says it and the next ones are still offered
            logger.exception("check_proof.offer_failed proposal=%s", proposal.id)
            proposal.proof = _not_run("the proof could not be offered", RETRIES + 1)
        await db.commit()
    return offered


__all__ = ["MAX_CASES", "PURPOSE", "cases_of", "offer_proof", "prove_due", "record"]
