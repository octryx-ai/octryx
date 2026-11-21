"""Code-context budgets must preserve whole evidence and explicit omissions."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from app.services.code_intelligence.graph_context_selection import ContextCandidate, _select_candidates, _select_edges
from app.services.token_estimation import estimate_serialized_tokens
from app.tools.code_context_compaction import compact_code_context


def candidate(cost: int, name: str = "handler") -> ContextCandidate:
    return ContextCandidate(node=SimpleNamespace(id=name), depth=0,
                            source_chunk={"path": "a.py", "line_start": 1, "line_end": 2, "content": "same"},
                            file_metadata={}, score=(0, 0, 0, name, 0, name), signals=[], context_text="node",
                            estimated_chars=cost)


def test_first_candidate_cannot_bypass_source_budget():
    large, small = candidate(1000), candidate(20, "service")
    selected, omitted = _select_candidates([large, small], budget_chars=500)
    assert selected == [small]
    assert omitted == [large]


def test_duplicate_chunks_are_counted_consistently_with_serialized_candidates():
    selected, omitted = _select_candidates([candidate(300), candidate(300, "service")], budget_chars=500)
    assert len(selected) == len(omitted) == 1
    assert sum(item.estimated_chars for item in selected) <= 500


def test_first_edge_cannot_bypass_remaining_budget():
    edge = SimpleNamespace(source_node_id="a", target_node_id="b", relation="calls", id="e", confidence=1)
    selected, used, omitted = _select_edges([edge], selected_node_ids={"a", "b"}, remaining_chars=0)
    assert (selected, used, omitted) == ([], 0, 1)


def result_fixture():
    chunk = {"path": "a.py", "line_start": 4, "line_end": 6, "content": "4: def handler():\n5:     return service()"}
    return {
        "status": "ready", "repository": {"id": "repo-a", "config": {"token": "excluded"}, "repo_root": "/private/root"},
        "graph": {"run_id": "run-a", "backend": "native", "is_stale": False, "sync": {"huge": "x" * 50000}},
        "start_node": {"id": "a", "name": "handler", "path": "a.py", "line_start": 4},
        "context_nodes": [{"node": {"id": "a", "name": "handler", "path": "a.py", "line_start": 4, "metadata": {"secret": "excluded"}}, "source_chunk": chunk},
                          {"node": {"id": "b", "name": "service", "path": "a.py", "line_start": 8}}],
        "context_files": [{"path": "a.py", "source_chunks": [chunk]}], "source_files": [{"source_chunks": [chunk]}],
        "context_edges": [{"edge": {"source_node_id": "a", "target_node_id": "b", "relation": "calls", "confidence": 1}}],
        "budget": {"omitted_nodes": 0, "omitted_edges": 0},
    }


def test_compaction_retains_cited_code_once_and_connected_symbols_without_mutating_original():
    original = result_fixture()
    before = copy.deepcopy(original)
    packet = compact_code_context(original)
    assert original == before
    assert packet["source_chunks"] == [original["context_nodes"][0]["source_chunk"]]
    assert {item["node"]["name"] for item in packet["context_nodes"]} == {"handler", "service"}
    assert packet["context_edges"][0]["relation"] == "calls"
    assert packet["graph"]["run_id"] == "run-a"
    assert packet["repository"] == {"id": "repo-a"}
    assert packet["truncated"] is False
    assert "excluded" not in json.dumps(packet)
    assert json.dumps(packet).count("return service()") == 1


def test_large_unicode_and_metadata_cannot_expand_packet_or_create_dangling_edges():
    original = result_fixture()
    original["context_nodes"][0]["source_chunk"]["content"] = "界" * 100000
    original["context_nodes"][1]["node"]["name"] = "huge" * 10000
    packet = compact_code_context(original)
    assert len(json.dumps(packet, ensure_ascii=False).encode("utf-8")) <= 6000
    assert estimate_serialized_tokens(packet) <= 1600
    assert packet["truncated"] is True
    assert packet["source_chunks"] == []
    assert packet["context_edges"] == []
    assert packet["omitted"]["chunks"] == 1
    assert packet["omitted"]["nodes"] == 1


def test_oversized_scope_metadata_is_omitted_with_safe_expansion_guidance():
    original = result_fixture()
    for key in ("repository", "graph", "start_node"):
        original[key] = {"id": "界" * 10000, "run_id": "界" * 10000, "name": "界" * 10000}
    packet = compact_code_context(original)
    assert len(json.dumps(packet, ensure_ascii=False).encode("utf-8")) <= 6000
    assert packet["truncated"]
    assert packet["agent_guidance"]


def test_existing_engine_registry_dispatches_code_context_and_explore_compactor():
    from app.agent.engine.messages._engine_tool_compaction import _compact_tool_result_for_model
    for tool in ("code_context", "code_explore"):
        packet = _compact_tool_result_for_model(tool, result_fixture())
        assert packet["context_format"] == "cited_code_packet"
        assert packet["source_chunks"]


def test_model_envelope_survives_existing_budget_and_evidence_contract_without_losing_source():
    from app.services.tool_artifact import build_tool_artifact_envelope, serialize_tool_artifact_envelope
    from app.services.tool_result_compression.budget import enforce_compact_result_budget
    from app.services.tool_result_compression.evidence_contracts import attach_evidence_contract
    original = result_fixture()
    original["graph"]["status"] = "completed"
    packet = compact_code_context(original)
    packet = attach_evidence_contract(tool_name="code_context", original_result=original,
                                     compressed_result=packet, strategy="fallback")
    packet = enforce_compact_result_budget(packet, token_budget=2200)
    assert packet["evidence_contract"]["status"] == "passed"
    assert packet["source_chunks"]
    envelope = build_tool_artifact_envelope(artifact_id="a", tool_name="code_context", payload=packet, include_result=True)
    text = serialize_tool_artifact_envelope(envelope)
    assert len(text.encode("utf-8")) < 9000
    assert estimate_serialized_tokens(envelope) < 3000


def test_absent_whole_source_fails_evidence_contract_instead_of_claiming_answerable_context():
    from app.services.tool_result_compression.evidence_contracts import attach_evidence_contract
    original = result_fixture()
    original["context_nodes"][0]["source_chunk"]["content"] = "x" * 100000
    packet = attach_evidence_contract(tool_name="code_context", original_result=original,
                                     compressed_result=compact_code_context(original), strategy="fallback")
    assert packet["evidence_contract"]["status"] == "failed"
    assert "source_chunks" in packet["evidence_contract"]["missing_paths"]


@pytest.mark.asyncio
async def test_real_graph_query_keeps_handler_service_and_source_locations_in_model_packet(db):
    from app.services.code_intelligence.graph_context import get_code_graph_context
    from tests.code_graph_queries_support import _seed_code_graph
    seeded = await _seed_code_graph(db)
    original = await get_code_graph_context(db=db, repository_id=seeded["repository_id"],
                                           project_id=seeded["project_id"], query="handler", budget_chars=2000)
    packet = compact_code_context(original)
    assert packet["repository"]["id"] == seeded["repository_id"]
    assert packet["graph"]["run_id"]
    assert {item["node"]["name"] for item in packet["context_nodes"]} >= {"handler", "service"}
    assert any("4: def handler()" in chunk["content"] for chunk in packet["source_chunks"])
    assert any(edge["relation"] == "calls" for edge in packet["context_edges"])
    assert len(json.dumps(packet, ensure_ascii=False).encode("utf-8")) <= 6000
    assert estimate_serialized_tokens(packet) <= 1600
