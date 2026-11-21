"""The Work item list is lean and paginated; the detail read keeps the full item."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Project, WorkItem
from app.services.secure_work.work_item_listing import DETAIL_ONLY_FIELDS
from app.time_utils import utc_now

API = "/api/v1/secure-work/work-items"


async def _seed(db, count: int, *, label: str | None = None) -> tuple[str, str]:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    instance = f"lean-{uuid.uuid4().hex[:8]}"
    now = utc_now()
    for index in range(count):
        db.add(WorkItem(
            project_id=project.id,
            source_type="jira",
            source_instance=instance,
            source_key=f"LEAN-{index}",
            title=f"Item {index}",
            description="A long description " * 50,
            priority="High",
            assignee="jdoe",
            source_status="In Progress",
            labels_json=[label] if label and index % 2 == 0 else [],
            watchers_json=["w1"],
            components_json=["core"],
            linked_issues_json=[{"key": "LEAN-X"}],
            source_fields_json={
                "raw": {"fields": {"summary": f"Item {index}"}},
                "people": {"assignee": {"id": "jdoe", "display": "Jane Doe"}},
                "comments": [{"id": "1", "body": "hello"}],
                "comments_total": 3,
            },
            work_state="intake",
            updated_at=now - timedelta(minutes=index),
        ))
    await db.commit()
    return project.id, instance


@pytest.mark.asyncio
async def test_list_rows_are_lean_and_the_detail_is_full(client, auth_headers, db):
    project_id, instance = await _seed(db, 1)
    page = (await client.get(f"{API}?project_id={project_id}&limit=1000", headers=auth_headers)).json()
    row = next(item for item in page["items"] if item["source_instance"] == instance)
    assert not set(DETAIL_ONLY_FIELDS) & set(row)
    assert (row["source_key"], row["title"], row["work_state"], row["assignee"], row["priority"]) == (
        "LEAN-0", "Item 0", "intake", "jdoe", "High")
    assert row["assignee_display"] == "Jane Doe" and row["comments_total"] == 3
    assert row["automation_eligibility"]["requested"] is False and row["updated_at"]

    detail = (await client.get(f"{API}/{row['id']}", headers=auth_headers)).json()
    assert set(DETAIL_ONLY_FIELDS) <= set(detail)
    assert detail["source_fields"]["raw"]["fields"]["summary"] == "Item 0"
    assert detail["comments"][0]["body"] == "hello" and detail["description"].startswith("A long description")


@pytest.mark.asyncio
async def test_list_pages_with_limit_offset_total_and_next_offset(client, auth_headers, db):
    project_id, instance = await _seed(db, 5)
    base = f"{API}?project_id={project_id}&sync_state=imported&source_status=In%20Progress"
    seen: list[str] = []
    offset: int | None = 0
    total = None
    while offset is not None:
        page = (await client.get(f"{base}&limit=2&offset={offset}", headers=auth_headers)).json()
        assert page["limit"] == 2 and page["offset"] == offset and len(page["items"]) <= 2
        total = page["total"] if total is None else total
        assert page["total"] == total
        seen.extend(item["source_key"] for item in page["items"] if item["source_instance"] == instance)
        offset = page["next_offset"]
    assert total >= 5
    assert seen == [f"LEAN-{index}" for index in range(5)]  # newest first, no duplicates across pages
    assert len(set(seen)) == len(seen)


@pytest.mark.asyncio
async def test_json_filtered_list_pages_over_the_matches(client, auth_headers, db):
    label = f"lbl-{uuid.uuid4().hex[:6]}"
    project_id, _ = await _seed(db, 5, label=label)
    first = (await client.get(f"{API}?project_id={project_id}&label={label}&limit=2", headers=auth_headers)).json()
    assert first["total"] == 3 and [item["source_key"] for item in first["items"]] == ["LEAN-0", "LEAN-2"]
    assert first["next_offset"] == 2
    last = (await client.get(f"{API}?project_id={project_id}&label={label}&limit=2&offset=2",
                             headers=auth_headers)).json()
    assert [item["source_key"] for item in last["items"]] == ["LEAN-4"] and last["next_offset"] is None


@pytest.mark.asyncio
async def test_list_limit_is_bounded(client, auth_headers):
    assert (await client.get(f"{API}?limit=1001", headers=auth_headers)).status_code == 422
    assert (await client.get(f"{API}?offset=-1", headers=auth_headers)).status_code == 422
