from __future__ import annotations

from app.models import Project, User, UserProject
from app.models.project.knowledge_graph import KnowledgeGraphEdge, KnowledgeGraphNode
from app.services.mcp_entity_graph_tools import mcp_entity_neighbors, mcp_entity_search


async def _fixture(db):
    user = User(username="graph-user", email="graph@example.test", password_hash="x")
    db.add(user)
    db.add(Project(id="proj-1", name="graph-proj-1", config={}))
    await db.flush()
    db.add(UserProject(user_id=user.id, project_id="proj-1", role="member"))  # the tools read only own Workspaces
    person = KnowledgeGraphNode(
        project_id="proj-1", node_type="person", node_key="test-person", display_name="Test Person",
        trust_level="bronze", status="active",
    )
    repo = KnowledgeGraphNode(
        project_id="proj-1", node_type="repository", node_key="test-repo", display_name="Test Repo",
        trust_level="bronze", status="active",
    )
    db.add(person)
    db.add(repo)
    await db.flush()
    db.add(
        KnowledgeGraphEdge(
            project_id="proj-1", edge_type="authored", source_node_id=person.id, target_node_id=repo.id
        )
    )
    await db.flush()
    return user, person, repo


async def test_entity_search_by_name_and_type(db):
    user, person, _ = await _fixture(db)
    result = await mcp_entity_search(db, user=user, arguments={"query": "test person"})
    assert any(item["id"] == person.id for item in result["items"])
    assert "evidence-based" in result["note"]
    assert result["ranking"] in {"graph_retrieval", "substring_fallback"}
    matched = next(item for item in result["items"] if item["id"] == person.id)
    assert matched["trust_level"] == "bronze"
    typed = await mcp_entity_search(db, user=user, arguments={"query": "test", "node_type": "repository"})
    assert all(item["node_type"] == "repository" for item in typed["items"])


async def test_entity_neighbors_by_key_and_display_name(db):
    user, person, repo = await _fixture(db)
    result = await mcp_entity_neighbors(db, user=user, arguments={"node": "test-person"})
    assert result["entity"]["node_key"] == "test-person"
    assert result["relations"][0]["edge_type"] == "authored"
    assert result["relations"][0]["neighbor"]["id"] == repo.id
    assert result["relations"][0]["trust_level"] == "bronze"
    assert result["relations"][0]["evidence_count"] == 0
    by_name = await mcp_entity_neighbors(db, user=user, arguments={"node": "Test Repo"})
    assert by_name["entity"]["id"] == repo.id
    missing = await mcp_entity_neighbors(db, user=user, arguments={"node": "nope"})
    assert "not found" in missing["error"]


async def test_a_non_member_reads_nothing_of_another_workspaces_graph(db):
    # neither by naming the Workspace nor by searching without one
    _user, person, _repo = await _fixture(db)
    stranger = User(username="graph-stranger", email="stranger@example.test", password_hash="x")
    db.add(stranger)
    await db.flush()
    named = await mcp_entity_search(db, user=stranger, arguments={"project_id": "proj-1", "query": "test person"})
    assert named == {"error": "Workspace not found or not accessible"}
    unnamed = await mcp_entity_search(db, user=stranger, arguments={"query": "test person"})
    assert all(item["id"] != person.id for item in unnamed["items"])
    neighbors = await mcp_entity_neighbors(db, user=stranger, arguments={"node": "test-person"})
    assert "not found" in neighbors["error"]
