"""The draft of a proposed check: the drafting model sees redacted excerpts only (never a secret), the cheapest check
the stack offers, and a draft without a valid rule or without its "instead" is refused and asked once more."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.check_proposals.draft import checked, task, write_draft

TOKEN = "ghp_" + "A" * 36
SIGNATURE = {"id": "sig_1", "message": "a list as a default argument", "file_pattern": "shop/**/*.py",
             "occurrences": [{"source": "review_fixed", "excerpt": f"def total(items=[]):  # token={TOKEN}",
                              "paths": ["shop/pricing.py"]},
                             {"source": "pipeline_cause", "excerpt": "Authorization: Bearer abc.def.ghi"}]}
GOOD = {"kind": "lint_rule", "stack": "python", "rule": {"tool": "ruff", "rule_id": "B006"},
        "summary": "A mutable default argument.",
        "message": {"what": "a list as default", "why": "shared between calls", "instead": "default to None"}}


class _Model:
    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    async def answer(self, *, system, user):
        self.asked.append(user)
        return SimpleNamespace(answer=self.answers.pop(0))


def test_the_drafting_model_never_sees_a_secret():
    prompt = task(SIGNATURE, "python")
    assert TOKEN not in prompt and "abc.def.ghi" not in prompt
    assert "def total(items=[])" in prompt and '"tool": "ruff"' in prompt and "shop/pricing.py" in prompt


@pytest.mark.asyncio
async def test_a_draft_without_its_instead_is_asked_once_more_with_the_reason():
    model = _Model({**GOOD, "message": {"what": "x", "why": "y"}}, GOOD)
    found, problem = await write_draft(model, SIGNATURE, "python")
    assert problem == "" and found["draft"] == {"kind": "lint_rule", "lands_in": "code_style:stack:python",
                                                "stack": "python", "rule": {"tool": "ruff", "rule_id": "B006"},
                                                "summary": "A mutable default argument."}
    assert "instead" in model.asked[1]  # the second answer was told why the first was refused
    nothing, why = await write_draft(_Model({**GOOD, "kind": "x"}, {**GOOD, "kind": "x"}), SIGNATURE, "python")
    assert nothing is None and "kind is one of" in why


@pytest.mark.parametrize(("answer", "error"), [
    ({**GOOD, "rule": {"tool": "ruff", "rule_id": "rm -rf"}}, "valid rule_id"),
    ({**GOOD, "rule": {"tool": "eslint", "rule_id": "B006"}}, r"linter \(ruff\)"),
    ({**GOOD, "kind": "pattern", "rule": {"tool": "ast-grep", "rule": {}}}, "ast-grep rule object"),
    ({**GOOD, "summary": ""}, "summary"),
])
def test_an_invalid_draft_names_what_is_wrong(answer, error):
    with pytest.raises(ValueError, match=error):
        checked(answer, "python")


def test_flutter_offers_its_linter_only_no_pattern():
    with pytest.raises(ValueError, match="stack that offers patterns"):
        checked({**GOOD, "stack": "flutter", "kind": "pattern",
                 "rule": {"tool": "ast-grep", "rule": {"pattern": "x"}}}, "flutter")
    assert checked({**GOOD, "rule": {"tool": "dart", "rule_id": "avoid_print"}}, "flutter")["draft"]["lands_in"] == \
        "code_style:stack:flutter"


@pytest.mark.asyncio
async def test_the_worker_drafts_a_new_proposal_with_the_newest_run_s_review_model(db, monkeypatch):
    from app.services.check_proposals import signature_updated, worker
    from tests.knowledge_evidence_seed_support import seed_workspace

    workspace_id = await seed_workspace(db)
    signature = {**SIGNATURE, "workspace_id": workspace_id, "kind_hint": "lint_rule",
                 "occurrences": [{**item, "run_id": "run-1", "at": "2026-11-20T01:00:00"}
                                 for item in SIGNATURE["occurrences"]]}
    proposal = await signature_updated(db, signature)
    await db.commit()

    async def model_for(_db, _run, _factory):
        return _Model(GOOD)

    async def signature_of(_db, _id):
        return signature

    monkeypatch.setattr(worker, "_model_for", model_for)
    real_get = db.get

    async def get(model, ident):
        return SimpleNamespace(id=ident, project_id=workspace_id) if ident == "run-1" else await real_get(model, ident)

    monkeypatch.setattr(db, "get", get)
    assert await worker.draft_due(db, signature_of=signature_of) == 1
    await db.refresh(proposal)
    assert proposal.draft["rule"] == {"tool": "ruff", "rule_id": "B006"}
    assert proposal.message["instead"] == "default to None"
    assert worker.stack_of({"occurrences": [{"paths": ["lib/x.dart"]}]}) == "flutter"
