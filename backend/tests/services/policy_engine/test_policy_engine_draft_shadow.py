"""Policy UX: the draft shadow counts what an open draft would block in live traffic."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import PolicyDraftImpact
from app.services.classification_tool_policy import classification_tool_decision
from app.services.policy_engine import draft_shadow
from app.services.policy_engine.custom_policies import check_custom_policies
from app.services.policy_engine.draft_shadow import flush_draft_impact, pending_buckets, prune_draft_impact
from app.services.policy_engine.request_principal import policy_principal_scope
from app.services.policy_engine.runtime import current_runtime, refresh_policy_runtime, set_policy_runtime
from app.services.policy_engine.shadow import decision_counters
from app.time_utils import utc_now
from tests.policy_engine_support import BASE, bearer, make_user, publish, use_custom_policies

DRAFT = '@id("no-web-search")\nforbid (principal, action == Action::"call_tool", resource)\nwhen { resource in [Tool::"web_search"] };\n'
PUBLISHED = '@id("seat-off")\nforbid (principal, action == Action::"use_seat", resource);\n'
CONFIG = {"classification_tool_policy": {"level": "internal", "workspace_id": "ws-1", "connectors": {}}}
DENIED_CONFIG = {"classification_tool_policy": {"level": "internal", "workspace_id": "ws-1",
                                                "connectors": {"jira": "none"}}}


def _with_draft(text: str = DRAFT, *, mode: str = "shadow"):
    runtime = use_custom_policies(PUBLISHED, mode=mode)
    checked = check_custom_policies(text)
    set_policy_runtime(replace(runtime, draft_text=checked.text, draft_ids=frozenset(checked.ids), draft_version=7,
                               draft_digest=checked.digest))
    return checked.digest


def _buckets():
    return {(key[2], key[3], key[4]): value["count"] for key, value in draft_shadow._BUCKETS.items()}


def test_an_allowed_request_the_draft_would_deny_is_counted_and_the_live_shadow_is_untouched():
    _with_draft()
    before = classification_tool_decision("web_search", CONFIG, {"query": "x"})
    assert before.allowed is True, "shadow mode: nothing changes"
    assert _buckets() == {("no-web-search", "tool_admission", "call_tool"): 1}
    assert decision_counters()["tool_admission"] == {"match": 1, "mismatch": 0, "custom_policy": 0, "error": 0}
    classification_tool_decision("other_tool_x", CONFIG, {"query": "x"})
    assert _buckets() == {("no-web-search", "tool_admission", "call_tool"): 1}, "a request the draft allows"


def test_a_request_the_existing_check_already_denies_is_not_counted():
    _with_draft('@id("no-jira")\nforbid (principal, action in [Action::"read_connector", Action::"write_connector"], '
                'resource)\nwhen { resource in [ConnectorFamily::"jira"] };\n')
    assert classification_tool_decision("get_jira_ticket", DENIED_CONFIG, {"key": "A-1"}).allowed is False
    assert pending_buckets() == 0


def test_memoised_listing_decisions_count_on_every_listing():
    _with_draft()
    for _ in range(3):
        classification_tool_decision("web_search", CONFIG)
    assert _buckets() == {("no-web-search", "tool_admission", "call_tool"): 3}


def test_enforce_mode_still_enforces_only_the_published_set():
    _with_draft(mode="enforce")
    assert classification_tool_decision("web_search", CONFIG, {"query": "x"}).allowed is True
    assert pending_buckets() == 1


@pytest.mark.asyncio
async def test_the_runtime_loads_the_open_draft_unless_it_equals_the_published_set(client, db):
    admin = await make_user(db, admin=True)
    await publish(client, db, PUBLISHED)
    runtime = await refresh_policy_runtime(db)
    assert runtime.draft_text == "" and runtime.draft_digest is None
    same = (await client.post(f"{BASE}/policy-sets", json={"policies": PUBLISHED}, headers=bearer(admin))).json()
    assert (await refresh_policy_runtime(db)).draft_digest is None, "a draft equal to the published set adds nothing"
    await client.post(f"{BASE}/policy-sets/{same['version']}/retire", headers=bearer(admin))
    draft = (await client.post(f"{BASE}/policy-sets", json={"policies": PUBLISHED + "\n" + DRAFT},
                               headers=bearer(admin))).json()
    loaded = await refresh_policy_runtime(db)
    assert loaded.draft_version == draft["version"] and loaded.draft_digest == draft["digest"]
    assert loaded.draft_ids == frozenset({"seat-off", "no-web-search"})
    assert loaded.key != replace(loaded, draft_digest=None).key, "a new draft invalidates the listing memo"


@pytest.mark.asyncio
async def test_flushes_accumulate_per_hour_bounded_and_the_api_reports_per_policy(client, db):
    admin = await make_user(db, admin=True)
    users = [await make_user(db, admin=False) for _ in range(3)]
    await publish(client, db, PUBLISHED)
    draft = (await client.post(f"{BASE}/policy-sets", json={"policies": PUBLISHED + "\n" + DRAFT},
                               headers=bearer(admin))).json()
    await refresh_policy_runtime(db)
    assert current_runtime().draft_digest == draft["digest"]
    for user in users[:2]:
        async with policy_principal_scope(user):
            for _ in range(3):
                classification_tool_decision("web_search", CONFIG, {"query": "secret token=abc123abc123abc123"})
    assert [len(bucket["samples"]) for bucket in draft_shadow._BUCKETS.values()] == [draft_shadow.MAX_SAMPLES], \
        "the buffer keeps a bounded sample"
    assert await flush_draft_impact(db) == 1
    async with policy_principal_scope(users[2]):
        for _ in range(4):
            classification_tool_decision("web_search", CONFIG, {"query": "y"})
    await flush_draft_impact(db)
    await db.commit()
    (row,) = (await db.execute(select(PolicyDraftImpact))).scalars()
    assert (row.policy_id, row.point, row.action, row.count, row.draft_version) == (
        "no-web-search", "tool_admission", "call_tool", 10, draft["version"])
    assert len(row.principals) == 3 and len(row.samples) == draft_shadow.MAX_SAMPLES
    assert row.hour.minute == 0 and row.hour.second == 0
    async with policy_principal_scope(users[1]):
        classification_tool_decision("web_search", CONFIG, {"query": "z"})  # still buffered: reported too
    body = (await client.get(f"{BASE}/policy-sets/{draft['version']}/impact", params={"hours": 24},
                             headers=bearer(admin))).json()
    assert body["total"] == 11 and body["hours"] == 24
    policy = body["policies"]["no-web-search"]
    assert policy["count"] == 11 and policy["points"] == {"tool_admission": 11} and policy["actions"] == {"call_tool": 11}
    assert policy["principals"] == 3
    assert policy["samples"][0]["resource"] == "Tool::web_search"
    assert all(len(sample["principal"]) == 16 and "User::" not in sample["principal"] for sample in policy["samples"]), \
        "samples carry the principal hash, never the label"
    assert not any(user in str(body) for user in users)
    other = (await client.get(f"{BASE}/policy-sets/1/impact", headers=bearer(admin))).json()
    assert other["total"] == 0 and other["policies"] == {}
    assert (await client.get(f"{BASE}/policy-sets/{draft['version']}/impact", params={"hours": 0},
                             headers=bearer(admin))).status_code == 422
    member = await make_user(db, admin=False)
    assert (await client.get(f"{BASE}/policy-sets/1/impact", headers=bearer(member))).status_code == 403


@pytest.mark.asyncio
async def test_old_buckets_are_pruned_and_the_buffer_is_bounded(db, monkeypatch):
    db.add(PolicyDraftImpact(id=str(uuid.uuid4()), draft_digest="sha256:x", draft_version=1, policy_id="p",
                             point="seat", action="use_seat", hour=utc_now() - timedelta(days=40), count=1,
                             principals=[], samples=[], updated_at=utc_now()))
    await db.commit()
    await prune_draft_impact(db, days=30)
    await db.commit()
    assert (await db.execute(select(PolicyDraftImpact))).scalars().all() == []
    monkeypatch.setattr(draft_shadow, "MAX_BUCKETS", 1)
    _with_draft(DRAFT + '\n@id("no-other")\nforbid (principal, action == Action::"call_tool", resource);\n')
    classification_tool_decision("web_search", CONFIG, {"query": "x"})
    assert pending_buckets() == 1 and draft_shadow._STATE["dropped"] == 1


def test_only_the_drafts_own_policies_are_counted_never_the_baseline():
    from app.services.policy_engine.points import tool_query
    from app.services.policy_engine.shadow import LegacyDecision, _draft_blocking

    _with_draft('@id("no-jira-writes")\nforbid (principal, action == Action::"write_connector", resource)\n'
                'when { resource in [ConnectorFamily::"jira"] };\n')
    section = {"level": "internal", "workspace_id": "ws-1", "connectors": {"jira": "none"}}
    # Asked directly (no shadow decision, so no mismatch is recorded): both a classification forbid and the draft
    # policy deny; only the draft's own policy is attributed.
    query = tool_query("add_jira_comment", section, {})
    assert _draft_blocking(query, LegacyDecision(True), current_runtime()) == ("no-jira-writes",)
    assert _draft_blocking(query, LegacyDecision(False), current_runtime()) == ()
