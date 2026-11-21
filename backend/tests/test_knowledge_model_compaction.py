from app.agent.engine.messages._tool_compaction_registry import resolve_tool_result_compactor
from app.services.tool_result_compression import compress_tool_result_for_model


async def test_actual_model_pipeline_keeps_passages_and_pinned_citations(db):
    url = "https://github.com/example/repository/blob/" + "a" * 40 + "/Controller.java#L1-L30"
    original = {
        "state": "ok", "workspace_id": "w", "result_count": 8,
        "mode_states": {"lexical": "ok"},
        "evidence": [
            {"text": '@GetMapping("/owners/new")\n' + "code line\n" * 400,
             "source_url": url, "citation": "pinned", "evidence_key": f"e{i}", "line_start": 1, "line_end": 30}
            for i in range(8)
        ],
        "facts": {"state": "not_extracted", "items": []},
    }
    compactor = resolve_tool_result_compactor("knowledge_search")
    result = await compress_tool_result_for_model(
        db, session_id="s", tool_name="knowledge_search", result=original,
        fallback=lambda _name, value: compactor(value),
    )
    assert len(result["evidence"]) == 8
    assert result["evidence"][0]["source_url"] == url
    assert '/owners/new' in result["evidence"][0]["text"]
    assert result["evidence"][0]["text_truncated"] is True
    assert result["evidence"][0]["line_end"] == 30
    assert original["evidence"][0]["text"].endswith("code line\n")


def test_closed_knowledge_states_are_preserved():
    compactor = resolve_tool_result_compactor("knowledge_search")
    closed = {"state": "needs_configuration", "reason": "evidence_store_not_configured"}
    assert compactor(closed) == closed
