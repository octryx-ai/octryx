"""Repository files to configuration layer to linkage to "Handbook vs. reality", end to end."""

from __future__ import annotations

from sqlalchemy import select

from app.models.project.knowledge_source_acl import KnowledgeSourceAcl
from app.models.project.knowledge_structured import KnowledgeStructuredEdge, KnowledgeStructuredNode
from app.services.auth import create_access_token
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import TRIGGER_MANUAL
from app.services.knowledge.structured.config_report import handbook_vs_reality
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.knowledge_runtime_support import set_evidence_runtime
from tests.services.knowledge.structured.structured_graph_support import (
    SERVER_MANUAL,
    seed_config_repository,
    seed_parsed_revision,
)
from tests.services.knowledge.structured.test_structured_graph_config import CONF_APP_INI

SECRET = "s3cr3t-Value"


async def _workspace(db, *, jira: bool = False):
    project_id = await seed_workspace(db, name="Demo Shop structured")
    user_id = await seed_member(db, workspace_id=project_id, role="admin")
    user = await fetch_user(db, user_id)
    authorized = await authorize_workspace(db, current_user=user, workspace_id=project_id)
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    await seed_parsed_revision(db, project_id, source_key="demo-shop-server-guide",
                               title="Demo Shop Server Guide 1.4", spans=SERVER_MANUAL)
    files = {f"{component}/app.ini": CONF_APP_INI.replace("{lock}", lock)
             for component, lock in (("conf", "500"), ("data", "60000"), ("worker", "60000"))}
    # A long file: its keys sit in later code spans, so citations must pick the span covering the line.
    files["data/app.ini"] = "".join(f"; padding line {n}\n" for n in range(1, 151)) + files["data/app.ini"]
    files["acme-orders-stack/values.yaml"] = "shop:\n  image:\n    tag: 3.2-3\n"
    files["conf/log4j2.xml"] = "<Configuration/>\n"
    files["conf/cache.ini"] = "[Cache1]\nHosts = cache-a:6379\nPoolSize = 8\n"
    if jira:
        from app.models.project.knowledge_source_sync import KnowledgeSourceConnector

        db.add(KnowledgeSourceConnector(project_id=project_id, connector_key="jira-shop", kind="jira",
                                        scope={"project_keys": ["ACME"]}, products=[], cursor={}))
        await db.commit()
    revisions = await seed_config_repository(db, runtime, authorized, connector_key="repo-ini",
                                             repo="acme-orders-config", files=files)
    build = await request_build(db, project_id=project_id, layers=["manual", "configuration"], trigger=TRIGGER_MANUAL)
    await claim_next_build(db, worker_id="w")
    assert await run_build_slice(db, runtime=runtime, build_id=build.id, worker_id="w") == "completed"
    await db.refresh(build)
    return user, authorized, revisions, build


async def test_the_configuration_layer_is_built_from_the_repository_files_only(db):
    _, authorized, revisions, build = await _workspace(db)
    layer = build.report["layers"]["configuration"]
    assert layer["selected"] == 5 and layer["extracted"] == 5 and layer["failed"] == 0
    linkage = build.report["linkage"]["configuration"]
    assert linkage["state"] == "ok" and linkage["edges"]["inconsistent_across"] >= 2
    setting = (await db.execute(select(KnowledgeStructuredNode).where(
        KnowledgeStructuredNode.revision_id == revisions["conf/app.ini"],
        KnowledgeStructuredNode.label == "[QueueConnection] RequestTimeout"))).scalar_one()
    assert setting.line == 30 and setting.properties["value"] == "500" and setting.span_ordinal >= 1
    from app.models.project.knowledge_parsing import KnowledgeSpanLocator

    far = (await db.execute(select(KnowledgeStructuredNode).where(
        KnowledgeStructuredNode.revision_id == revisions["data/app.ini"],
        KnowledgeStructuredNode.label == "[QueueConnection] RequestTimeout"))).scalar_one()
    locator = await db.get(KnowledgeSpanLocator, (far.revision_id, far.span_ordinal))
    assert far.line == 180 and far.span_ordinal > 1 and locator.line_start <= 180 <= locator.line_end
    mentions = (await db.execute(select(KnowledgeStructuredEdge).where(
        KnowledgeStructuredEdge.source_id == setting.node_id,
        KnowledgeStructuredEdge.edge_type == "mentions"))).scalars().all()
    assert mentions == []


async def test_ticket_keys_in_the_comment_above_a_setting_become_cited_mentions(db):
    _, _, revisions, _ = await _workspace(db, jira=True)
    setting = (await db.execute(select(KnowledgeStructuredNode).where(
        KnowledgeStructuredNode.revision_id == revisions["conf/app.ini"],
        KnowledgeStructuredNode.label == "[QueueConnection] RequestTimeout"))).scalar_one()
    (mention,) = (await db.execute(select(KnowledgeStructuredEdge).where(
        KnowledgeStructuredEdge.source_id == setting.node_id,
        KnowledgeStructuredEdge.edge_type == "mentions"))).scalars().all()
    ticket = (await db.execute(select(KnowledgeStructuredNode).where(
        KnowledgeStructuredNode.node_id == mention.target_id))).scalars().first()
    assert ticket.node_type == "JiraIssue" and ticket.label == "ACME-117"
    assert mention.citations[0][2] == 28


async def test_no_secret_value_is_stored_in_the_graph(db):
    _, authorized, _, _ = await _workspace(db)
    nodes = (await db.execute(select(KnowledgeStructuredNode.properties, KnowledgeStructuredNode.label))).all()
    edges = (await db.execute(select(KnowledgeStructuredEdge.properties))).all()
    assert SECRET not in repr(nodes) + repr(edges)
    redacted = [props for props, label in nodes if label == "[GeneralSettings] KeyStorePassword"]
    assert redacted and all(props["value"] == "[redacted]" and props["redacted"] for props in redacted)


async def test_handbook_vs_reality_lists_the_queue_findings_with_citations(db):
    _, authorized, _, _ = await _workspace(db)
    report = await handbook_vs_reality(db, authorized=authorized)
    assert report["state"] == "ok" and report["content_is_data"] is True
    unknown = {(item["section"], item["component"]): item for item in report["unknown_section"]}
    lock = unknown[("QueueConnection", "conf")]
    assert lock["keys"] == ["RequestTimeout", "RetryInterval"] and lock["key_count"] == 2
    assert lock["line"] == 30 and lock["citation"]["line"] == 30 and "#L30" in lock["citation"]["source_url"]
    assert lock["citation"]["cite_as"].startswith("[acme-orders-config:conf/app.ini")
    hint = next(item for item in lock["name_matches"] if item["name"] == "RequestTimeout")
    assert hint["parameter"] == "[Cache?] RequestTimeout" and hint["default"] == "60000"
    assert hint["citation"]["page"] == 125 and "Demo Shop Server Guide 1.4" in hint["citation"]["citation"]
    assert unknown[("${CACHE_PREFIX}Customer_Profiles", "conf")]["keys"] == ["MaxEntries", "EntryLifetime"]
    assert report["counts"]["unknown_section_settings"] == sum(item["key_count"] for item in unknown.values())
    known = {(item["setting"], item["component"]) for item in report["undocumented_in_known_section"]}
    assert known == {("[Cache1] PoolSize", "conf")}
    assert not any(item["section"] == "QueueConnection" for item in report["undocumented_in_known_section"])
    (group,) = [item for item in report["inconsistencies"] if item["setting"] == "[QueueConnection] RequestTimeout"]
    assert sorted((value["component"], value["value"]) for value in group["values"]) == [
        ("conf", "500"), ("data", "60000"), ("worker", "60000")]
    assert not any(item["setting"] == "[QueueConnection] RequestTimeout" for item in report["deviations"])
    assert report["counts"]["undocumented_in_known_section"] == len(report["undocumented_in_known_section"])
    assert report["counts"]["unknown_section"] == len(report["unknown_section"])


async def test_filters_narrow_every_list(db):
    _, authorized, _, _ = await _workspace(db)
    by_parameter = await handbook_vs_reality(db, authorized=authorized, parameter="RequestTimeout")
    assert {item["section"] for item in by_parameter["unknown_section"]} == {"QueueConnection"}
    assert by_parameter["undocumented_in_known_section"] == []
    assert [item["setting"] for item in by_parameter["inconsistencies"]] == ["[QueueConnection] RequestTimeout"]
    by_file = await handbook_vs_reality(db, authorized=authorized, file="worker/")
    assert {item["file"] for item in by_file["unknown_section"]} == {"worker/app.ini"}
    assert by_file["undocumented_in_known_section"] == []
    by_cache = await handbook_vs_reality(db, authorized=authorized, file="conf/cache.ini")
    assert [item["key"] for item in by_cache["undocumented_in_known_section"]] == ["PoolSize"]
    by_section = await handbook_vs_reality(db, authorized=authorized, section="6.3.3")
    assert {item["section"] for item in by_section["unknown_section"]} == {"QueueConnection"}
    (queue,) = {item["section"]: item for item in by_section["unknown_section"]
                 if item["component"] == "conf"}.values()
    assert {hint["name"] for hint in queue["name_matches"]} == {"RequestTimeout", "RetryInterval"}


async def test_the_report_follows_the_readers_source_acl(db):
    _, authorized, _, _ = await _workspace(db)
    db.add(KnowledgeSourceAcl(project_id=authorized.project_id, source_key="demo-shop-server-guide",
                              restriction="restricted"))
    await db.commit()
    report = await handbook_vs_reality(db, authorized=authorized)
    assert report["undocumented_in_known_section"] == [] and report["unknown_section"] == []
    assert report["documented_unused"] == []
    assert report["inconsistencies"]


async def test_the_report_endpoint_requires_a_workspace_reader(client, db):
    user, authorized, _, _ = await _workspace(db)
    url = f"/api/v1/workspaces/{authorized.project_id}/knowledge/graph/structured/report"
    assert (await client.get(url)).status_code == 401
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    found = await client.get(url, headers=headers, params={"parameter": "RequestTimeout"})
    assert found.status_code == 200 and found.json()["unknown_section"]
    other = await seed_workspace(db, name="Other")
    foreign = await client.get(f"/api/v1/workspaces/{other}/knowledge/graph/structured/report", headers=headers)
    assert foreign.status_code == 404
    assert (await client.get(url, headers=headers, params={"limit": 5000})).status_code == 422


async def test_a_workspace_without_a_configuration_layer_reports_not_built(db):
    project_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=project_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=project_id)
    assert (await handbook_vs_reality(db, authorized=authorized))["state"] == "not_built"
