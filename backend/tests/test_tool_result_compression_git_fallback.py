"""Pull request and workspace git compression and the global hard cap of the fallback compressor."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Session, ToolResultCompressionLog, User
from app.services.tool_result_compression import compress_tool_result_for_model


@pytest.mark.asyncio
async def test_pull_requests_and_workspace_git_are_compressed(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    pull_requests = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="list_bitbucket_pull_requests",
        result={
            "project_key": "RIVER",
            "repo_slug": "report-builder",
            "state": "OPEN",
            "pull_requests": [
                {
                    "id": 12,
                    "title": "Roll out report-builder startup change",
                    "state": "OPEN",
                    "author": "Alice",
                    "from_branch": "feature/report-builder-startup",
                    "to_branch": "release/prod",
                    "updated_date": 123456,
                    "reviewers": [
                        {"name": "Ana", "approved": True},
                        {"name": "Max", "approved": False},
                    ],
                    "links": "https://example.test/pr/12",
                }
            ],
        },
    )
    assert pull_requests["pull_request_count"] == 1
    assert pull_requests["pull_requests"][0]["approved_count"] == 1

    workspace_git = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="list_workspace_git_commits",
        result={
            "cwd": "/tmp/repo",
            "days": 7,
            "cutoff_utc": "2026-04-01T00:00:00Z",
            "path": "services/report-builder",
            "commit_count": 3,
            "commits": [
                {
                    "commit": "a" * 40,
                    "short_commit": "aaaaaaa",
                    "author_name": "Alice",
                    "author_email": "alice@example.com",
                    "authored_at": "2026-04-01T10:00:00Z",
                    "subject": "Adjust report-builder startup handling",
                },
                {
                    "commit": "b" * 40,
                    "short_commit": "bbbbbbb",
                    "author_name": "Alice",
                    "author_email": "alice@example.com",
                    "authored_at": "2026-04-02T10:00:00Z",
                    "subject": "Add branch-aware sync",
                },
                {
                    "commit": "c" * 40,
                    "short_commit": "ccccccc",
                    "author_name": "Ana",
                    "author_email": "ana@example.com",
                    "authored_at": "2026-04-03T10:00:00Z",
                    "subject": "Document integration",
                },
            ],
        },
    )
    assert workspace_git["commit_count"] == 3
    assert workspace_git["top_authors"][0] == ("Alice", 2)
    assert workspace_git["commits"][0]["short_commit"] == "aaaaaaa"

    logs = (
        (
            await db.execute(
                select(ToolResultCompressionLog).where(
                    ToolResultCompressionLog.session_id == session.id,
                    ToolResultCompressionLog.tool_name.in_(
                        [
                            "list_bitbucket_pull_requests",
                            "list_workspace_git_commits",
                        ]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 2


@pytest.mark.asyncio
async def test_fallback_tool_result_compression_applies_global_hard_cap(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    await db.commit()

    huge_result = {
        "content": "x" * 40000,
        "items": [{"value": "y" * 2000} for _ in range(200)],
    }

    compressed = await compress_tool_result_for_model(
        db,
        session_id=session.id,
        tool_name="unknown_large_tool",
        result=huge_result,
        fallback=lambda _tool_name, result: result,
    )

    assert compressed["_hard_capped"] is True
