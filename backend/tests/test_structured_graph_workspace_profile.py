"""A Workspace's own structured profile: validated, versioned, audited, built and read under its id."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.models.project.knowledge_structured import KnowledgeStructuredBuild, KnowledgeStructuredNode
from app.services.auth import create_access_token
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import TRIGGER_MANUAL
from app.services.knowledge.structured.manual import extract_manual
from app.services.knowledge.structured.profile import default_profile_document, parse_profile, structured_profile
from app.services.knowledge.structured.profile_types import StructuredProfileError
from app.services.knowledge.structured.status import structured_status
from app.services.knowledge.structured.workspace_profile import (
    AUDIT_ACTION,
    MAX_DOCUMENT_BYTES,
    profile_settings,
    save_workspace_profile,
    validate_document,
    workspace_profile,
    workspace_profile_id,
)
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.structured_graph_support import seed_parsed_revision, span

DEFAULT_ID = structured_profile().profile_id
DEFAULT_HEADERS = [
    span(1, "4.1 General settings\n\nThe server is configured in app.ini.", page=10,
         section=["4.1 General settings"]),
    span(2, "[GeneralSettings] Parameter | Default value | Description\nThreadCount | 4 | Number of threads.",
         kind="table", page=10, section=["4.1 General settings"]),
]
CUSTOM = [
    span(1, "4.1 Settings\n\nThe server reads app.ini.", page=10, section=["4.1 Settings"]),
    span(2, "[GeneralSettings] Parameter | Factory preset | Explanation\nQueueSize | 100 | Queue length.",
         kind="table", page=10, section=["4.1 Settings"]),
]


def _parameters(extraction) -> dict[str, dict]:
    return {node.label: node.properties for ref, node in extraction.nodes.items() if ref.node_type == "Parameter"}


def _with_header(document: dict, header: str) -> dict:
    changed = copy.deepcopy(document)
    changed["manual"]["default_headers"].append(header)
    return changed


def test_the_default_reads_its_table_headers():
    found = _parameters(extract_manual(DEFAULT_HEADERS, structured_profile(), document_key="en", title="Manual"))
    assert found["[GeneralSettings] ThreadCount"]["default"] == "4"
    assert "Default value" in default_profile_document()["manual"]["default_headers"]
    assert "Description" in default_profile_document()["manual"]["description_headers"]


def test_a_workspace_document_is_validated_with_the_default_schema():
    document = default_profile_document()
    assert parse_profile(document).profile_id == DEFAULT_ID
    assert validate_document(document, revision=3).profile_id == f"{DEFAULT_ID}-w3"
    missing = copy.deepcopy(document)
    del missing["manual"]["units"]
    with pytest.raises(StructuredProfileError, match="exactly the fields"):
        validate_document(missing)
    unsafe = copy.deepcopy(document)
    unsafe["operations"]["ticket_patterns"]["Incident"] = "(\\w+\\s?)*INC"
    with pytest.raises(StructuredProfileError, match="backtrack"):
        validate_document(unsafe)
    long_pattern = copy.deepcopy(document)
    long_pattern["configuration"]["variant_patterns"] = ["(?P<base>x)(?P<variant>y)" + "z" * 400]
    with pytest.raises(StructuredProfileError, match="too long"):
        validate_document(long_pattern)
    bad_type = copy.deepcopy(document)
    bad_type["operations"]["ticket_patterns"] = {"incident ticket": "INC[0-9]+"}
    with pytest.raises(StructuredProfileError, match="CamelCase"):
        validate_document(bad_type)
    long_key = {**copy.deepcopy(document), "key": "a" * 31}
    with pytest.raises(StructuredProfileError, match="too long"):
        validate_document(long_key, revision=12345)
    huge = copy.deepcopy(document)
    huge["manual"]["units"] = {f"unit{index}": "x" * 40 for index in range(2000)}
    with pytest.raises(StructuredProfileError, match=str(MAX_DOCUMENT_BYTES)):
        validate_document(huge)
    with pytest.raises(StructuredProfileError, match="JSON object"):
        validate_document(["not", "an", "object"])


async def _admin(db, project_id: str):
    user = await fetch_user(db, await seed_member(db, workspace_id=project_id, role="admin"))
    return user, await authorize_workspace(db, current_user=user, workspace_id=project_id)


async def test_saving_versions_and_audits_and_a_reset_returns_to_the_default(db):
    project_id = await seed_workspace(db)
    user, _ = await _admin(db, project_id)
    assert await workspace_profile_id(db, project_id) == DEFAULT_ID
    first = await save_workspace_profile(db, project_id, document=_with_header(default_profile_document(), "Factory preset"),
                                         actor_id=user.id)
    assert first.revision == 1 and first.profile_id == f"{DEFAULT_ID}-w1"
    profile = await workspace_profile(db, project_id)
    assert profile.profile_id == f"{DEFAULT_ID}-w1" and "factorypreset" in profile.default_headers
    assert await workspace_profile_id(db, project_id) == f"{DEFAULT_ID}-w1"
    second = await save_workspace_profile(db, project_id, document=None, actor_id=user.id)
    assert second.revision == 2 and await workspace_profile_id(db, project_id) == DEFAULT_ID
    assert (await workspace_profile(db, project_id)).profile_id == DEFAULT_ID
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION)
                               .order_by(AuditLog.created_at))).scalars().all()
    assert [entry.details["revision"] for entry in audits] == [1, 2]
    assert audits[0].details["changed_sections"] == ["manual"] and audits[0].details["reset"] is False
    assert audits[1].details["reset"] is True and audits[1].details["profile_id"] == DEFAULT_ID
    assert "Factory preset" not in repr([entry.details for entry in audits])  # never the document itself
    settings = await profile_settings(db, project_id, may_author=True)
    assert settings["source"] == "default" and [item["revision"] for item in settings["history"]] == [2, 1]
    assert settings["history"][0]["reset"] is True and settings["document"] == default_profile_document()


async def _build(db, project_id: str) -> KnowledgeStructuredBuild:
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id="w") == build.id
    assert await run_build_slice(db, runtime=None, build_id=build.id, worker_id="w") == "completed"
    await db.refresh(build)
    return build


async def test_a_build_extracts_with_the_workspace_profile_and_readers_see_only_its_graph(db):
    project_id = await seed_workspace(db)
    user, authorized = await _admin(db, project_id)
    await seed_parsed_revision(db, project_id, source_key="manual", title="Manual", spans=CUSTOM)
    await _build(db, project_id)
    labels = set((await db.execute(select(KnowledgeStructuredNode.label).where(
        KnowledgeStructuredNode.node_type == "Parameter"))).scalars())
    assert "[GeneralSettings] QueueSize" not in labels  # the default does not know "Factory preset"
    await save_workspace_profile(db, project_id, document=_with_header(default_profile_document(), "Factory preset"),
                                 actor_id=user.id)
    build = await _build(db, project_id)
    assert build.profile == f"{DEFAULT_ID}-w1" and build.report["profile"] == f"{DEFAULT_ID}-w1"
    assert build.report["layers"]["manual"]["retired"] == 1 and build.report["layers"]["manual"]["extracted"] == 1
    rows = (await db.execute(select(KnowledgeStructuredNode.profile, KnowledgeStructuredNode.label).where(
        KnowledgeStructuredNode.project_id == project_id))).all()
    assert {profile for profile, _ in rows} == {f"{DEFAULT_ID}-w1"}
    assert "[GeneralSettings] QueueSize" in {label for _, label in rows}
    status = await structured_status(db, authorized=authorized)
    assert status["profile"] == f"{DEFAULT_ID}-w1" and status["layers"]["manual"]["revisions"] == 1


async def test_the_profile_endpoints_validate_save_audit_and_request_re_extraction(client, db):
    project_id = await seed_workspace(db)
    user, _ = await _admin(db, project_id)
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    base = f"/api/v1/workspaces/{project_id}/knowledge/graph/structured/profile"
    current = (await client.get(base, headers=headers)).json()
    assert current["source"] == "default" and current["profile_id"] == DEFAULT_ID and current["may_author"] is True
    document = _with_header(current["document"], "Factory preset")
    checked = await client.post(f"{base}/validate", headers=headers, json={"document": document})
    assert checked.status_code == 200 and checked.json() == {"valid": True, "profile_id": f"{DEFAULT_ID}-w1"}
    broken = {**document, "unknown": 1}
    refused = await client.post(f"{base}/validate", headers=headers, json={"document": broken})
    assert refused.status_code == 422 and "exactly the fields" in refused.json()["detail"]
    assert (await client.put(base, headers=headers, json={"document": broken})).status_code == 422
    saved = await client.put(base, headers=headers, json={"document": document})
    body = saved.json()
    assert saved.status_code == 200 and body["source"] == "workspace" and body["revision"] == 1
    assert body["build"]["state"] == "pending" and body["build"]["layers"] == ["manual", "configuration", "operations"]
    member = await seed_member(db, workspace_id=project_id, role="member")
    member_headers = {"Authorization": f"Bearer {create_access_token(member)}"}
    assert (await client.put(base, headers=member_headers, json={"document": None})).status_code == 403
    assert (await client.post(f"{base}/validate", headers=member_headers, json={"document": document})).status_code == 403
    seen = (await client.get(base, headers=member_headers)).json()
    assert seen["may_author"] is False and seen["profile_id"] == f"{DEFAULT_ID}-w1"


async def test_a_source_sync_refreshes_the_layers_of_the_workspace_profile(db):
    from app.models.project.knowledge_structured import KnowledgeStructuredProfile
    from app.services.knowledge.structured.build import refresh_after_sync

    project_id = await seed_workspace(db)
    user, _ = await _admin(db, project_id)
    await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    document = default_profile_document()
    document["layers"]["configuration"]["connector_kinds"] = ["svn_repository"]
    await save_workspace_profile(db, project_id, document=document, actor_id=user.id)
    await refresh_after_sync(db, project_id, "svn_repository")
    pending = (await db.execute(select(KnowledgeStructuredBuild).where(
        KnowledgeStructuredBuild.project_id == project_id, KnowledgeStructuredBuild.state == "pending"))).scalar_one()
    # The manual request is pending; the sync merges configuration into it (the default would ask manual+operations).
    assert pending.layers == ["manual", "configuration"] and pending.profile == f"{DEFAULT_ID}-w1"
    # A stored document the loader refuses today: every layer is refreshed and the build reports it.
    db.add(KnowledgeStructuredProfile(project_id=project_id, revision=2, profile_id=f"{DEFAULT_ID}-w2",
                                      document={"key": "broken"}))
    await db.commit()
    await refresh_after_sync(db, project_id, "svn_repository")
    await db.refresh(pending)
    assert pending.layers == ["manual", "configuration", "operations"]


async def test_a_runner_plans_again_when_the_profile_changes_during_its_claim(db, monkeypatch):
    from app.services.knowledge.structured import build_slice
    from app.services.knowledge.structured.build_slice import SliceCache

    project_id = await seed_workspace(db)
    user, _ = await _admin(db, project_id)
    await seed_parsed_revision(db, project_id, source_key="manual", title="Manual", spans=CUSTOM)
    await seed_parsed_revision(db, project_id, source_key="second", title="Second", spans=DEFAULT_HEADERS)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id="w") == build.id
    plans: list[str] = []
    real_plan = build_slice._plan

    async def counted(context, spec, layer, entry):
        plans.append(context.profile.profile_id)
        return await real_plan(context, spec, layer, entry)

    monkeypatch.setattr(build_slice, "_plan", counted)
    cache = SliceCache(build.id)
    assert await run_build_slice(db, runtime=None, build_id=build.id, worker_id="w", max_revisions=1,
                                 cache=cache) == "running"
    await save_workspace_profile(db, project_id, document=_with_header(default_profile_document(), "Factory preset"),
                                 actor_id=user.id)
    while await run_build_slice(db, runtime=None, build_id=build.id, worker_id="w", max_revisions=1,
                                cache=cache) == "running":
        pass
    assert plans == [DEFAULT_ID, f"{DEFAULT_ID}-w1"]
    profiles = set((await db.execute(select(KnowledgeStructuredNode.profile).where(
        KnowledgeStructuredNode.project_id == project_id))).scalars())
    assert profiles == {f"{DEFAULT_ID}-w1"}


@pytest.mark.parametrize(("pattern", "safe"), [
    (r"(?: \w+){3,}", True), (r"(?:ab)+", True), (r"((a+)b)+", True), (r"[0-9]{1,4}", True),
    (r"(\w+\s?)*", False), (r"(a+)+", False), (r"(?:x*)*y", False), (r"^(a|b+)+$", False),
])
def test_a_profile_pattern_must_not_backtrack_without_bound(pattern, safe):
    from app.services.knowledge.structured.profile_patterns import UnsafePatternError, check_pattern

    if safe:
        assert check_pattern(pattern).pattern == pattern
    else:
        with pytest.raises(UnsafePatternError):
            check_pattern(pattern)


async def test_two_saves_racing_for_one_revision_store_one_and_answer_409(client, db, monkeypatch):
    from app.models.project.knowledge_structured import KnowledgeStructuredProfile
    from app.services.knowledge.structured import workspace_profile as module
    from app.services.knowledge.structured.workspace_profile import StructuredProfileConflictError

    project_id = await seed_workspace(db)
    user, _ = await _admin(db, project_id)
    user_id = user.id  # the refused save rolls the session back, which expires loaded objects
    document = _with_header(default_profile_document(), "Factory preset")
    await save_workspace_profile(db, project_id, document=document, actor_id=user_id)
    real_rows = module._rows

    async def stale(session, project, limit=1):
        # The racing save read the latest revision before the first save committed.
        return [] if limit == 1 else await real_rows(session, project, limit)

    monkeypatch.setattr(module, "_rows", stale)
    with pytest.raises(StructuredProfileConflictError):
        await save_workspace_profile(db, project_id, document=None, actor_id=user_id)
    headers = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    base = f"/api/v1/workspaces/{project_id}/knowledge/graph/structured/profile"
    answer = await client.put(base, headers=headers, json={"document": None})
    assert answer.status_code == 409 and "reload" in answer.json()["detail"]
    monkeypatch.setattr(module, "_rows", real_rows)
    rows = (await db.execute(select(KnowledgeStructuredProfile.revision, KnowledgeStructuredProfile.document).where(
        KnowledgeStructuredProfile.project_id == project_id))).all()
    assert [(revision, stored is not None) for revision, stored in rows] == [(1, True)]
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION))).scalars().all()
    assert [entry.details["revision"] for entry in audits] == [1]
    # The session is usable again, and the next save takes the next revision.
    assert (await save_workspace_profile(db, project_id, document=None, actor_id=user_id)).revision == 2
