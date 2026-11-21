"""Bitbucket commit summaries and quality rollups of large Jira and Bitbucket searches without a hard cap."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, User
from app.services.tool_result_compression import compress_tool_result_for_model


def _contains_hard_cap(value):
    if isinstance(value, dict):
        if value.get("_hard_capped") is True:
            return True
        return any(_contains_hard_cap(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_hard_cap(item) for item in value)
    return False


@pytest.mark.asyncio
async def test_bitbucket_recent_commits_are_compressed_to_summary(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    bitbucket = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="list_recent_bitbucket_commits",
        result={
            "days": 7,
            "cutoff_utc": "2026-03-23T00:00:00Z",
            "branch_mode": "all",
            "total_commit_count": 60,
            "repositories": [
                {
                    "project_key": "RIVER",
                    "repo_slug": "service-a",
                    "label": "RIVER/service-a",
                    "commit_count": 40,
                    "branches_scanned": ["main", "release/prod", "hotfix/a"],
                    "branch_mode": "all",
                    "commits": [
                        {
                            "display_id": f"abc{i}",
                            "message": f"Commit {i}",
                            "author_name": "Alice",
                            "author_timestamp": 1000 + i,
                            "branches": ["release/prod"] if i % 2 else ["main"],
                        }
                        for i in range(20)
                    ],
                }
            ],
            "commits": [
                {
                    "project_key": "RIVER",
                    "repo_slug": "service-a",
                    "repository_label": "RIVER/service-a",
                    "display_id": f"abc{i}",
                    "message": f"Commit {i}",
                    "author_name": "Alice",
                    "author_timestamp": 1000 + i,
                    "branches": ["release/prod"] if i % 2 else ["main"],
                }
                for i in range(60)
            ],
        },
    )
    assert bitbucket["total_commit_count"] == 60
    assert bitbucket["branch_mode"] == "all"
    assert len(bitbucket["recent_commits"]) == 12
    assert len(bitbucket["repositories"]) == 1
    assert len(bitbucket["repositories"][0]["recent_commits"]) == 3
    assert bitbucket["repository_commit_counts"] == {"RIVER/service-a": 40}
    assert bitbucket["author_counts"] == {"Alice": 60}
    assert bitbucket["branch_counts"] == {"main": 30, "release/prod": 30}


@pytest.mark.asyncio
async def test_large_jira_ticket_search_keeps_quality_rollup_without_hard_cap(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    jira = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="search_jira_tickets",
        result={
            "jql": 'project in ("ACME") AND assignee in ("alice") ORDER BY updated DESC',
            "api_version": "2",
            "total": 277,
            "results": [
                {
                    "ticket_id": f"ACME-{index}",
                    "summary": "Alice Example work item with enough detail to need bounded model-visible text",
                    "status": "In Progress" if index % 2 else "Done",
                    "assignee": "Alice Example",
                    "reporter": "Alice Example" if index % 3 == 0 else "Risk User",
                    "creator": "Alice Example",
                    "priority": "High" if index % 5 == 0 else "Medium",
                    "issue_type": "Task" if index % 4 else "Bug",
                    "created": "2026-01-02T09:00:00.000+0100",
                    "updated": "2026-01-03T10:00:00.000+0100",
                }
                for index in range(100)
            ],
        },
    )

    assert not _contains_hard_cap(jira)
    assert jira["total"] == 277
    assert jira["count"] == 100
    assert jira["returned_count"] == 20
    assert jira["omitted_count"] == 80
    assert jira["status_counts"] == {"Done": 50, "In Progress": 50}
    assert jira["issue_type_counts"] == {"Task": 75, "Bug": 25}
    assert jira["top_assignees"] == {"Alice Example": 100}
    assert len(jira["results"]) == 20
    assert jira["results"][0]["ticket_id"] == "ACME-0"


@pytest.mark.asyncio
async def test_large_bitbucket_commit_search_keeps_quality_rollup_without_hard_cap(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    repositories = []
    commits = []
    for repo_index in range(7):
        repo_commits = []
        for commit_index in range(40):
            commit = {
                "project_key": "ACME",
                "repo_slug": f"service-{repo_index}",
                "repository_label": f"ACME/service-{repo_index}",
                "display_id": f"{repo_index:02d}{commit_index:03d}",
                "message": "Alice Example implementation commit with enough message detail to require truncation",
                "author_name": "Alice Example",
                "author_timestamp": 100000 + repo_index * 1000 + commit_index,
                "branches": ["main"] if commit_index % 2 else ["release/1.0"],
            }
            repo_commits.append(commit)
            commits.append(commit)
        repositories.append(
            {
                "project_key": "ACME",
                "repo_slug": f"service-{repo_index}",
                "label": f"ACME/service-{repo_index}",
                "branch_mode": "all",
                "branches_scanned": ["main", "release/1.0", "feature/deep-investigation"],
                "commit_count": len(repo_commits),
                "commits": repo_commits,
            }
        )
    commits.sort(key=lambda item: item["author_timestamp"], reverse=True)

    bitbucket = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="list_recent_bitbucket_commits",
        result={
            "days": 30,
            "cutoff_utc": "2026-05-14T00:00:00Z",
            "branch_mode": "all",
            "author_filter": ["alice", "Alice Example"],
            "total_commit_count": len(commits),
            "repositories": repositories,
            "commits": commits,
        },
    )

    assert not _contains_hard_cap(bitbucket)
    assert bitbucket["total_commit_count"] == 280
    assert bitbucket["repository_count"] == 7
    assert bitbucket["returned_repository_count"] == 7
    assert bitbucket["returned_global_commit_count"] == 12
    assert bitbucket["author_counts"] == {"Alice Example": 280}
    assert bitbucket["branch_counts"] == {"main": 140, "release/1.0": 140}
    assert len(bitbucket["repositories"]) == 7
    assert len(bitbucket["repositories"][0]["recent_commits"]) == 3
    assert len(bitbucket["recent_commits"]) == 12
