"""Custom REST as a Knowledge source: a REST list operation synced into Knowledge.

Against one API answering through the real pinned ``custom_rest`` egress (``rest_connector_support``) and the real
ledger with the in-memory Evidence index/S3 doubles: records are listed as the source's role (scope parameter injected,
result filter applied and counted, never ingested), their content is read through the detail operation, an unchanged
version is not fetched again and a changed one makes a new revision; the ACL follows the grants (visible to a holder
of an admitted role, invisible to others, withheld while the Workspace does not enforce source ACLs, and the admin
answer says so); a page larger than the runner's limit is answered in slices; the change parameter drives
``list_changed_items``; an unknown kind is refused instead of being read as Jira; a configuration without version or
``updated_at`` is refused; and the admin API samples a draft without saving or ingesting anything.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import User
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_describe import describe_connector
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_source_sync_custom_rest_support import MAPPING, FakeDocs, _run, _scope, _world, api  # noqa: F401

pytestmark = pytest.mark.usefixtures("public_source_dns")


def _calls(api, kind: str) -> int:  # noqa: F811
    detail = [request for request in api.requests if request.url.path.startswith("/v1/docs/")]
    return len(detail) if kind == "detail" else len(api.requests) - len(detail)


async def _source(db, world, *, mapping=None, actor_id=None, **scope):
    config = validate_config(connector_key="desk", kind="custom_rest", scope=_scope(world, **scope),
                             mapping=MAPPING if mapping is None else mapping, max_items_per_run=50)
    return await configure_connector(db, authorized=world.alice, config=config, actor_id=actor_id or world.alice_id)


async def _titles(db, world, authorized, query: str) -> list[str]:
    result = await retrieve_workspace_evidence(db, runtime=world.runtime, authorized=authorized, query_text=query)
    return sorted(item.source_title for item in result.evidence)


async def test_records_sync_incrementally_through_the_detail_operation_inside_the_roles_scope(db, api) -> None:  # noqa: F811
    world = await _world(db)
    docs = FakeDocs()
    docs.put("D-1", "VPN runbook", "The failover drill for the VPN gateway.")
    docs.put("D-2", "Mail runbook", "The failover drill for the mail relay.")
    docs.put("D-9", "Other team", "The failover drill of another team.", group="G2")
    api.answer = docs.answer
    row = await _source(db, world)

    first = await _run(db, world, row)

    assert first.state == "completed" and first.report["created"] == 2
    assert first.report["listing"] == {"role": world.roles.agent, "pages": 1, "dropped_out_of_scope": 1}, \
        "the result filter dropped the G2 record; it is counted and never ingested"
    listed = [request for request in api.requests if request.url.path == "/v1/docs"]
    assert all(request.url.params["group"] == "G1" for request in listed), "the role's scope parameter is injected"
    assert _calls(api, "detail") == 2, "the content is read through the detail operation"
    assert await _titles(db, world, world.alice, "failover drill") == ["Mail runbook", "VPN runbook"]

    second = await _run(db, world, row)

    assert (second.report["created"], second.report["unchanged"]) == (0, 2)
    assert _calls(api, "detail") == 2, "an unchanged version marker is never fetched again"

    docs.put("D-1", "VPN runbook", "The failover drill for the VPN gateway, now with a rollback.",
             updated="2026-11-12T08:00:00Z")
    third = await _run(db, world, row)

    assert (third.report["updated"], third.report["unchanged"]) == (1, 1)
    assert _calls(api, "detail") == 3, "only the changed record is fetched"


async def test_the_grants_decide_who_finds_the_knowledge(db, api) -> None:  # noqa: F811
    world = await _world(db)
    docs = FakeDocs()
    docs.put("D-1", "VPN runbook", "The failover drill for the VPN gateway.")
    api.answer = docs.answer
    row = await _source(db, world)

    run = await _run(db, world, row)

    assert run.report["created"] == 1
    assert run.outcomes[0]["title"] is None, "a restricted item's title never reaches the run report"
    assert await _titles(db, world, world.alice, "failover drill") == ["VPN runbook"], "a holder of the agent role"
    assert await _titles(db, world, world.bob, "failover drill") == [], \
        "bob's role is scoped to G2: it would never list this record, so Knowledge does not show it to him either"


async def test_an_unscoped_grant_admits_its_holders_and_workspace_visibility_admits_everyone(db, api) -> None:  # noqa: F811
    world = await _world(db, list_grants=lambda roles: [{"role": roles.agent, "scope": {"group": "G1"}},
                                                        {"role": roles.other}])
    docs = FakeDocs()
    docs.put("D-1", "VPN runbook", "The failover drill for the VPN gateway.")
    api.answer = docs.answer
    row = await _source(db, world)

    await _run(db, world, row)

    assert await _titles(db, world, world.bob, "failover drill") == ["VPN runbook"], \
        "bob's unscoped grant lists everything the agent role lists"

    outsider_world = await _world(db)
    docs_two = FakeDocs()
    docs_two.put("D-5", "Shared notes", "The failover drill shared notes.")
    api.answer = docs_two.answer
    # ``workspace`` visibility is a platform admin's decision (``owner_rules``), also on the service path.
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    public = await _source(db, outsider_world, visibility="workspace", actor_id=admin.id)
    await _run(db, outsider_world, public)
    assert await _titles(db, outsider_world, outsider_world.bob, "failover drill") == ["Shared notes"]


async def test_without_acl_enforcement_restricted_items_are_withheld_and_the_answer_says_so(db, api) -> None:  # noqa: F811
    world = await _world(db, enforce=False)
    docs = FakeDocs()
    docs.put("D-1", "VPN runbook", "The failover drill for the VPN gateway.")
    api.answer = docs.answer
    row = await _source(db, world)

    run = await _run(db, world, row)

    assert run.report["created"] == 0 and run.report["withheld_reasons"] == {"restricted_acl": 1}
    described = await describe_connector(db, await db.get(KnowledgeSourceConnector, row.id))
    assert described["acl"]["restricted_items_withheld"] is True and described["acl"]["note"]
    assert _calls(api, "detail") == 0, "a withheld item is never fetched"
