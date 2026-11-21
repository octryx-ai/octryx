"""The short cited answer on Knowledge Search: only cited sentences over passages the reader may read."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.knowledge.answer import model as answer_model
from app.services.knowledge.answer import service
from app.services.knowledge.answer.prompt import answer_prompt
from app.services.knowledge.answer.validate import cited_sentences
from app.services.knowledge.ledger.errors import EvidenceRecordNotFoundError

SCOPE = SimpleNamespace(primary=SimpleNamespace(project_id="ws-1"))
PASSAGES = {
    "rev-a:1": ("Release guide", "Release 4.1 ships on 12 March."),
    "rev-b:3": ("Ops notes", "Rollbacks need the on-call lead."),
}


class FakeModel:
    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []

    async def json(self, *, system, user):
        self.prompts.append(user)
        return self.answer


def _patch(monkeypatch, model=None, *, hidden=(), unavailable=None):
    read_keys: list[str] = []

    async def scoped_read(db, *, scope, evidence_key, window):
        read_keys.append(evidence_key)
        if evidence_key in hidden or evidence_key not in PASSAGES:
            raise EvidenceRecordNotFoundError()
        title, text = PASSAGES[evidence_key]
        return "ws-1", SimpleNamespace(evidence_key=evidence_key, source_title=title, text=text)

    async def governed(db, *, project_id):
        assert project_id == "ws-1"
        if unavailable:
            raise answer_model.AnswerModelUnavailableError(*unavailable)
        return model

    monkeypatch.setattr(service, "scoped_read", scoped_read)
    monkeypatch.setattr(service, "governed_answer_model", governed)
    return read_keys


async def _answer(keys, query="When does 4.1 ship?"):
    return await service.answer_from_passages(None, scope=SCOPE, query_text=query, evidence_keys=keys)


@pytest.mark.asyncio
async def test_cited_sentences_map_numbers_to_evidence_keys(monkeypatch):
    model = FakeModel({"sentences": [{"text": "4.1 ships on 12 March.", "cites": [1]}]})
    _patch(monkeypatch, model)
    result = await _answer(["rev-a:1", "rev-b:3"])
    assert result == {
        "state": "ok",
        "sentences": [{"text": "4.1 ships on 12 March.", "cites": ["rev-a:1"]}],
        "cited_keys": ["rev-a:1"],
    }
    assert "[1] Release guide" in model.prompts[0] and "[2] Ops notes" in model.prompts[0]


@pytest.mark.asyncio
async def test_a_fabricated_citation_or_an_uncited_sentence_is_dropped(monkeypatch):
    model = FakeModel(
        {
            "sentences": [
                {"text": "Made up from passage seven.", "cites": [7]},
                {"text": "No source at all.", "cites": []},
                {"text": "Rollbacks need the on-call lead.", "cites": [2, 2]},
            ]
        }
    )
    _patch(monkeypatch, model)
    result = await _answer(["rev-a:1", "rev-b:3"])
    assert result["state"] == "ok"
    assert result["sentences"] == [{"text": "Rollbacks need the on-call lead.", "cites": ["rev-b:3"]}]


@pytest.mark.asyncio
async def test_only_fabricated_citations_mean_no_answer(monkeypatch):
    _patch(monkeypatch, FakeModel({"sentences": [{"text": "Invented.", "cites": [3]}]}))
    assert (await _answer(["rev-a:1"]))["state"] == "no_answer"


@pytest.mark.asyncio
async def test_insufficient_passages_mean_no_answer(monkeypatch):
    _patch(monkeypatch, FakeModel({"insufficient": True}))
    assert await _answer(["rev-a:1"]) == {"state": "no_answer", "sentences": [], "cited_keys": []}


@pytest.mark.asyncio
async def test_access_is_checked_again_and_a_hidden_passage_never_reaches_the_model(monkeypatch):
    model = FakeModel({"sentences": [{"text": "Rollbacks need the on-call lead.", "cites": [1]}]})
    _patch(monkeypatch, model, hidden={"rev-a:1"})
    result = await _answer(["rev-a:1", "rev-b:3"])
    # The hidden key is left out, so passage 1 is the readable one and the citation maps to it.
    assert result["cited_keys"] == ["rev-b:3"]
    assert "Release 4.1" not in model.prompts[0]


@pytest.mark.asyncio
async def test_nothing_readable_is_no_answer_without_a_model_call(monkeypatch):
    model = FakeModel({"sentences": [{"text": "x", "cites": [1]}]})
    _patch(monkeypatch, model, hidden={"rev-a:1"})
    assert (await _answer(["rev-a:1", "unknown:1"]))["state"] == "no_answer"
    assert model.prompts == []


@pytest.mark.asyncio
async def test_at_most_ten_passages_are_read(monkeypatch):
    read_keys = _patch(monkeypatch, FakeModel({"insufficient": True}))
    await _answer([f"k{i}:1" for i in range(14)])
    assert len(read_keys) == service.MAX_ANSWER_PASSAGES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("admission", "state"),
    [
        (("needs_configuration", "no_runtime_configured"), "needs_configuration"),
        (("denied", "data_classification"), "denied"),
        (("unavailable", "no_usable_answer"), "unavailable"),
        (("blocked", "something_else"), "unavailable"),
    ],
)
async def test_model_admission_states_are_passed_on(monkeypatch, admission, state):
    _patch(monkeypatch, unavailable=admission)
    assert await _answer(["rev-a:1"]) == {"state": state, "sentences": [], "cited_keys": []}


@pytest.mark.asyncio
async def test_governed_model_needs_a_runtime_and_an_admission(monkeypatch):
    from app.services import control_plane_service

    async def no_runtimes(db):
        return []

    monkeypatch.setattr(control_plane_service, "resolve_control_plane_runtimes", no_runtimes)
    with pytest.raises(answer_model.AnswerModelUnavailableError) as error:
        await answer_model.governed_answer_model(None, project_id="ws-1")
    assert error.value.state == "needs_configuration"

    async def runtimes(db):
        return [{"provider_name": "p", "model": "m"}]

    seen = {}

    async def admit(db, runtimes, *, project_ids, owner):
        seen.update(owner=owner, project_ids=project_ids)
        return SimpleNamespace(allowed=False, state="denied", reason="data_classification")

    monkeypatch.setattr(control_plane_service, "resolve_control_plane_runtimes", runtimes)
    monkeypatch.setattr(answer_model, "admit_runtimes_for_dispatch", admit)
    with pytest.raises(answer_model.AnswerModelUnavailableError) as error:
        await answer_model.governed_answer_model(None, project_id="ws-1")
    assert (error.value.state, error.value.reason) == ("denied", "data_classification")
    assert seen == {"owner": "knowledge_search_answer", "project_ids": "ws-1"}


def test_validation_ignores_malformed_entries():
    keys = ["a:1", "b:1"]
    assert cited_sentences({"sentences": "nope"}, keys) == []
    assert cited_sentences({"sentences": [{"text": " ", "cites": [1]}, {"text": "ok", "cites": [True]}]}, keys) == []
    assert cited_sentences({"sentences": [{"text": "both", "cites": [2, 1]}]}, keys) == [
        {"text": "both", "cites": ["b:1", "a:1"]}
    ]


def test_inline_markers_leave_the_text_and_the_citations_stay():
    keys = ["a:1", "b:1"]
    answer = {"sentences": [{"text": "PostgreSQL 16 is required [1][2].", "cites": [1, 2]}, {"text": "[2]", "cites": [2]}]}
    assert cited_sentences(answer, keys) == [{"text": "PostgreSQL 16 is required.", "cites": ["a:1", "b:1"]}]


def test_prompt_numbers_passages_from_one():
    prompt = answer_prompt("Why?", [("T1", "one"), ("T2", "two")])
    assert prompt.index("[1] T1") < prompt.index("[2] T2")


def test_the_answer_route_is_registered():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/workspaces/{workspace_id}/knowledge/answer" in paths
