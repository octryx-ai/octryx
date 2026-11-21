"""From Correction to Check: capture and signature store.

Every correction of an agent's work is kept per Workspace, repository and app under a signature (check kind, file
pattern, normalised message) and its repeats are counted; a check is proposed when a signature reaches the
Workspace's threshold (default 2). A signature never holds a secret or a person's name."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import CorrectionSignature, Project, User, UserProject, WorkflowRun
from app.services.observability import agent_metrics, correction_metrics
from app.services.workflow_runs import corrections
from app.services.workflow_runs.corrections import signature

# Fake credentials in the shapes the redaction must catch, put together at run time so no scanner reads one here.
SECRETS = ("ghp_" + "abcdefghijklmnopqrstuvwxyz" + "0123456789", "sk-" + "ant-api03-" + "abcdefghijklmnopqrstuvwx",
           "AKIA" + "ABCDEFGHIJKLMNOP", ".".join(("eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0",
                                                 "dozjgNryP4J3jVmNHl0w5N")),
           "hunter2secret", "mara.keller@example.com")


def uid() -> str:
    return str(uuid.uuid4())


async def _workspace(db, **config) -> tuple[Project, User, WorkflowRun]:
    project = Project(id=uid(), name=f"Corrections {uid()[:6]}", is_active=True, config=config)
    mara = User(id=uid(), username=f"mkeller{uid()[:4]}", email=f"mara.keller.{uid()[:4]}@example.com",
                password_hash="x", display_name="Mara Keller", account_type="human")
    db.add_all([project, mara])
    await db.flush()
    db.add(UserProject(user_id=mara.id, project_id=project.id, role="member"))
    run = WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="ticket-delivery",
                      title="OCX-1", status="running", requested_by=mara.id, current_node_id="build",
                      repository="github:octryx/demo-shop", ticket_key="OCX-1", context={})
    db.add(run)
    await db.flush()
    return project, mara, run


async def _signatures(db, project: Project) -> list[CorrectionSignature]:
    return list((await db.execute(select(CorrectionSignature).where(
        CorrectionSignature.project_id == project.id).order_by(CorrectionSignature.first_seen))).scalars().all())


def test_one_mistake_in_other_files_lines_and_names_is_one_signature():
    first = signature.normalise(signature.redact("Use Decimal for money in shop/pricing/cart.py:26, not float "
                                                 "(`total_price` is 12.5)"))
    again = signature.normalise(signature.redact("Use Decimal for money in shop/orders/refund.py:140, not float "
                                                 "(`net_amount` is 3)"))
    assert first == again == "Use Decimal for money in <path>, not float (<code> is <n>)"
    assert signature.file_pattern("shop/pricing/cart.py:26") == signature.file_pattern("shop/orders/x.py") \
        == "shop/**/*.py"
    assert signature.file_pattern("main.dart") == "*.dart" and signature.file_pattern("") == "*"
    assert signature.key("review", "shop/**/*.py", first) == signature.key("review", "shop/**/*.py", again)
    assert signature.key("review", "shop/**/*.py", first) != signature.key("code_style", "shop/**/*.py", first)


@pytest.mark.asyncio
async def test_a_signature_and_its_excerpts_hold_no_secret_and_no_persons_name(db):
    project, mara, run = await _workspace(db)
    said = (f"Mara Keller here: never commit {SECRETS[0]} or {SECRETS[1]} again, AWS {SECRETS[2]}, token "
            f"{SECRETS[3]}, password={SECRETS[4]}; ask {SECRETS[5]} or @mkeller. Keller wants the secrets in the "
            "vault, not in shop/config/settings.py.")
    await corrections.change_request(db, run, said, mara, "functional_acceptance")
    [row] = await _signatures(db, project)
    stored = " ".join([row.message, *(item["excerpt"] for item in row.occurrences)])
    for secret in (*SECRETS, "Mara", "Keller", "mkeller"):
        assert secret.lower() not in stored.lower(), secret
    assert "vault" in row.message and row.check_kind == "change_request" and row.kind_hint == "design_change"
    assert row.occurrences[0]["work_item_key"] == "OCX-1" and row.occurrences[0]["run_id"] == run.id


@pytest.mark.asyncio
async def test_repeats_reach_the_threshold_once_and_the_workspace_can_raise_it(db):
    agent_metrics.reset()
    project, _mara, run = await _workspace(db)
    finding = {"dropped": [{"file": "shop/pricing/cart.py", "line": 26, "fix": "Use Decimal for money, not float",
                            "severity": "high", "dropped": "fixed"},
                           {"file": "shop/cart.py", "fix": "still open", "dropped": "out_of_scope"}]}
    for _ in range(3):
        await corrections.review_fixed(db, run, finding, before_tree="t-red", after_tree="t-green")
        await db.commit()
    [row] = await _signatures(db, project)
    assert {key: row.occurrences[0].get(key) for key in ("before_tree", "after_tree", "paths")} == {
        "before_tree": "t-red", "after_tree": "t-green", "paths": ["shop/pricing/cart.py"]}  # the proposal's proof
    assert (await corrections.get_signature(db, row.id))["repeats"] == 3
    assert row.repeats == 3 and row.over_threshold_at is not None and len(row.occurrences) == 3
    assert correction_metrics.CAPTURED.series[("review_fixed",)] == 3
    assert correction_metrics.OVER_THRESHOLD.series[("pattern",)] == 1  # crossed at the second, counted once

    raised, _mara, other = await _workspace(db, check_proposals={"threshold": 3})
    assert corrections.settings(raised)["threshold"] == {"value": 3, "source": "workspace"}
    for _ in range(2):
        await corrections.review_fixed(db, other, finding)
    assert (await _signatures(db, raised))[0].over_threshold_at is None
    assert corrections.settings(project)["threshold"] == {"value": 2, "source": "default"}


@pytest.mark.asyncio
async def test_every_source_keeps_its_correction_and_a_switched_off_source_none(db, monkeypatch):
    project, mara, run = await _workspace(db)
    await corrections.pipeline_red(db, run, style_errors=["shop/cart.py: 412 lines, more than 300"],
                                   failed=["pytest -q exited 1: tests/test_cart.py::test_total failed"],
                                   missing_proofs=["T2 (tests/test_cart.py::test_vat)"], base_errors=[])
    await corrections.refused_call(db, run, "protected_path", "Edit: .env", "Edit: shop/settings.example")

    from app.services.pr_review_bot import seat_choice

    async def linked(_db, _repository, author, _author_id=""):
        return [mara] if author == "mara-gh" else []

    monkeypatch.setattr(seat_choice, "linked_users", linked)
    comment = SimpleNamespace(repository="github:octryx/demo-shop", pr_id="7", comment_id="c1", author="mara-gh",
                              author_id="", body="Please keep the prices in cents as integers here, mara-gh.")
    await corrections.pr_comment(db, project.id, comment)
    await corrections.pr_comment(db, project.id, comment)  # the webhook and the poll: one occurrence
    for body in ("@octryx explain why", "**🔴 High** · F1\n\nUse Decimal", "Octryx: this pull request is closed.",
                 "octryx-e2e nightly 2026-11-19-levers-2: case done",  # the harness posts under a person's login
                 "Merged into main with the whole epic chain in f4ea424."):  # status, no correction
        await corrections.pr_comment(db, project.id, SimpleNamespace(**{**comment.__dict__, "comment_id": body,
                                                                        "body": body}))
    await corrections.pr_comment(db, project.id, SimpleNamespace(**{**comment.__dict__, "author": "stranger",
                                                                    "comment_id": "c9"}))
    rows = await _signatures(db, project)
    kinds = {(row.check_kind, row.kind_hint): row for row in rows}
    assert set(kinds) == {("code_style", "lint_rule"), ("test", "regression_test"), ("proof", "regression_test"),
                          ("refused_call", "platform_rule"), ("pr_comment", "pattern")}
    assert kinds[("code_style", "lint_rule")].file_pattern == "shop/**/*.py"
    comment_row = kinds[("pr_comment", "pattern")]
    assert comment_row.repeats == 1 and "mara" not in comment_row.message.lower()

    off, _mara, quiet = await _workspace(db, check_proposals={"sources": ["review_fixed"]})
    await corrections.refused_call(db, quiet, "protected_path", "Edit: .env", "Edit: shop/settings.example")
    assert await _signatures(db, off) == []
