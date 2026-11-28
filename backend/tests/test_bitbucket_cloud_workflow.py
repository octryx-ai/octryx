"""Workflow B on Bitbucket Cloud: the run's actions, CI, webhooks and Knowledge sync on a Cloud connection."""

from __future__ import annotations

from sqlalchemy import select

from app.models import UserLinkedAccount
from app.services.workflow_runs.platform import bitbucket_cloud, repo_ref, scm
from app.services.workflow_runs.platform.dispatch import read_outcome
from tests.bitbucket_cloud_workflow_support import EMAIL, _cloud_workspace, _run
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.phased_workflow_fixtures import admin_user

ACCOUNT = "557058:00000000-0000-0000-0000-00000000000a"


async def test_on_cloud_the_requester_reviews_by_atlassian_account(db, monkeypatch) -> None:
    admin = await admin_user(db)
    workspace_id = await _cloud_workspace(db)
    run, ref = _run(workspace_id, admin.id), repo_ref.parse_repository("bitbucket:acme/payments")
    assert await bitbucket_cloud.is_cloud_repository(db, run, ref.args())
    assert not await bitbucket_cloud.is_cloud_repository(db, _run(await seed_workspace(db), admin.id), ref.args())

    lookups: list[dict] = []
    answers = [{"users": [{"account_id": ACCOUNT}]}, {"users": []}]

    async def dispatch(db_, run_, tool, arguments, *, capability_class):
        lookups.append({"tool": tool, **arguments})
        return read_outcome(answers.pop(0))

    monkeypatch.setattr(bitbucket_cloud, "dispatch_tool", dispatch)
    admin.email = EMAIL
    # A Bitbucket Server username of the requester is no Atlassian account: the platform email is looked up.
    db.add(UserLinkedAccount(user_id=admin.id, platform="bitbucket_server", username="admin-on-server"))
    await db.flush()
    chosen = await repo_ref.reviewers_for(db, run, ref)
    assert (chosen.requester, chosen.platform, chosen.unresolved) == (ACCOUNT, "atlassian", "")
    assert lookups == [{"tool": "search_jira_users", "email": EMAIL, "project_key": "PAY"}]
    chosen = await repo_ref.reviewers_for(db, run, ref)
    assert chosen.requester == "" and "Linked accounts" in chosen.unresolved and EMAIL not in chosen.unresolved
    db.add(UserLinkedAccount(user_id=admin.id, platform="atlassian", account_id="{00000000-0000-0000-0000-00000000000a}"))
    await db.flush()
    assert (await repo_ref.reviewers_for(db, run, ref)).requester == "{00000000-0000-0000-0000-00000000000a}"
    assert len(lookups) == 2  # a linked account needs no lookup


async def test_a_requester_whose_own_cloud_connection_opens_the_pr_is_its_author_not_unresolved(db, monkeypatch) -> None:
    from app.models import ConnectorNamedConnection

    admin = await admin_user(db)
    workspace_id = await _cloud_workspace(db)
    run, ref = _run(workspace_id, admin.id, id="00000000-0000-0000-0000-0000000000b1",
                    workflow_kind="phased", workflow_key="ticket-delivery"), \
        repo_ref.parse_repository("bitbucket:acme/payments")
    lookups: list[str] = []

    async def dispatch(db_, run_, tool, arguments, *, capability_class, **_):
        lookups.append(tool)
        if tool == "search_jira_users":
            return read_outcome({"users": []})
        return read_outcome({"id": 9, "url": "https://bitbucket.org/acme/payments/pull-requests/9",
                             "status": "created", "reviewers_unresolved": []})

    monkeypatch.setattr(bitbucket_cloud, "dispatch_tool", dispatch)
    monkeypatch.setattr(scm, "dispatch_tool", dispatch)
    # Someone else (an admin's bot account) saved it: never assumed to be the requester's -> lookup, unresolved.
    chosen = await repo_ref.reviewers_for(db, run, ref)
    assert (chosen.requester, chosen.is_author) == ("", False) and "Linked accounts" in chosen.unresolved
    assert lookups == ["search_jira_users"]

    row = (await db.execute(select(ConnectorNamedConnection).where(
        ConnectorNamedConnection.name == "Bitbucket-Cloud"))).scalar_one()
    row.created_by = admin.id
    await db.flush()
    lookups.clear()
    chosen = await repo_ref.reviewers_for(db, run, ref)
    assert (chosen.requester, chosen.unresolved, chosen.is_author) == ("", "", True) and chosen.names == []
    assert lookups == []

    db.add(run)
    await db.flush()
    outcome = await scm.open_pr(db, run, {})
    assert outcome.ok
    pr_call = lookups[-1]
    assert pr_call == "create_bitbucket_pull_request"
    assert run.pull_request["reviewer_skipped"] == "requester_is_author" and run.pull_request["reviewers"] == []
    assert run.context["reviewer_skipped"] == "requester_is_author"

    # A linked Atlassian account still wins: the tool's own author check then decides.
    db.add(UserLinkedAccount(user_id=admin.id, platform="atlassian", account_id=ACCOUNT))
    await db.flush()
    chosen = await repo_ref.reviewers_for(db, run, ref)
    assert (chosen.requester, chosen.is_author) == (ACCOUNT, False)


async def test_a_shared_platform_cloud_connection_saved_by_the_requester_is_theirs(db, monkeypatch) -> None:
    import uuid

    from app.models import ConnectionWorkspace, ConnectorNamedConnection

    admin = await admin_user(db)
    workspace_id = await seed_workspace(db)
    other_id = await seed_member(db, workspace_id=workspace_id, role="member")
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="bitbucket", project_id=None, scope_key="global", name="Bitbucket-octryx",
        bound_scopes=[], available_in="selected", agent_tools_level="write", is_active=True, created_by=admin.id,
        config={"bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org",
                "bitbucket_username": EMAIL, "bitbucket_token_secret_ref": "ref"})
    db.add(row)
    await db.flush()
    db.add(ConnectionWorkspace(connection_id=row.id, workspace_id=workspace_id))
    await db.flush()
    args = {"project_key": "acme", "repo_slug": "payments"}

    async def no_lookup(*_args, **_kwargs):
        raise AssertionError("no email lookup for the requester's own connection")

    monkeypatch.setattr(bitbucket_cloud, "dispatch_tool", no_lookup)
    assert await bitbucket_cloud.requester_account(db, _run(workspace_id, admin.id), args) == (
        "", bitbucket_cloud.REQUESTER_IS_AUTHOR)
    assert not await bitbucket_cloud.personal_connection(db, _run(workspace_id, other_id), args)
