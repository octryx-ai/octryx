"""Code impact over MCP: cited facts from client files or the session-bound snapshot with blob links, scoped to the connection's Workspace, and verified snapshot uploads that refuse credentials."""

from __future__ import annotations

import base64
import hashlib
import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Project
from app.models.project.knowledge_source_sync import KnowledgeSourceSyncItem
from app.services.knowledge.code import service as code_service
from app.services.knowledge.ledger.citations import ResolvedCitation
from app.services.knowledge.sources.repository_snapshot.binding import bind_session_repository
from app.services.knowledge.sources.repository_snapshot.policy import set_local_snapshots_allowed
from app.services.knowledge.sources.repository_snapshot.snapshot_complete import complete_snapshot_pass
from app.services.knowledge.sources.repository_snapshot.snapshot_files import git_blob_sha1, upload_snapshot_files
from app.services.knowledge.sources.repository_snapshot.upload import open_snapshot_pass
from app.services.knowledge.temporal.change_types import ACTION_REQUIRED_TYPES
from app.services.knowledge.temporal.changes import STATE_OK
from app.services.knowledge.temporal.changes_facts import ChangeFact, ChangesResult
from app.services.mcp_governed_knowledge import run_governed_mcp_tool
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.knowledge_evidence_text_support import unfenced
from tests.knowledge_runtime_support import set_evidence_runtime
from tests.mcp_claude_code_parity_support import SCOPES, _caller, _gateway_session, _native
from tests.mcp_native_support import mcp_call, native_token

ORIGIN = "https://octryx.example.test"


HEAD = "b26f235250627a235a2974a22f2317dbef27338d"


GUIDE = "https://docs.spring.io/spring-boot/upgrading.html"


POM = b"<project>\n  <properties>\n    <java.version>11</java.version>\n  </properties>\n</project>\n"


JAVA = b"package demo;\nimport org.springframework.boot.jackson.JsonComponent;\n@JsonComponent\nclass Json {}\n"


FILES = {"pom.xml": POM, "src/main/java/demo/Json.java": JAVA}


@pytest.fixture
def evidence_runtime():
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, evidence_index
    finally:
        set_evidence_runtime(None)


@pytest.fixture
def change_facts(monkeypatch):
    citation = ResolvedCitation(
        evidence_key="a" * 32 + ":1", citation="Upgrade guide (rev 1)", revision_id="r", span_ordinal=1,
        object_bucket="b", object_key="k", content_sha256="0" * 64, source_title="Spring Boot upgrade guide",
        source_url=GUIDE,
    )
    relation = sorted(ACTION_REQUIRED_TYPES)[0]
    facts = (
        ChangeFact(relation, "@JsonComponent has been renamed to @JacksonComponent", "", "", "4.0", citation, 1),
        ChangeFact(relation, "Spring Boot 4.0 requires Java 17 or later", "", "", "4.0", citation, 1),
    )

    async def scoped(db, *, runtime, scope, product, **options):
        return scope.primary.project_id, ChangesResult(STATE_OK, "spring-boot", "3.5", "4.0", ("4.0",), facts, 1)

    monkeypatch.setattr(code_service, "scoped_changes", scoped)


@pytest.fixture
def public_origin(monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_public_origin", ORIGIN)


async def _snapshot(db, *, user_id: str, workspace_id: str, session, dirty: bool = False):
    bound = await bind_session_repository(
        db, session=session, user_id=user_id, workspace_id=workspace_id,
        payload={"remote_url": "git@github.com:spring-projects/spring-petclinic.git", "head_commit": HEAD,
                 "head_dirty": dirty, "head_pushed": True, "branch": "main"},
    )
    manifest = [{"path": path, "blob_sha": git_blob_sha1(data), "size": len(data)} for path, data in FILES.items()]
    manifest += [{"path": ".env", "blob_sha": "c" * 40, "size": 10}]
    opened = await open_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=user_id,
        payload={"head_commit": HEAD, "files": manifest},
    )
    if not isinstance(opened, dict):
        return bound, opened, None, None
    files = [
        {"path": path, "blob_sha": git_blob_sha1(data), "content_base64": base64.b64encode(data).decode()}
        for path, data in FILES.items()
        if path in opened["wanted"]
    ]
    uploaded = await upload_snapshot_files(
        db, session=session, workspace_id=workspace_id, user_id=user_id, payload={"head_commit": HEAD, "files": files}
    ) if files else {"results": []}
    completed = await complete_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=user_id, payload={"head_commit": HEAD}
    )
    await db.commit()
    return bound, opened, uploaded, completed


async def test_code_impact_from_client_files_is_cited_and_scoped_to_the_connection_workspace(
    db, monkeypatch, evidence_runtime, change_facts
):
    _native(db, monkeypatch)
    workspace_id = await seed_workspace(db)
    other_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    token = await native_token(db, user_id=member_id, scopes=list(SCOPES))
    files = [{"path": path, "content": data.decode()} for path, data in FILES.items()]
    arguments = {"product": "spring-boot", "to_version": "4.0", "from_version": "3.5", "files": files}

    result = await mcp_call(token, "knowledge_code_impact", arguments, {"X-Octryx-Workspace": workspace_id})

    assert result["state"] == "ok", result
    assert (result["codebase"], result["files"], result["commit"], result["session_bound"]) == (
        "client_files", 2, None, False
    )
    hits = {item["fact"]: item for item in unfenced(result["impact"])}
    assert hits["@JsonComponent has been renamed to @JacksonComponent"]["at"] == [
        "src/main/java/demo/Json.java:2 org.springframework.boot.jackson.JsonComponent",
        "src/main/java/demo/Json.java:3 JsonComponent",
    ]
    assert hits["Spring Boot 4.0 requires Java 17 or later"]["at"] == ["pom.xml:3 java.version"]
    assert result["sources"] == [{"id": "S1", "cite_as": f"[Spring Boot upgrade guide]({GUIDE})"}]
    assert all(item["source"] == "S1" for item in result["impact"])

    foreign = await mcp_call(token, "knowledge_code_impact", arguments, {"X-Octryx-Workspace": other_id})
    assert foreign["state"] == "not_found"
    unscoped = await mcp_call(token, "knowledge_code_impact", arguments)
    assert unscoped["state"] == "needs_configuration"

    caller = _caller(member_id, workspace_id)
    both = await run_governed_mcp_tool(
        db, caller=caller, tool_name="knowledge_code_impact", arguments={**arguments, "repository": "repo-x"}
    )
    assert (both["state"], both["reason"]) == ("invalid_request", "files_and_repository")
    unscanned = await run_governed_mcp_tool(
        db, caller=caller, tool_name="knowledge_code_impact",
        arguments={**arguments, "files": [{"path": "README.md", "content": "hi"}]},
    )
    assert (unscanned["state"], unscanned["reason"]) == ("invalid_request", "file_class_not_scanned")
    server_path = await run_governed_mcp_tool(
        db, caller=caller, tool_name="knowledge_code_impact", arguments={**arguments, "path": "/srv"}
    )
    assert (server_path["state"], server_path["reason"]) == ("invalid_request", "path_not_available_over_mcp")
    nothing = await run_governed_mcp_tool(
        db, caller=caller, tool_name="knowledge_code_impact", arguments={"product": "spring-boot", "to_version": "4.0"}
    )
    assert (nothing["state"], nothing["reason"]) == ("needs_configuration", "no_repository_source")

    project = await db.get(Project, workspace_id)
    project.config = {"tool_policy": {"denylist": ["knowledge_code_impact"]}}
    await db.commit()
    denied = await run_governed_mcp_tool(db, caller=caller, tool_name="knowledge_code_impact", arguments=arguments)
    assert (denied["state"], denied["reason"]) == ("denied", "tool_denied_by_project_policy")


async def test_code_impact_answers_the_session_bound_snapshot_with_blob_links(
    db, evidence_runtime, change_facts, public_origin
):
    runtime, evidence_index = evidence_runtime
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    admin_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    session_key = str(uuid.uuid4())
    session = await _gateway_session(db, member_id, workspace_id, session_key)
    bound, opened, _, _ = await _snapshot(db, user_id=member_id, workspace_id=workspace_id, session=session)
    assert bound["state"] == "bound"
    assert bound["snapshot"] == {"state": "denied", "reason": "local_snapshots_not_allowed"}
    assert opened == type(opened)("denied", "local_snapshots_not_allowed")

    await set_local_snapshots_allowed(db, workspace_id, allowed=True, actor_id=admin_id)
    await db.commit()
    bound, opened, uploaded, completed = await _snapshot(
        db, user_id=member_id, workspace_id=workspace_id, session=session
    )
    assert bound["binding"]["links"] == "host" and bound["snapshot"]["state"] == "allowed"
    assert sorted(opened["wanted"]) == sorted(FILES)
    assert opened["skipped"] == [{"path": ".env", "reason": "skipped_sensitive_path"}]
    assert [item["outcome"] for item in uploaded["results"]] == ["ingested", "ingested"]
    assert completed == {"state": "indexed", "files_indexed": 2, "files_new": 2, "files_removed": 0, "missing": 0}
    markers = (await db.execute(select(KnowledgeSourceSyncItem.version_marker))).scalars().all()
    assert sorted(markers) == sorted(git_blob_sha1(data) for data in FILES.values())

    caller = _caller(member_id, workspace_id, session_key=session_key)
    arguments = {"product": "spring-boot", "to_version": "4.0"}
    result = await run_governed_mcp_tool(db, caller=caller, tool_name="knowledge_code_impact", arguments=arguments)
    assert result["state"] == "ok", result
    assert (result["codebase"], result["commit"], result["session_bound"]) == ("workspace_repository", HEAD, True)
    pom = next(item for item in unfenced(result["impact"]) if item["at"] == ["pom.xml:3 java.version"])
    assert pom["links"] == [f"https://github.com/spring-projects/spring-petclinic/blob/{HEAD}/pom.xml#L3"]

    _, opened, _, completed = await _snapshot(
        db, user_id=member_id, workspace_id=workspace_id, session=session, dirty=True
    )
    assert opened["wanted"] == [] and opened["unchanged"] == 2 and completed["files_new"] == 0
    dirty = await run_governed_mcp_tool(db, caller=caller, tool_name="knowledge_code_impact", arguments=arguments)
    pom = next(item for item in unfenced(dirty["impact"]) if item["at"] == ["pom.xml:3 java.version"])
    connector_key = dirty["repository"]["key"]
    assert pom["links"] == [
        f"{ORIGIN}/api/v1/workspaces/{workspace_id}/knowledge/repositories/{connector_key}/blob/{HEAD}/pom.xml"
        f"?blob={git_blob_sha1(POM)}#L3"
    ]


async def test_snapshot_uploads_verify_the_blob_and_refuse_credentials(db, evidence_runtime):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    admin_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    await set_local_snapshots_allowed(db, workspace_id, allowed=True, actor_id=admin_id)
    session = await _gateway_session(db, member_id, workspace_id, str(uuid.uuid4()))
    secret = await bind_session_repository(
        db, session=session, user_id=member_id, workspace_id=workspace_id,
        payload={"remote_url": "https://user:tok@github.com/o/r.git", "head_commit": HEAD},
    )
    assert (secret.state, secret.reason) == ("denied", "remote_url_has_credentials")
    await bind_session_repository(
        db, session=session, user_id=member_id, workspace_id=workspace_id,
        payload={"remote_url": "https://github.com/o/r.git", "head_commit": HEAD},
    )
    blob = git_blob_sha1(POM)
    await open_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=member_id,
        payload={"head_commit": HEAD, "files": [{"path": "pom.xml", "blob_sha": blob, "size": len(POM)}]},
    )
    tampered = await upload_snapshot_files(
        db, session=session, workspace_id=workspace_id, user_id=member_id,
        payload={"head_commit": HEAD, "files": [
            {"path": "pom.xml", "blob_sha": blob, "content_base64": base64.b64encode(POM + b"x").decode()}
        ]},
    )
    assert tampered["results"] == [{"path": "pom.xml", "outcome": "skipped", "reason": "blob_sha_mismatch"}]
    incomplete = await complete_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=member_id, payload={"head_commit": HEAD}
    )
    assert (incomplete["state"], incomplete["missing"]) == ("incomplete", 1)
    other_head = await open_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=member_id,
        payload={"head_commit": "d" * 40, "files": []},
    )
    assert (other_head.state, other_head.reason) == ("denied", "head_commit_mismatch")
    assert git_blob_sha1(b"") == hashlib.sha1(b"blob 0\x00", usedforsecurity=False).hexdigest()
