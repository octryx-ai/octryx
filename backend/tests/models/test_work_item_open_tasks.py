"""The open task list: the Work item list's
``open``, ``mine``, ``q`` and ``state_counts`` filters, used by the phone's task view."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Project, WorkItem
from app.time_utils import utc_now

API = "/api/v1/secure-work/work-items"
ROWS = [  # (key, title, work_state, assignee)
    ("OPEN-1", "Fix the scoring timeout", "intake", "ADMIN"),
    ("OPEN-2", "Release notes 4.2", "development", "someone"),
    ("OPEN-3", "100% coverage_report", "clarification", None),
    ("OPEN-4", "Old finished thing", "done", "admin"),
    ("OPEN-5", "Withdrawn idea", "rejected", "admin"),
]


async def _seed(db) -> tuple[str, str]:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    instance = f"open-{uuid.uuid4().hex[:8]}"
    now = utc_now()
    for index, (key, title, state, assignee) in enumerate(ROWS):
        db.add(WorkItem(project_id=project.id, source_type="jira", source_instance=instance, source_key=key,
                        title=title, work_state=state, assignee=assignee, updated_at=now - timedelta(minutes=index)))
    await db.commit()
    return project.id, instance


async def _keys(client, headers, query: str, instance: str) -> tuple[list[str], dict]:
    page = (await client.get(f"{API}?limit=1000&{query}", headers=headers)).json()
    return [item["source_key"] for item in page["items"] if item["source_instance"] == instance], page


@pytest.mark.asyncio
async def test_open_leaves_out_finished_items(client, auth_headers, db):
    project_id, instance = await _seed(db)
    keys, _ = await _keys(client, auth_headers, f"project_id={project_id}&open=true", instance)
    assert keys == ["OPEN-1", "OPEN-2", "OPEN-3"]
    every, _ = await _keys(client, auth_headers, f"project_id={project_id}", instance)
    assert len(every) == 5  # without the filter nothing changes


@pytest.mark.asyncio
async def test_mine_matches_the_username_case_insensitively(client, auth_headers, db):
    project_id, instance = await _seed(db)
    keys, _ = await _keys(client, auth_headers, f"project_id={project_id}&open=true&mine=true", instance)
    assert keys == ["OPEN-1"]


@pytest.mark.asyncio
async def test_search_finds_key_or_title_and_treats_wildcards_literally(client, auth_headers, db):
    project_id, instance = await _seed(db)
    assert (await _keys(client, auth_headers, f"project_id={project_id}&q=release", instance))[0] == ["OPEN-2"]
    assert (await _keys(client, auth_headers, f"project_id={project_id}&q=open-3", instance))[0] == ["OPEN-3"]
    assert (await _keys(client, auth_headers, f"project_id={project_id}&q=100%25", instance))[0] == ["OPEN-3"]
    assert (await _keys(client, auth_headers, f"project_id={project_id}&q=e_r", instance))[0] == ["OPEN-3"]
    assert (await _keys(client, auth_headers, f"project_id={project_id}&q=%25", instance))[0] == ["OPEN-3"]


@pytest.mark.asyncio
async def test_state_counts_ignore_the_state_filter_but_keep_the_others(client, auth_headers, db):
    project_id, instance = await _seed(db)
    keys, page = await _keys(
        client, auth_headers, f"project_id={project_id}&open=true&work_state=intake&state_counts=true", instance)
    assert keys == ["OPEN-1"]
    counts = page["state_counts"]
    assert counts.get("intake", 0) >= 1 and counts.get("development", 0) >= 1 and counts.get("clarification", 0) >= 1
    assert "done" not in counts and "rejected" not in counts
    _, plain = await _keys(client, auth_headers, f"project_id={project_id}", instance)
    assert "state_counts" not in plain
