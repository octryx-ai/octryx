"""Policy UX regressions: draft-impact retention, ``If-Match`` on whole-set saves, draft latency metric,
hashed principals, the public policy view and concurrent-flush buckets."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.models import PolicyDraftImpact, PolicySetVersion, Project, SystemConfig
from app.services.classification_tool_policy import classification_tool_decision
from app.services.policy_engine import draft_shadow, store
from app.services.policy_engine.builder import render
from app.services.policy_engine.builder_model import model_from_json
from app.services.policy_engine.custom_policies import check_custom_policies
from app.services.policy_engine.decision_log import RETENTION_CONFIG_KEY
from app.services.policy_engine.draft_shadow import flush_draft_impact, pending_buckets
from app.services.policy_engine.policy_edits import ERROR_CONFLICT, PolicyEditError, put_policy, save_set
from app.services.policy_engine.runtime import maintain_policy_runtime, set_policy_runtime
from app.services.policy_engine.shadow import draft_latency_summary, latency_summary
from app.time_utils import utc_now
from tests.knowledge_evidence_seed_support import seed_member
from tests.policy_engine_support import BASE, bearer, make_user, publish, use_custom_policies

FORBID = '@id("seat-off")\nforbid (principal, action == Action::"use_seat", resource);\n'
OTHER = '@id("no-web-search")\nforbid (principal, action == Action::"call_tool", resource)\n' \
        'when { resource in [Tool::"web_search"] };\n'
CONFIG = {"classification_tool_policy": {"level": "internal", "workspace_id": "ws-1", "connectors": {}}}


class _SharedFactory:
    def __init__(self, db) -> None:
        self.db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return None


def _impact(days_old: float, policy_id: str = "p") -> PolicyDraftImpact:
    hour = (utc_now() - timedelta(days=days_old)).replace(minute=0, second=0, microsecond=0)
    return PolicyDraftImpact(id=str(uuid.uuid4()), draft_digest="sha256:x", draft_version=1, policy_id=policy_id,
                             point="seat", action="use_seat", hour=hour, count=1, principals=[], samples=[],
                             updated_at=utc_now())


def _with_draft(text: str = OTHER) -> None:
    runtime = use_custom_policies(FORBID)
    checked = check_custom_policies(text)
    set_policy_runtime(replace(runtime, draft_text=checked.text, draft_ids=frozenset(checked.ids), draft_version=7,
                               draft_digest=checked.digest))


@pytest.mark.asyncio
async def test_maintenance_prunes_draft_impact_by_the_retention_once_an_hour(db, monkeypatch):
    # A host up for less than an hour (fresh CI runner): the first prune is still due.
    monkeypatch.setattr(draft_shadow.time, "monotonic", lambda: 120.0)
    monkeypatch.setattr("app.db.core.async_session_factory", _SharedFactory(db))
    use_custom_policies(FORBID)  # a fresh snapshot: maintenance does not reload
    db.add(SystemConfig(key=RETENTION_CONFIG_KEY, value="50"))
    db.add_all([_impact(40, "kept"), _impact(60, "expired")])
    await db.commit()
    assert pending_buckets() == 0
    await maintain_policy_runtime()
    left = (await db.execute(select(PolicyDraftImpact.policy_id))).scalars().all()
    assert left == ["kept"], "rows older than the configured retention are pruned, newer ones kept"
    db.add(_impact(70, "within-the-hour"))
    await db.commit()
    await maintain_policy_runtime()
    assert sorted((await db.execute(select(PolicyDraftImpact.policy_id))).scalars().all()) == [
        "kept", "within-the-hour"], "the prune runs at most once an hour"


@pytest.mark.asyncio
async def test_the_whole_set_save_requires_a_current_if_match(client, db):
    admin = await make_user(db, admin=True)
    draft = (await client.post(f"{BASE}/policy-sets", json={"policies": FORBID}, headers=bearer(admin))).json()
    path = f"{BASE}/policy-sets/{draft['version']}"
    missing = await client.put(path, json={"policies": OTHER}, headers=bearer(admin))
    assert missing.status_code == 428 and missing.json()["detail"]["code"] == "policy_set_if_match_required"
    first = await client.put(path, json={"policies": OTHER}, headers={**bearer(admin), "If-Match": draft["digest"]})
    assert first.status_code == 200 and first.json()["digest"] != draft["digest"]
    lost = await client.put(path, json={"policies": FORBID + OTHER},
                            headers={**bearer(admin), "If-Match": f'"{draft["digest"]}"'})
    assert lost.status_code == 409
    assert lost.json()["detail"] == {"code": ERROR_CONFLICT, "digest": first.json()["digest"]}
    row = await store.get_version(db, draft["version"])
    await db.refresh(row)
    assert row.policies_text == check_custom_policies(OTHER).text, "the stale save changed nothing"


@pytest.mark.asyncio
async def test_a_note_alone_is_saved_without_the_text(client, db):
    admin = await make_user(db, admin=True)
    draft = (await client.post(f"{BASE}/policy-sets", json={"policies": FORBID}, headers=bearer(admin))).json()
    path = f"{BASE}/policy-sets/{draft['version']}"
    edited = await client.put(path, json={"policies": OTHER}, headers={**bearer(admin), "If-Match": draft["digest"]})
    noted = await client.patch(path, json={"note": "Block web search"}, headers=bearer(admin))
    assert noted.status_code == 200
    body = noted.json()
    assert body["note"] == "Block web search" and body["digest"] == edited.json()["digest"]
    assert body["policies"] == check_custom_policies(OTHER).text, "a concurrent text edit is kept"
    submitted = await client.post(f"{path}/submit", headers=bearer(admin))
    assert submitted.status_code == 200
    frozen = await client.patch(path, json={"note": "x"}, headers=bearer(admin))
    assert frozen.status_code == 409 and frozen.json()["detail"]["code"] == "policy_set_version_not_draft"


async def _stale_draft(client, db) -> tuple[str, PolicySetVersion, str]:
    admin = await make_user(db, admin=True)
    draft = (await client.post(f"{BASE}/policy-sets", json={"policies": FORBID}, headers=bearer(admin))).json()
    row = await store.get_version(db, draft["version"])
    assert row.digest == draft["digest"]
    await db.execute(update(PolicySetVersion).where(PolicySetVersion.id == row.id)
                     .values(digest="sha256:concurrent").execution_options(synchronize_session=False))
    assert row.digest == draft["digest"], "the session still holds the digest it read"
    return admin, row, draft["digest"]


@pytest.mark.asyncio
async def test_a_policy_edit_loses_the_race_against_a_concurrent_save(client, db):
    admin, row, seen = await _stale_draft(client, db)
    with pytest.raises(PolicyEditError) as refused:
        await put_policy(db, row.version, "no-web-search", {"cedar": OTHER}, if_match=seen, actor_id=admin)
    assert refused.value.code == ERROR_CONFLICT and refused.value.details == {"digest": "sha256:concurrent"}


@pytest.mark.asyncio
async def test_a_whole_set_save_loses_the_race_against_a_concurrent_save(client, db):
    admin, row, seen = await _stale_draft(client, db)
    with pytest.raises(PolicyEditError) as refused:
        await save_set(db, row, text=OTHER, note=None, if_match=seen, actor_id=admin)
    assert refused.value.details == {"digest": "sha256:concurrent"}


@pytest.mark.asyncio
async def test_the_draft_evaluation_is_measured_separately(client, db):
    use_custom_policies(FORBID)
    for index in range(3):
        classification_tool_decision("web_search", CONFIG, {"query": f"a{index}"})
    assert latency_summary()["samples"] == 3 and draft_latency_summary()["samples"] == 0
    _with_draft()
    for index in range(4):
        classification_tool_decision("web_search", CONFIG, {"query": f"b{index}"})
    assert latency_summary()["samples"] == 7, "the live metric is unchanged"
    draft = draft_latency_summary()
    assert draft["samples"] == 4 and draft["p95_ms"] > 0
    status = (await client.get(f"{BASE}/status", headers=bearer(await make_user(db, admin=True)))).json()
    assert status["draft_latency"]["samples"] == 4


def test_impact_samples_carry_the_principal_hash():
    _with_draft()
    classification_tool_decision("web_search", CONFIG, {"query": "x"})
    ((_, bucket),) = draft_shadow._BUCKETS.items()
    (principal,) = bucket["principals"]
    assert [sample["principal"] for sample in bucket["samples"]] == [principal]
    assert len(principal) == 16 and "::" not in principal


def _builder(raw: dict) -> str:
    model, issues = model_from_json(raw)
    assert model is not None, issues
    return render(model)


def _plain(item: dict) -> str:
    return "".join(segment["text"] for segment in item["sentence"])


@pytest.mark.asyncio
async def test_members_never_read_other_workspaces_users_or_groups(client, db):
    own = Project(id=str(uuid.uuid4()), name="Own Workspace", is_active=True, config={})
    secret = Project(id=str(uuid.uuid4()), name="Secret Merger Room", is_active=True, config={})
    db.add_all([own, secret])
    await db.commit()
    named = await make_user(db, admin=False)
    member = await seed_member(db, workspace_id=own.id, role="member")
    texts = [
        _builder({"id": "a-two-workspaces", "actions": ["use_seat"], "where": {"workspaces": [own.id, secret.id]}}),
        _builder({"id": "b-group", "actions": ["use_seat"], "who": {"mode": "groups", "items": ["m-and-a-team"]}}),
        _builder({"id": "c-user", "actions": ["use_seat"], "who": {"mode": "users", "items": [named]}}),
        '@id("d-hand-written")\nforbid (principal in Group::"m-and-a-team", action == Action::"use_seat", resource)\n'
        f'when {{ context.workspace == Workspace::"{own.id}" || context.workspace == Workspace::"{secret.id}" }};',
    ]
    await publish(client, db, "\n\n".join(texts) + "\n")
    body = (await client.get(f"/api/v1/workspaces/{own.id}/policy-summary", headers=bearer(member))).json()
    items = {item["id"]: item for item in body["platform_policies"]["items"]}
    assert set(items) == {"a-two-workspaces", "b-group", "c-user", "d-hand-written"}
    assert _plain(items["a-two-workspaces"]) == "Block everyone from using a personal seat in Own Workspace or " \
                                                "another Workspace."
    assert "members of group (hidden)" in _plain(items["b-group"])
    assert "user (hidden)" in _plain(items["c-user"])
    assert "members of group (hidden)" in _plain(items["d-hand-written"])
    exposed = str(body)
    assert "Secret Merger Room" not in exposed and "m-and-a-team" not in exposed and named not in exposed
    admin_view = (await client.get(f"{BASE}/policies", headers=bearer(await make_user(db, admin=True)))).json()
    assert "Secret Merger Room" in str(admin_view) and "m-and-a-team" in str(admin_view), "admins keep the names"


@pytest.mark.asyncio
async def test_a_concurrently_inserted_bucket_is_added_to_not_lost(db, monkeypatch):
    _with_draft(OTHER + '\n@id("no-seats")\nforbid (principal, action == Action::"call_tool", resource);\n')
    for index in range(3):
        classification_tool_decision("web_search", CONFIG, {"query": f"q{index}"})
    assert {key[2]: bucket["count"] for key, bucket in draft_shadow._BUCKETS.items()} == {
        "no-web-search": 3, "no-seats": 3}
    (digest, version, _, point, action, hour) = next(iter(draft_shadow._BUCKETS))
    real = draft_shadow._bucket_row
    raced: list[str] = []

    async def racing_read(session, digest_, policy_id, point_, action_, hour_):
        if policy_id == "no-web-search" and not raced:  # another worker inserts right after this read
            raced.append(policy_id)
            session.add(PolicyDraftImpact(draft_digest=digest_, draft_version=version, policy_id=policy_id,
                                          point=point_, action=action_, hour=hour_, count=5, principals=["other"],
                                          samples=[], updated_at=utc_now()))
            await session.commit()
            return None
        return await real(session, digest_, policy_id, point_, action_, hour_)

    monkeypatch.setattr(draft_shadow, "_bucket_row", racing_read)
    assert await flush_draft_impact(db) == 2
    await db.commit()
    rows = {row.policy_id: row for row in (await db.execute(select(PolicyDraftImpact))).scalars()}
    assert raced == ["no-web-search"]
    assert rows["no-web-search"].count == 8 and "other" in rows["no-web-search"].principals
    assert rows["no-seats"].count == 3, "the rest of the batch is written too"
    assert (digest, point, action, hour) == (rows["no-seats"].draft_digest, "tool_admission", "call_tool",
                                             rows["no-seats"].hour)
