"""Shared fake source connector, workspace, sync and visibility helpers for the source ACL facet tests."""

from __future__ import annotations

from app.models import BuiltInToolConfig, Project
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import AclExpansion, AclFacet, ItemContent, ListingPage, SourceItem
from app.services.knowledge.sources.sync.runner import run_source_sync
from app.services.knowledge.sources.sync.service import configure_connector
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

JIRA = "https://jira.example.test/jira"


class FakeSource:
    kind = "jira"
    requires_parser = False

    def __init__(self) -> None:
        self.items: dict[str, tuple[str, str, AclFacet]] = {}
        self.members: dict[str, tuple[str, ...]] = {}

    def put(self, external_id: str, title: str, text: str, acl: AclFacet | None = None) -> None:
        self.items[external_id] = (title, text, acl or AclFacet.scope())

    async def list_items(self, token, *, limit):
        items = tuple(
            SourceItem(key, title, f"{JIRA}/browse/{key}", "1", acl)
            for key, (title, _, acl) in sorted(self.items.items())
        )
        return ListingPage(items=items[:limit], next_token=None)

    async def fetch(self, item):
        return ItemContent(data=self.items[item.external_id][1].encode(), media_type="text/markdown")

    async def expand_acl(self, acl):
        emails = self.members[acl.principals[0]]
        return AclExpansion(member_emails=tuple(email for email in emails if "@" in email), unmapped=0)


def _restricted(label: str) -> AclFacet:
    return AclFacet.restricted("issue_security_level", (label,))


async def _enforce(db, workspace_id: str) -> None:
    project = await db.get(Project, workspace_id)
    project.config = {**(project.config or {}), "knowledge_source_acl": {"enforce": True}}
    await db.flush()


async def _workspace(db, *, enforce: bool = True, name: str | None = None):
    workspace_id = await seed_workspace(db, name=name)
    alice_id = await seed_member(db, workspace_id=workspace_id, role="admin", username=f"alice{workspace_id[:6]}")
    bob_id = await seed_member(db, workspace_id=workspace_id, role="member", username=f"bob{workspace_id[:6]}")
    if enforce:
        await _enforce(db, workspace_id)
    tool = {"jira_auth_mode": "basic", "jira_url": JIRA, "jira_username": "sync", "jira_password": "pw", "jira_allowed_projects": ["OPS"]}
    db.add(BuiltInToolConfig(tool_name="jira", project_id=workspace_id, config=tool, is_active=True))
    await db.flush()
    alice = await authorize_workspace(db, current_user=await fetch_user(db, alice_id), workspace_id=workspace_id)
    bob = await authorize_workspace(db, current_user=await fetch_user(db, bob_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()
    config = validate_config(connector_key="ops", kind="jira", products=[], max_items_per_run=50, project_keys=["OPS"])
    row = await configure_connector(db, authorized=alice, config=config, actor_id=alice_id)
    emails = {"alice": (await fetch_user(db, alice_id)).email, "bob": (await fetch_user(db, bob_id)).email}
    return {
        "alice": alice,
        "bob": bob,
        "alice_id": alice_id,
        "runtime": runtime,
        "evidence_index": evidence_index,
        "row": row,
        "emails": emails,
    }


async def _sync(db, world, source: FakeSource):
    row = await db.get(KnowledgeSourceConnector, world["row"].id)
    run = await run_source_sync(
        db,
        runtime=world["runtime"],
        authorized=world["alice"],
        connector_row=row,
        connector=source,
        actor_id=world["alice_id"],
    )
    projector = EvidenceProjector(world["runtime"])
    while await projector.project_once(db, worker_id="test") is not None:
        pass
    return run


async def _titles(db, world, authorized, query: str) -> list[str]:
    result = await retrieve_workspace_evidence(db, runtime=world["runtime"], authorized=authorized, query_text=query)
    return sorted(item.source_title for item in result.evidence)


def _markers(world, authorized) -> dict[str, list[str]]:
    records = world["evidence_index"].workspace_records(authorized.workspace.canonical)
    return {record["body_text"].split(":")[0]: record["acl_keys"] for record in records.values()}
