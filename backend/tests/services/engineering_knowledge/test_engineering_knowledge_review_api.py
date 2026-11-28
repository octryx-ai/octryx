from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, EngineeringKnowledgeGraphNode, User
from app.services.auth import create_access_token, hash_password
from app.services.engineering_knowledge import (
    upsert_engineering_knowledge_edge,
    upsert_engineering_knowledge_node,
)


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _graph_node(db, *, admin_id: str, key: str, trust: str = "bronze") -> EngineeringKnowledgeGraphNode:
    return await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key=key,
        display_name=f"{key} fix pattern",
        summary="Use source-backed evidence before changing repository code.",
        status="active",
        trust_level=trust,
        classification="internal",
        properties={"package": "spring-web", "reviewer": "platform-team"},
        provenance={"source": "agent_learning"},
        source_refs=[
            {
                "source_type": "cicd_failure",
                "source_ref": f"jenkins-{key}",
                "title": "Jenkins failure evidence",
                "url": "https://jenkins.example/job/shop-service/81",
                "observed_at": "2026-06-21T21:00:00Z",
            }
        ],
        aliases=[{"type": "package", "value": "spring-web"}],
        created_by_user_id=admin_id,
    )


async def test_engineering_knowledge_review_queue_filters_and_lifecycle_actions(client, auth_headers, db, auth_user):
    node = await _graph_node(db, admin_id=auth_user.id, key="spring-web-test-slice")
    target = await _graph_node(db, admin_id=auth_user.id, key="spring-web-target", trust="silver")
    await upsert_engineering_knowledge_edge(
        db,
        edge_type="applies_to",
        source_node_id=node.id,
        target_node_id=target.id,
        trust_level="bronze",
        classification="internal",
        source_refs=[{"source_type": "test", "source_ref": "edge-evidence"}],
        created_by_user_id=auth_user.id,
    )
    await db.commit()

    list_response = await client.get(
        "/admin/chat/api/panel/engineering-knowledge/graph/nodes",
        headers=auth_headers,
        params={"query": "spring-web", "trust_level": "bronze", "source": "jenkins", "reviewer": "platform-team"},
    )
    assert list_response.status_code == 200, list_response.text
    payload = list_response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == node.id
    assert payload["items"][0]["source_refs"][0]["source_ref"] == "jenkins-spring-web-test-slice"

    entity_response = await client.get(
        f"/admin/chat/api/panel/engineering-knowledge/graph/entities/{node.id}",
        headers=auth_headers,
    )
    assert entity_response.status_code == 200, entity_response.text
    entity = entity_response.json()
    assert entity["source_refs"][0]["title"] == "Jenkins failure evidence"
    assert entity["related_edges"][0]["related_node"]["id"] == target.id

    promote = await client.post(
        f"/admin/chat/api/panel/engineering-knowledge/graph/nodes/{node.id}/review",
        headers=auth_headers,
        json={"action": "promote", "reason": "Evidence reviewed for reuse.", "trust_level": "gold"},
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["trust_level"] == "gold"
    assert promote.json()["status"] == "active"
    assert promote.json()["properties"]["review_history"][-1]["action"] == "promote"

    reject = await client.post(
        f"/admin/chat/api/panel/engineering-knowledge/graph/nodes/{target.id}/review",
        headers=auth_headers,
        json={"action": "reject", "reason": "Duplicate candidate."},
    )
    assert reject.status_code == 200, reject.text
    assert reject.json()["status"] == "rejected"
    assert reject.json()["trust_level"] == "untrusted"

    retract = await client.post(
        f"/admin/chat/api/panel/engineering-knowledge/graph/nodes/{node.id}/review",
        headers=auth_headers,
        json={"action": "retract", "reason": "Superseded by official pack."},
    )
    assert retract.status_code == 200, retract.text
    assert retract.json()["status"] == "retracted"

    audits = (
        await db.execute(
            select(AuditLog).where(AuditLog.resource_type == "engineering_knowledge_graph").order_by(AuditLog.created_at)
        )
    ).scalars().all()
    assert "engineering_knowledge_graph.node_promote" in [audit.action for audit in audits]
    assert "engineering_knowledge_graph.node_reject" in [audit.action for audit in audits]
    assert "engineering_knowledge_graph.node_retract" in [audit.action for audit in audits]


async def test_engineering_knowledge_quality_panel_reports_gate_metrics(client, auth_headers, db, auth_user):
    await _graph_node(db, admin_id=auth_user.id, key="quality-panel-node", trust="gold")
    await db.commit()

    response = await client.get("/admin/chat/api/panel/engineering-knowledge/quality?limit=10", headers=auth_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["quality"]["evaluated_count"] >= 1
    assert "status_counts" in payload
    assert payload["usage"]["retrieval_miss_instrumented"] is False
    assert any(item["key"] == "vulnerability_fix" for item in payload["evaluation_scenarios"])


async def test_engineering_knowledge_review_blocks_non_admin(client, db):
    user = User(
        username="knowledge-review-viewer",
        email="knowledge-review-viewer@example.com",
        password_hash=hash_password("testpass123"),
        display_name="Knowledge Review Viewer",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    admin = await _admin(db)
    node = await _graph_node(db, admin_id=admin.id, key="non-admin-denied")
    await db.commit()

    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}
    list_response = await client.get("/admin/chat/api/panel/engineering-knowledge/graph/nodes", headers=headers)
    action_response = await client.post(
        f"/admin/chat/api/panel/engineering-knowledge/graph/nodes/{node.id}/review",
        headers=headers,
        json={"action": "promote", "reason": "should fail"},
    )

    assert list_response.status_code == 403
    assert action_response.status_code == 403
