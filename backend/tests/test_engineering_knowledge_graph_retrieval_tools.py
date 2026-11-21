from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import CodeRepository, Project, User
from app.services.engineering_knowledge import (
    search_engineering_knowledge_graph,
    upsert_engineering_knowledge_node,
)
from app.time_utils import utc_now
from app.tools.context import ToolContext
from app.tools.definitions import get_all_definitions
from app.tools.registry import TOOL_REGISTRY, execute_tool_with_plugins, get_tool_definitions


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _project(db, name: str) -> Project:
    project = Project(name=name, is_active=True)
    db.add(project)
    await db.flush()
    return project


async def _repo(db, project: Project) -> CodeRepository:
    repo = CodeRepository(
        project_id=project.id,
        name=f"{project.name}-api",
        repo_root=f"/tmp/{project.name}-api",
        provider="local",
        is_active=True,
    )
    db.add(repo)
    await db.flush()
    return repo


async def _seed_visible_nodes(db, admin, project, repo):
    """Seed the global gold baseline, a project silver candidate and a repository failure pattern; return the silver node."""
    await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="spring-boot-4-baseline",
        display_name="Spring Boot 4 baseline",
        summary="Use the project Spring Boot 4 baseline before editing web services.",
        trust_level="gold",
        classification="internal",
        properties={"technology": "spring-boot", "version": "4"},
        source_refs=[{"source_type": "engineering_review", "source_ref": "review-1", "title": "Reviewed baseline"}],
        created_by_user_id=admin.id,
    )
    silver = await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="spring-boot-silver-candidate",
        display_name="Spring Boot silver candidate",
        summary="Candidate guidance only visible when the project allows Silver knowledge.",
        scope_type="project",
        scope_id=project.id,
        trust_level="silver",
        classification="internal",
        source_refs=[{"source_type": "agent_learning", "source_ref": "learning-1"}],
        created_by_user_id=admin.id,
    )
    await upsert_engineering_knowledge_node(
        db,
        node_type="failure_pattern",
        node_key="jenkins-spring-test-failure",
        display_name="Jenkins Spring test failure",
        summary="Retry-free test failure pattern for Spring services.",
        scope_type="repository",
        scope_id=repo.id,
        repository_id=repo.id,
        trust_level="verified",
        classification="internal",
        properties={"pipeline": "jenkins", "repository": repo.name},
        source_refs=[{"source_type": "jenkins", "source_ref": "job/shop/42", "title": "Jenkins failure"}],
        created_by_user_id=admin.id,
    )
    return silver


async def _seed_hidden_nodes(db, other_project) -> None:
    """Seed nodes the search must never return: another project's, restricted, retracted and expired."""
    await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="out-of-scope-spring-guidance",
        display_name="Out of scope Spring guidance",
        summary="This belongs to another project and must not be visible.",
        scope_type="project",
        scope_id=other_project.id,
        trust_level="gold",
        classification="internal",
    )
    await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="restricted-spring-guidance",
        display_name="Restricted Spring guidance",
        summary="Restricted facts must not be exposed to the agent by default.",
        trust_level="gold",
        classification="restricted",
    )
    await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="retracted-spring-guidance",
        display_name="Retracted Spring guidance",
        summary="Retracted facts must not be exposed.",
        status="retracted",
        trust_level="gold",
        classification="internal",
    )
    await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="expired-spring-guidance",
        display_name="Expired Spring guidance",
        summary="Expired facts must not be exposed.",
        trust_level="gold",
        classification="internal",
        valid_until=utc_now() - timedelta(days=1),
    )


async def test_engineering_knowledge_graph_retrieval_enforces_scope_trust_classification_and_validity(db):
    admin = await _admin(db)
    project = await _project(db, "ek-retrieval-risk")
    other_project = await _project(db, "ek-retrieval-other")
    repo = await _repo(db, project)

    silver = await _seed_visible_nodes(db, admin, project, repo)
    await _seed_hidden_nodes(db, other_project)
    await db.commit()

    gold_only = await search_engineering_knowledge_graph(
        db,
        query="spring",
        project_ids=[project.id],
        repository_id=repo.id,
        include_silver=False,
        limit=10,
    )
    keys = {item["node_key"] for item in gold_only["results"]}
    assert "spring-boot-4-baseline" in keys
    assert "jenkins-spring-test-failure" in keys
    assert silver.node_key not in keys
    assert "out-of-scope-spring-guidance" not in keys
    assert "restricted-spring-guidance" not in keys
    assert "retracted-spring-guidance" not in keys
    assert "expired-spring-guidance" not in keys
    assert gold_only["results"][0]["trust_level"] in {"official", "verified", "gold"}
    assert gold_only["results"][0]["evidence"]

    with_silver = await search_engineering_knowledge_graph(
        db,
        query="spring",
        project_ids=[project.id],
        repository_id=repo.id,
        include_silver=True,
        limit=10,
    )
    assert silver.node_key in {item["node_key"] for item in with_silver["results"]}
    assert with_silver["policy"]["include_silver"] is True


async def _seed_cve_and_reviewer_nodes(db, admin, repo) -> None:
    await upsert_engineering_knowledge_node(
        db,
        node_type="vulnerability",
        node_key="CVE-2026-352",
        display_name="CVE-2026-352 Spring Web",
        summary="Upgrade spring-web and verify the Jenkins security pipeline.",
        scope_type="repository",
        scope_id=repo.id,
        repository_id=repo.id,
        trust_level="gold",
        classification="internal",
        properties={"cve": "CVE-2026-352", "affected_package": "spring-web", "severity": "high"},
        source_refs=[{"source_type": "scanner", "source_ref": "scan-352", "title": "SCA finding"}],
        created_by_user_id=admin.id,
    )
    await upsert_engineering_knowledge_node(
        db,
        node_type="reviewer",
        node_key="reviewer-platform-team",
        display_name="Platform Team",
        summary="Reviews Spring Boot and Jenkins pipeline changes.",
        trust_level="verified",
        classification="internal",
        properties={"reviewer": "platform-team", "technology": "spring-boot"},
        source_refs=[{"source_type": "bitbucket", "source_ref": "reviewer-map"}],
        created_by_user_id=admin.id,
    )


def _engineering_tool_context(db, admin, project, repo) -> ToolContext:
    return ToolContext(
        user_id=admin.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id="session-352",
        project_config={
            "project_id": project.id,
            "repository_id": repo.id,
            "engineering_knowledge_policy": {
                "include_silver": False,
                "allowed_classifications": ["public", "internal"],
            },
        },
        db=db,
    )


async def test_agent_engineering_knowledge_tools_are_visible_executable_and_policy_bounded(db):
    admin = await _admin(db)
    project = await _project(db, "ek-tool-risk")
    repo = await _repo(db, project)
    await _seed_cve_and_reviewer_nodes(db, admin, repo)
    await db.commit()

    definitions = get_all_definitions()
    for tool_name in [
        "search_engineering_knowledge",
        "get_repository_patterns",
        "get_vulnerability_fix_knowledge",
        "get_pipeline_failure_patterns",
        "get_reviewer_expertise",
    ]:
        assert tool_name in TOOL_REGISTRY
        assert tool_name in definitions

    exposed = {definition["function"]["name"] for definition in get_tool_definitions("change")}
    assert "get_vulnerability_fix_knowledge" in exposed
    assert "get_reviewer_expertise" in exposed

    context = _engineering_tool_context(db, admin, project, repo)
    vuln = await execute_tool_with_plugins(
        "get_vulnerability_fix_knowledge",
        {"cve": "CVE-2026-352", "repository_id": repo.id, "limit": 5},
        context,
    )
    assert vuln["count"] == 1
    assert vuln["results"][0]["node_key"] == "CVE-2026-352"
    assert vuln["results"][0]["properties"]["affected_package"] == "spring-web"
    assert vuln["results"][0]["evidence"][0]["source_ref"] == "scan-352"
    assert vuln["policy"]["allowed_classifications"] == ["public", "internal"]

    reviewers = await execute_tool_with_plugins(
        "get_reviewer_expertise",
        {"technology": "spring-boot", "limit": 5},
        context,
    )
    assert reviewers["count"] == 1
    assert reviewers["results"][0]["node_key"] == "reviewer-platform-team"
