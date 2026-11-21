"""Evidence carries its origin link from upload to citation (a source with an openable URL)."""

from __future__ import annotations

import pytest

from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from app.services.knowledge.sources.source_url import normalize_source_url
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

PAGE = "https://confluence.example.test/wiki/spaces/RIVER/pages/123456/Failover+Runbook?pageVersion=7"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (PAGE, PAGE),
        ("HTTPS://docs.example.test/spec-2.2.0.pdf", "https://docs.example.test/spec-2.2.0.pdf"),
        (None, None),
        ("   ", None),
    ],
)
def test_accepted_links(raw, expected) -> None:
    assert normalize_source_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:secret@confluence.example.test/page",
        "https://confluence.example.test/a b",
        "https://confluence.example.test/\x00",
        "https:///no-host",
        "https://confluence.example.test:99999/",
        "https://example.test/" + "x" * 2048,
        42,
    ],
)
def test_refused_links(raw) -> None:
    with pytest.raises(InvalidEvidenceRequestError):
        normalize_source_url(raw)


@pytest.mark.asyncio
async def test_a_citation_carries_the_revisions_source_url(db) -> None:
    from app.services.knowledge.access.authorization import authorize_workspace

    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()

    await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="failover-runbook",
        display_title="Failover Runbook",
        declared_media_type="text/markdown",
        data=b"Failover runs from Geneva when Zurich is down.\n",
        created_by=user_id,
        source_url=PAGE,
    )
    await EvidenceProjector(runtime).project_once(db, worker_id="test")
    result = await retrieve_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="failover Geneva")

    assert [(item.source_title, item.source_url) for item in result.evidence] == [("Failover Runbook", PAGE)]


def test_chat_turns_are_offered_the_evidence_search_and_told_to_link_the_source() -> None:
    """The link only reaches a person if the model sees the tool and cites with it."""
    from app.agent.core.context.tool_families import GOVERNED_KNOWLEDGE_TOOLS
    from app.tools.definitions import get_all_definitions, get_tool_definition_metadata

    assert get_tool_definition_metadata("knowledge_search").is_core
    assert "knowledge_search" in GOVERNED_KNOWLEDGE_TOOLS
    description = get_all_definitions()["knowledge_search"]["function"]["description"]
    assert "cite_as" in description
    assert "never invent or guess a URL" in description


def test_the_knowledge_workflow_surface_allows_the_evidence_search() -> None:
    """The Knowledge request family answers from the governed ledger."""
    from app.agent.core.context.turn_tool_surface import resolve_workflow_tool_surface
    from app.services.workflow_contracts.registry import get_workflow_definition

    surface = resolve_workflow_tool_surface(workflow_id="knowledge_request", workflow_contract=None)
    assert {"knowledge_search", "knowledge_read", "knowledge_changes", "memory_recall"} <= set(surface)
    assert not {"knowledge_get", "list_project_knowledge"} & set(surface)
    assert "knowledge_search" in get_workflow_definition("knowledge_request").phases[0].preferred_tools


def _planned(calls: list[dict]) -> list[tuple[str, dict]]:
    import json

    return [(call["function"]["name"], json.loads(call["function"]["arguments"])) for call in calls]


def test_the_knowledge_plan_is_one_governed_evidence_search_and_never_the_legacy_map() -> None:
    from app.services.workflow_contracts.knowledge_request import plan_knowledge_request

    contract = {"workflow_id": "knowledge_request", "source_user_message": "When does the failover drill run?"}
    allowed = {"knowledge_search", "knowledge_get"}

    first = _planned(
        plan_knowledge_request(contract, turn_tool_history=[], covered_evidence_axes=None, allowed_tool_names=allowed)
    )
    assert first == [("knowledge_search", {"query": "When does the failover drill run", "limit": 8})]

    # Passages or none: the plan ends; an empty result is answered as "nothing documented".
    for evidence in ([{"text": "x"}], []):
        history = [{"tool_name": "knowledge_search", "result": {"state": "ok", "evidence": evidence}}]
        assert (
            plan_knowledge_request(
                contract, turn_tool_history=history, covered_evidence_axes=None, allowed_tool_names=allowed
            )
            == []
        )
