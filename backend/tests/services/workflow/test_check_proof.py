"""Server side of an ast-grep check proof: red and green archives run as one device tool job, the raw answer becomes
the proof, and approving needs it (or accept_unproven); the device side is in the octryx-claude client tests."""

from __future__ import annotations

import json
import subprocess

import pytest

from app.models import CheckProposal, User, WorkflowRun
from app.services.check_proposals import proof, proof_job, store
from app.services.check_proposals.rules import CheckProposalRefusedError
from app.services.devices import tool_jobs
from app.services.observability import check_proposal_metrics
from tests.devices.device_support import device_with_grant
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

RULE = {"tool": "ast-grep", "language": "python", "rule": {"pattern": "os.environ[$KEY]"}}
MISTAKE, FIX = 'import os\nkey = os.environ["PAY_KEY"]\n', "from shop.config import settings\nkey = settings.pay_key\n"


class _Connection:
    def __init__(self, device_id: str) -> None:
        self.device_id, self.tools, self.sent = device_id, {"ast-grep": "0.51.0"}, []

    async def send(self, message_type: str, body: dict) -> None:
        self.sent.append((message_type, body))


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "shop").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.test")
    _git(repo, "config", "user.name", "t")
    shas = []
    for text in (MISTAKE, FIX):
        (repo / "shop" / "pay.py").write_text(text)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "x")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    return repo, shas


async def _setup(db, tmp_path, monkeypatch, *, code: bool = True):
    monkeypatch.setenv("OCTRYX_DEVICE_ARCHIVE_DIR", str(tmp_path / "archives"))
    check_proposal_metrics.reset()
    workspace_id = await seed_workspace(db)
    author = await db.get(User, await seed_member(db, workspace_id=workspace_id, role="owner"))
    approver = await seed_member(db, workspace_id=workspace_id, role="owner")
    device, _ = await device_with_grant(db, author, name="Mac")
    repo, (before, after) = _repo(tmp_path)
    run = WorkflowRun(project_id=workspace_id, workflow_kind="phased", workflow_key="x", title="t",
                      requested_by=author.id, context={"local_path": str(repo)})
    db.add(run)
    proposal = CheckProposal(workspace_id=workspace_id, signature_id="sig_env", state="proposed",
                             draft={"kind": "pattern", "rule": RULE, "summary": "reads the environment directly"},
                             message={"what": "w", "why": "y", "instead": "read settings"}, proof={"state": "not_run"})
    db.add(proposal)
    await db.flush()
    states = {"before_sha": before, "after_sha": after} if code else {}
    signature = {"id": "sig_env", "occurrences": [{"run_id": run.id, "paths": ["shop/pay.py"], **states}]}

    async def signature_of(_db, _ident):
        return signature

    return proposal, device, approver, before, after, signature_of


def _answer(job_id: str, red_exit: int, green_exit: int) -> dict:
    hit = json.dumps({"file": "red-1/shop/pay.py", "range": {"start": {"line": 1}}})
    green_hit = json.dumps({"file": "green-1/shop/pay.py", "range": {"start": {"line": 1}}})
    return {"job_id": job_id, "steps": [
        {"id": "scan-red-1", "status": "ok", "exit": red_exit, "stdout": hit if red_exit else "",
         "stderr": "Error: 1 error(s) found in code." if red_exit else ""},
        {"id": "scan-green-1", "status": "ok", "exit": green_exit, "stdout": green_hit if green_exit else "",
         "stderr": "Error: 1 error(s) found in code." if green_exit else ""}]}


async def _prove(db, proposal, device, signature_of, red_exit: int, green_exit: int) -> dict:
    assert await proof.prove_due(db, signature_of=signature_of) == 1
    await db.refresh(proposal)
    assert proposal.proof["state"] == "running" and proposal.proof["attempt"] == 1
    connection = _Connection(device.id)
    assert await tool_jobs.deliver(db, connection) == 1
    (kind, body), = connection.sent
    assert kind == "tool_job" and [item["name"] for item in body["archives"]] == ["rule", "red-1", "green-1"]
    assert [step["args"] for step in body["steps"]] == [step["args"] for step in proof_job.steps(proposal.proof["cases"])]
    assert await tool_jobs.apply_message(db, device.id, "tool_job_result",
                                         _answer(proposal.proof["job_id"], red_exit, green_exit))
    await db.refresh(proposal)
    return proposal.proof


@pytest.mark.asyncio
async def test_a_check_red_on_the_mistake_and_green_after_the_fix_is_proven_and_approved(db, tmp_path, monkeypatch):
    proposal, device, approver, before, after, signature_of = await _setup(db, tmp_path, monkeypatch)
    found = await _prove(db, proposal, device, signature_of, red_exit=1, green_exit=0)
    assert found["state"] == "proven" and found["red_on"] == [{"commit": before, "path": "shop/pay.py"}]
    assert found["green_on"] == {"commit": after, "files_checked": 1}
    approved = await store.approve(db, proposal.workspace_id, proposal.id, user_id=approver, may_approve=True)
    assert approved["state"] == "approved" and approved["decision"]["accept_unproven"] is False
    series = {key[1]: value for key, value in check_proposal_metrics.PROOFS.series.items()}
    assert series == {"offered": 1, "proven": 1}
    assert await proof.prove_due(db, signature_of=signature_of) == 0


@pytest.mark.asyncio
async def test_a_check_that_also_flags_the_fixed_code_fails_and_cannot_be_approved_unproven(db, tmp_path,
                                                                                         monkeypatch):
    proposal, device, approver, _before, _after, signature_of = await _setup(db, tmp_path, monkeypatch)
    found = await _prove(db, proposal, device, signature_of, red_exit=1, green_exit=1)
    assert found["state"] == "failed" and found["reason"] == "flags corrected code: shop/pay.py:2"
    with pytest.raises(CheckProposalRefusedError) as refused:
        await store.approve(db, proposal.workspace_id, proposal.id, user_id=approver, may_approve=True)
    assert refused.value.code == "proof_missing"
    assert await proof.prove_due(db, signature_of=signature_of) == 0  # a failed proof is a result, not retried


@pytest.mark.asyncio
async def test_without_a_code_state_the_proof_says_so_and_only_accept_unproven_approves(db, tmp_path, monkeypatch):
    proposal, _device, approver, _before, _after, signature_of = await _setup(db, tmp_path, monkeypatch, code=False)
    assert await proof.prove_due(db, signature_of=signature_of) == 0
    await db.refresh(proposal)
    assert proposal.proof["state"] == "not_run" and proposal.proof["reason"].startswith("no code state")
    assert await proof.prove_due(db, signature_of=signature_of) == 0
    with pytest.raises(CheckProposalRefusedError):
        await store.approve(db, proposal.workspace_id, proposal.id, user_id=approver, may_approve=True)
    approved = await store.approve(db, proposal.workspace_id, proposal.id, user_id=approver, may_approve=True,
                                   accept_unproven=True)
    assert approved["decision"]["accept_unproven"] is True


@pytest.mark.asyncio
async def test_a_job_without_result_is_offered_once_more_and_an_edited_rule_is_proven_anew(db, tmp_path,
                                                                                        monkeypatch):
    proposal, device, _approver, _before, _after, signature_of = await _setup(db, tmp_path, monkeypatch)
    assert await proof.prove_due(db, signature_of=signature_of) == 1
    await db.refresh(proposal)
    connection = _Connection(device.id)
    await tool_jobs.deliver(db, connection)
    await tool_jobs.apply_message(db, device.id, "tool_job_failed", {"job_id": proposal.proof["job_id"],
                                                                     "reason": "ast-grep is not available here"})
    await db.refresh(proposal)
    assert proposal.proof["state"] == "not_run" and "ast-grep is not available" in proposal.proof["reason"]
    assert await proof.prove_due(db, signature_of=signature_of) == 1
    await db.refresh(proposal)
    assert proposal.proof["attempt"] == 2
    await store.edit(db, proposal.workspace_id, proposal.id, user_id="someone",
                     body={"draft": {"rule": {**RULE, "rule": {"pattern": "os.getenv($KEY)"}}}})
    await db.refresh(proposal)
    assert proposal.proof == {"state": "not_run"}
    assert await proof.prove_due(db, signature_of=signature_of) == 1


def test_the_verdict_names_a_missed_mistake_and_a_rule_ast_grep_refused():
    cases = [{"archive": "red-1", "side": "red", "commit": "a", "paths": ["x.py"]},
             {"archive": "green-1", "side": "green", "commit": "b", "paths": ["x.py"]}]
    clean = {"status": "ok", "exit": 0, "stdout": "", "stderr": ""}
    missed = proof_job.verdict(cases, [{**clean, "id": "scan-red-1"}, {**clean, "id": "scan-green-1"}], at="t")
    assert missed["state"] == "failed" and missed["reason"] == "misses 1 of 1 past mistakes: x.py"
    refused = proof_job.verdict(cases, [{**clean, "id": "scan-red-1", "exit": 8}, {**clean, "id": "scan-green-1"}],
                                at="t")
    assert refused["state"] == "failed" and "could not run" in refused["reason"]
    with pytest.raises(ValueError):
        proof_job.rule_file({"tool": "ruff", "rule_id": "B006"})
