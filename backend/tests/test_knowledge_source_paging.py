"""Documents can reach every visible source: keyset pages and a title filter (judge J-C-001)."""

from __future__ import annotations

import pytest

from app.main import app
from app.services.auth import get_current_user
from app.services.knowledge.runtime import set_evidence_runtime
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_outsider, seed_workspace

BASE = "/api/v1/workspaces"


@pytest.fixture
def evidence_runtime():
    runtime, s3, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime
    finally:
        set_evidence_runtime(None)


@pytest.fixture
def as_user(db):
    def _install(user):
        app.dependency_overrides[get_current_user] = lambda: user

    yield _install
    app.dependency_overrides.pop(get_current_user, None)


async def _upload(client, workspace_id: str, key: str, title: str) -> None:
    response = await client.post(
        f"{BASE}/{workspace_id}/knowledge/sources",
        files={"file": ("doc.txt", f"{title} body text.\n".encode(), "text/plain")},
        data={"source_key": key, "display_title": title},
    )
    assert response.status_code == 201, response.text


async def test_cursor_pages_reach_every_source_once(client, db, as_user, evidence_runtime):
    workspace_id = await seed_workspace(db)
    as_user(await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin")))
    for index in range(5):
        await _upload(client, workspace_id, f"doc-{index}", f"Runbook {index}")

    seen: list[str] = []
    cursor = None
    for _ in range(5):
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await client.get(f"{BASE}/{workspace_id}/knowledge/sources", params=params)).json()
        seen.extend(item["source_key"] for item in page["sources"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == [f"doc-{index}" for index in range(5)]
    assert len(seen) == len(set(seen))


async def test_title_filter_is_literal_and_scoped(client, db, as_user, evidence_runtime):
    workspace_id = await seed_workspace(db)
    as_user(await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin")))
    await _upload(client, workspace_id, "alpha", "Alpha guide")
    await _upload(client, workspace_id, "beta", "Beta 100% guide")

    found = (await client.get(f"{BASE}/{workspace_id}/knowledge/sources", params={"query": "alpha"})).json()
    assert [item["source_key"] for item in found["sources"]] == ["alpha"]
    literal = (await client.get(f"{BASE}/{workspace_id}/knowledge/sources", params={"query": "100%"})).json()
    assert [item["source_key"] for item in literal["sources"]] == ["beta"]
    assert (await client.get(f"{BASE}/{workspace_id}/knowledge/sources", params={"cursor": "not-a-cursor"})).status_code in {400, 422}

    other = await seed_workspace(db, name="paging-other")
    as_user(await fetch_user(db, await seed_outsider(db)))
    assert (await client.get(f"{BASE}/{other}/knowledge/sources", params={"query": "alpha"})).status_code == 404
