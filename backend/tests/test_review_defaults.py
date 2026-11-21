"""The reviewer per engine: Terra for Codex, the installation's admin defaults, and a shallow review flagged
(e.g. 6.6k output tokens for 14 reviews)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.agent_gateway.review_keys import (
    DEFAULT_MODELS,
    SHALLOW_DEFAULTS,
    ReviewPolicyError,
    normalize_installation,
)
from app.services.workflow_runs.review.attempts import shallow_review
from app.services.workflow_runs.review.verdict import Finding, Verdict
from tests.observability_support import admin_user, call_as


def test_codex_is_reviewed_by_terra_and_the_installation_validates_its_defaults():
    assert DEFAULT_MODELS["codex"] == "gpt-6.1-terra"
    stored = normalize_installation({"codex": {"model": "gpt-6-sol", "route": "seat"},
                                     "shallow": {"min_findings": 2}})
    assert stored == {"codex": {"model": "gpt-6-sol", "route": "seat"}, "shallow": {"min_findings": 2}}
    for broken in ({"codex": {"model": "claude-haiku-5-5"}}, {"shallow": {"min_findings": -1}}, {"other": {}}):
        with pytest.raises(ReviewPolicyError):
            normalize_installation(broken)


@pytest.mark.asyncio
async def test_a_large_change_with_a_thin_review_is_flagged_and_a_small_one_never(db):
    thin = Verdict("pass", "ok", ())
    flagged = await shallow_review(db, thin, SimpleNamespace(tokens_out=120, model="gpt-6-luna"), 900)
    assert flagged["below"] == ["findings", "rationale_tokens"] and flagged["limits"] == SHALLOW_DEFAULTS
    assert await shallow_review(db, thin, SimpleNamespace(tokens_out=120, model="m"), 40) is None
    deep = Verdict("changes", "x", (Finding("high", "a.py", 1, "fix it"),))
    assert await shallow_review(db, deep, SimpleNamespace(tokens_out=2400, model="m"), 900) is None


@pytest.mark.asyncio
async def test_the_admin_sets_the_reviewer_per_engine_and_the_review_follows_it(client, db, monkeypatch):
    admin = await admin_user(db)
    answer = await call_as(client, "PUT", "/api/v1/admin/review-defaults", admin,
                           json={"codex": {"model": "gpt-6-sol"}, "shallow": {"min_diff_lines": 50}})
    assert answer.status_code == 200, answer.text
    refused = await call_as(client, "PUT", "/api/v1/admin/review-defaults", admin,
                            json={"codex": {"model": "claude-haiku-5-5"}})
    assert refused.status_code == 400 and refused.json()["reason"] == "review_model_wrong_engine_family"
    shown = (await call_as(client, "GET", "/api/v1/admin/review-defaults", admin)).json()
    assert shown["defaults"]["codex"] == {"model": "gpt-6-sol"} and shown["platform"]["models"] == DEFAULT_MODELS

    from app.services.workflow_runs.review import choice

    async def codex(_db, _run):
        return "codex"

    async def no_workspace(_db, _project, _engine):
        return {}

    monkeypatch.setattr(choice, "run_engine", codex)
    monkeypatch.setattr(choice, "workspace_choice", no_workspace)
    monkeypatch.setattr(choice, "run_route", lambda _run: "company")
    picked = await choice.review_choice(db, SimpleNamespace(project_id=None), {})
    assert (picked.model, picked.model_source) == ("gpt-6-sol", "installation")
    flagged = await shallow_review(db, Verdict("pass", "ok", ()), SimpleNamespace(tokens_out=10, model="m"), 60)
    assert flagged["limits"]["min_diff_lines"] == 50


@pytest.mark.asyncio
async def test_a_fresh_installation_reviews_claude_code_runs_with_sonnet(db, monkeypatch):
    """A fresh installation (no review-defaults, no Workspace or node choice) reviews with claude-sonnet-5-5, not
    claude-haiku-5-5. The platform default is data (``review_models.json``); an admin still changes it through
    review-defaults."""
    import json
    from pathlib import Path

    from app.services.agent_gateway import review_keys
    from app.services.workflow_runs.review import choice

    shipped = json.loads(Path(review_keys.__file__).with_name("review_models.json").read_text())["default_models"]
    assert DEFAULT_MODELS == shipped and shipped["claude_code"] == "claude-sonnet-5-5"

    async def claude(_db, _run):
        return "claude_code"

    async def no_workspace(_db, _project, _engine):
        return {}

    monkeypatch.setattr(choice, "run_engine", claude)
    monkeypatch.setattr(choice, "workspace_choice", no_workspace)
    monkeypatch.setattr(choice, "run_route", lambda _run: "company")
    picked = await choice.review_choice(db, SimpleNamespace(project_id=None), {})  # empty review-defaults
    assert (picked.model, picked.model_source) == ("claude-sonnet-5-5", "platform")
