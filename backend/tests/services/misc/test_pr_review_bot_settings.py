"""The bot's settings and access: a review-only checkout needs the repository's read operation (also on Bitbucket), members read the settings, only admins switch the bot on or sync now, and a panel save keeps the bot on."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.models import AuditLog
from app.services.pr_review_bot import sync as bot_sync
from tests.pr_review_bot_flow_support import _no_background, _workspace  # noqa: F401


async def test_a_review_only_checkout_needs_the_repositorys_read_operation_not_branch(monkeypatch):
    from types import SimpleNamespace

    from app.tools.connectors import github_repository_prepare as source

    asked = []

    async def operation(_context, *, owner, repo, operation):
        asked.append(operation)
        return {"error": "stop here"}

    monkeypatch.setattr(source, "require_github_repository_operation", operation)
    monkeypatch.setattr(source, "_resolve_github_repo", lambda _context, _params: ("acme", "pay"))
    context = SimpleNamespace(project_config={}, project_ids=["ws"], db=None)
    await source.PrepareGitHubRepositoryTool().execute({"repository": "acme/pay", "review_only": True}, context)
    await source.PrepareGitHubRepositoryTool().execute({"repository": "acme/pay"}, context)
    assert asked == ["read", "branch"]


async def test_members_read_the_bot_settings_and_only_admins_switch_it_on_or_sync_now(db, monkeypatch):
    from types import SimpleNamespace

    from app.api.routes.workflows import pr_review_bot as routes

    project_id, record, _hook = await _workspace(db, trigger="off")
    roles = {"admin": "admin", "dev": "member"}

    async def role(_db, user_id, _project_id):
        return roles.get(user_id)

    routes.get_project_role_for_user = role
    try:
        view = await routes.get_bot_settings(project_id, current_user=SimpleNamespace(id="dev"), db=db)
        assert (view["can_edit"], view["repositories"][0]["repository"]) == (False, "github:acme/pay")
        assert view["webhook_configured"] is True
        refused = await routes.put_bot_settings(project_id, record.id, {"trigger": "both"},
                                                current_user=SimpleNamespace(id="dev"), db=db)
        assert refused.status_code == 403
        bad = await routes.put_bot_settings(project_id, record.id, {"trigger": "always"},
                                            current_user=SimpleNamespace(id="admin"), db=db)
        assert bad.status_code == 400
        twice = await routes.put_bot_settings(project_id, record.id, {"trigger": "both", "protected_branches": [
            "main", "main"]}, current_user=SimpleNamespace(id="admin"), db=db)
        assert json.loads(twice.body) == {"state": "denied", "reason": "protected_branch_invalid",
                                          "path": "protected_branches[1]"}
        saved = await routes.put_bot_settings(project_id, record.id, {"trigger": "both", "protected_branches": [
            "main"]}, current_user=SimpleNamespace(id="admin"), db=db)
        assert saved["settings"] == {"trigger": "both", "protected_branches": ["main"], "review_drafts": False,
                                     "fix_runs": False, "size_limit_lines": 800, "size_limit_files": 25,
                                     "hotspot_paths": [], "status_policy": "gate"}
        assert saved["webhook_configured"] is True
        admin = SimpleNamespace(id="admin")
        await routes.put_bot_settings(project_id, record.id, {"fix_runs": True, "size_limit_lines": 1200},
                                      current_user=admin, db=db)
        kept = await routes.put_bot_settings(project_id, record.id, {"trigger": "sync"}, current_user=admin, db=db)
        assert {key: kept["settings"][key] for key in ("trigger", "protected_branches", "fix_runs",
                                                       "size_limit_lines")} == {
            "trigger": "sync", "protected_branches": ["main"], "fix_runs": True, "size_limit_lines": 1200}
        policy = await routes.put_bot_settings(project_id, record.id, {"status_policy": "inform"}, current_user=admin,
                                               db=db)
        assert {key: policy["settings"][key] for key in ("status_policy", "fix_runs", "size_limit_lines",
                                                         "size_limit_files")} == {
            "status_policy": "inform", "fix_runs": True, "size_limit_lines": 1200, "size_limit_files": 25}
        audits = (await db.execute(select(AuditLog).where(AuditLog.resource_id == record.id))).scalars().all()
        assert [audit.action for audit in audits] == ["pr_review_bot.settings_changed"] * 4
        synced = []

        async def sync(_db, row, *, reasons):
            synced.append(row.id)
            reasons["draft"] = 1
            return {"started": 1, "skipped": 1}

        monkeypatch.setattr(bot_sync, "sync_repository", sync)
        member = await routes.sync_now(project_id, record.id, current_user=SimpleNamespace(id="dev"), db=db)
        assert member.status_code == 403 and synced == []
        assert await routes.sync_now(project_id, record.id, current_user=SimpleNamespace(id="admin"), db=db) == {
            "repository": "github:acme/pay", "outcomes": {"started": 1, "skipped": 1},
            "skipped_reasons": {"draft": 1}}
        unknown = await routes.put_bot_settings("no-such-workspace", record.id, {"trigger": "off"},
                                                current_user=SimpleNamespace(id="nobody"), db=db)
        assert json.loads(unknown.body)["reason"] == "workspace_not_found"
    finally:
        from app.services.access_control import get_project_role_for_user

        routes.get_project_role_for_user = get_project_role_for_user


async def test_saving_the_repository_in_the_panel_keeps_the_bot_on_and_unsent_fields(db):
    from app.services.code_intelligence.repository import update_code_repository

    _project_id, record, _hook = await _workspace(db, trigger="sync")
    record.config_json = {**record.config_json, "operation_policy": {"read": True, "pr": True}}
    await db.flush()
    saved = await update_code_repository(db, record.id, {"description": "Test repo",
                                                         "config_json": {"operation_policy": {"read": True}}})
    await db.refresh(record)
    assert record.config_json["pr_review_bot"]["trigger"] == "sync"
    assert record.config_json["operation_policy"] == {"read": True}
    assert (record.provider, record.name, saved["description"]) == ("github", "acme/pay", "Test repo")
    await update_code_repository(db, record.id, {"default_branch": "develop"})
    await db.refresh(record)
    assert (record.default_branch, record.config_json["pr_review_bot"]["trigger"]) == ("develop", "sync")


async def test_a_review_only_bitbucket_checkout_needs_read_not_branch(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.tools.bitbucket_impl import _bitbucket_sync_repo as sync_repo

    asked = []

    async def operation(_db, *, project_ids, provider, operation, repository_refs):
        asked.append(operation)
        raise HTTPException(status_code=403, detail="stop here")

    monkeypatch.setattr(sync_repo, "require_project_repository_operation", operation)
    monkeypatch.setattr(sync_repo, "_is_repo_allowed", lambda *_args: True)
    context = SimpleNamespace(project_config={}, project_ids=["ws"], db=None)
    for params in ({"review_only": True}, {}):
        answer = await sync_repo.PrepareBitbucketRepository().execute(
            {"project_key": "SHOP", "repo_slug": "demo-shop", **params}, context)
        assert answer == {"error": "stop here"}
    assert asked == ["read", "branch"]
