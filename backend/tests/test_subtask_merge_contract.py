import uuid

from app.models import Session, ToolCall
from app.services.subtask_merge_contract import build_subtask_merge_contract, persist_subtask_merge_contract


def _session(session_id: str, *, status: str = "completed", metadata: dict | None = None) -> Session:
    return Session(
        id=session_id,
        user_id="u1",
        status=status,
        agent_type="coding",
        metadata_=metadata or {},
        sub_agent_depth=1,
    )


def test_subtask_merge_contract_marks_disjoint_children_merge_ready():
    parent = _session("parent", metadata={"title": "Parent"})
    child_a = _session("child-a", metadata={"title": "A", "delegated_write_areas": ["backend/app/a"]})
    child_b = _session("child-b", metadata={"title": "B", "delegated_write_areas": ["frontend/chat/src/b"]})

    contract = build_subtask_merge_contract(
        parent_session=parent,
        child_sessions=[child_a, child_b],
        accepted_subthreads=[{"session_id": child_a.id}, {"session_id": child_b.id}],
        rejected_subthreads=[],
        tool_calls_by_session={},
    )

    assert contract["status"] == "merge_ready"
    assert contract["requires_review"] is False
    assert contract["conflicts"] == []
    assert contract["tasks"][0]["ownership_known"] is True

    persist_subtask_merge_contract(parent, contract)
    assert parent.metadata_["subtask_merge_contract"]["status"] == "merge_ready"


def test_subtask_merge_contract_blocks_overlapping_changed_files():
    parent = _session("parent", metadata={"title": "Parent"})
    child_a = _session("child-a", metadata={"title": "A"})
    child_b = _session("child-b", metadata={"title": "B"})
    tool_calls = {
        child_a.id: [
            ToolCall(
                id=str(uuid.uuid4()),
                session_id=child_a.id,
                tool_name="write_workspace_file",
                result={"workspace_change_safety_contract": {"changed_files": ["backend/app/service.py"]}},
                status="success",
            )
        ],
        child_b.id: [
            ToolCall(
                id=str(uuid.uuid4()),
                session_id=child_b.id,
                tool_name="write_workspace_file",
                result={"workspace_change_safety_contract": {"changed_files": ["backend/app/service.py"]}},
                status="success",
            )
        ],
    }

    contract = build_subtask_merge_contract(
        parent_session=parent,
        child_sessions=[child_a, child_b],
        accepted_subthreads=[{"session_id": child_a.id}, {"session_id": child_b.id}],
        rejected_subthreads=[],
        tool_calls_by_session=tool_calls,
    )

    assert contract["status"] == "blocked_conflicts"
    assert contract["requires_review"] is True
    assert contract["conflict_count"] == 1
    assert contract["conflicts"][0]["type"] == "changed_file_overlap"
    assert contract["conflicts"][0]["child_session_ids"] == ["child-a", "child-b"]
