"""End to end: the noise rules through real code ingest, a build and "Handbook vs. reality"."""

from __future__ import annotations

from sqlalchemy import select

from app.models.project.knowledge_structured import KnowledgeStructuredNode
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

FILES = {
    "worker/app.ini": "[Cache1]\nRequestTimeout = ${Conf_Timeout}\nPoolSize = 8\nConnectTimeout = ${Conf_Missing}\n",
    "worker/app.ini-test": "[Cache1]\nRequestTimeout = 700\nPoolSize = 9\n",
    "worker/shop_config.properties": "Conf_Timeout=500\nShop_Other=1\n",
    "conf/app.ini": "[Cache1]\nRequestTimeout = 500\n",
    "util/log4j.properties": "log4j.rootLogger=INFO\n;log4j.logger.a=DEBUG\n; log4j.logger.b=TRACE\n",
}


async def _report(db):
    project_id = await seed_workspace(db, name="Noise")
    user = await fetch_user(db, await seed_member(db, workspace_id=project_id, role="admin"))
    authorized = await authorize_workspace(db, current_user=user, workspace_id=project_id)
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    await seed_parsed_revision(db, project_id, source_key="server-manual", title="Server Manual", spans=SERVER_MANUAL)
    await seed_config_repository(db, runtime, authorized, connector_key="repo-ini", repo="ini", files=FILES)
    build = await request_build(db, project_id=project_id, layers=["manual", "configuration"], trigger=TRIGGER_MANUAL)
    await claim_next_build(db, worker_id="w")
    assert await run_build_slice(db, runtime=runtime, build_id=build.id, worker_id="w") == "completed"
    return authorized, await handbook_vs_reality(db, authorized=authorized)


async def test_the_report_states_each_finding_once_without_comment_framework_or_placeholder_noise(db):
    authorized, report = await _report(db)
    counts = report["counts"]
    # [Cache1] RequestTimeout: ${Conf_Timeout} resolves to 500 (default 60000); the test variant's 700 rides along.
    deviations = {item["file"]: item for item in report["deviations"]}
    assert sorted(deviations) == ["conf/app.ini", "worker/app.ini"]  # never one per variant file
    deviation = deviations["worker/app.ini"]
    assert (deviation["value"], deviation["resolved_value"]) == ("${Conf_Timeout}", "500")
    assert [(item["path"], item["value"], item["deviates"]) for item in deviation["variants"]] == [
        ("worker/app.ini-test", "700", True)]
    assert deviation["documented"]["default"] == "60000" and deviations["conf/app.ini"]["variants"] == []
    (unresolved,) = report["unresolved_placeholders"]
    assert unresolved["key"] == "ConnectTimeout" and unresolved["placeholders"] == ["Conf_Missing"]
    (pool,) = report["undocumented_in_known_section"]
    assert pool["key"] == "PoolSize" and [item["path"] for item in pool["variants"]] == ["worker/app.ini-test"]
    # shop_config.properties and log4j.properties are not compared with the manual at all.
    assert report["unknown_section"] == []
    # 500 (resolved) in worker equals 500 in conf: no inconsistency.
    assert report["inconsistencies"] == []
    keys = (await db.execute(select(KnowledgeStructuredNode.properties["key"].as_string()).where(
        KnowledgeStructuredNode.project_id == authorized.project_id,
        KnowledgeStructuredNode.node_type == "ConfiguredSetting"))).scalars().all()
    assert not [key for key in keys if key.startswith(";")]
    assert counts == {**counts, "deviations": 2, "unknown_section": 0, "unresolved_placeholders": 1,
                      "undocumented_in_known_section": 1, "inconsistencies": 0}
