import uuid

from app.models import KnowledgeCodeFile, KnowledgeEvidenceSource, KnowledgeSourceConnector
from app.models.project.knowledge_source_acl import KnowledgeSourceAcl
from app.services.knowledge.access.source_context import authorized_repository_inventory
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace


async def _repository(db, workspace, key, *, hidden=False, remote="https://github.com/example/repository"):
    connector_id, source_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.add(KnowledgeSourceConnector(
        id=connector_id, project_id=workspace, connector_key=key, kind="git_repository",
        scope={"remote": remote, "head_commit": "a" * 40}, state="active",
    ))
    db.add(KnowledgeEvidenceSource(id=source_id, project_id=workspace, source_key=key, display_title=key))
    await db.flush()
    db.add(KnowledgeCodeFile(
        project_id=workspace, connector_id=connector_id, source_id=source_id, path="pom.xml",
        path_digest="b" * 64, blob_sha="c" * 40, commit_sha="a" * 40, last_seen_commit="a" * 40,
    ))
    if hidden:
        db.add(KnowledgeSourceAcl(project_id=workspace, source_key=key, restriction="issue_security_level"))
    await db.flush()


async def test_inventory_respects_workspace_and_source_acl_boundaries(db):
    workspace, foreign = await seed_workspace(db), await seed_workspace(db)
    user = await seed_member(db, workspace_id=workspace, role="member")
    await _repository(db, workspace, "public")
    await _repository(db, workspace, "hidden", hidden=True)
    await _repository(db, foreign, "foreign")
    inventory = await authorized_repository_inventory(
        db, user_id=user, workspace_id=workspace, allowed_project_ids=[workspace],
    )
    assert [item["repository"] for item in inventory] == ["public"]
    assert inventory[0]["commit"] == "a" * 40
    assert await authorized_repository_inventory(
        db, user_id=user, workspace_id=foreign, allowed_project_ids=[workspace],
    ) == []


async def test_inventory_never_exposes_credentialed_remote(db):
    workspace = await seed_workspace(db)
    user = await seed_member(db, workspace_id=workspace)
    await _repository(db, workspace, "bad", remote="https://user:secret@github.com/example/repository")
    assert await authorized_repository_inventory(
        db, user_id=user, workspace_id=workspace, allowed_project_ids=[workspace],
    ) == []
