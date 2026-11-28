"""Code-context budgets must preserve whole evidence and explicit omissions."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.code_intelligence.graph_context_selection import ContextCandidate, _select_candidates, _select_edges


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














