"""Shared constants and API helpers for the test_workflow_acceptance_b_feature_delivery scenario."""

from __future__ import annotations

import json
from pathlib import Path

from app.models.integration.webhook import Webhook
from app.services.inbound_alerts.signature import sign_body
from app.services.webhook_secret import issue_webhook_secret
from tests.fresh_interpreter_support import run_pytest_probe
from tests.phased_workflow_fixtures import admin_user

TOTALS_TEST = "from pay.totals import round_total\n\n\ndef test_rounds_half_up():\n    assert round_total(2.5) == 3\n"


FEES_TEST = "from pay.fees import fee\n\n\ndef test_fee_is_two_percent():\n    assert fee(100) == 2\n"


CONFIRMED = ["tests/test_totals.py::test_rounds_half_up", "tests/test_fees.py::test_fee_is_two_percent"]


def _pytest(cwd: Path, *targets: str) -> dict:
    done = run_pytest_probe(cwd, *(targets or ("tests",)))
    return {"tool_name": "run_test_suite", "status": "success",
            "result": {"stdout": done.stdout, "exit_code": done.returncode, "all_green": done.returncode == 0}}


EDIT = {"tool_name": "edit_workspace_file", "status": "success", "result": {}}


async def _view(client, headers, run_id: str) -> dict:
    return (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=headers)).json()["run"]


async def _act(client, headers, run_id: str, **body) -> dict:
    answer = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=headers, json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()["run"]


async def _signed(client, db, project_id: str, source_type: str, payload: dict, headers: dict) -> dict:
    admin = await admin_user(db)
    hook = Webhook(project_id=project_id, owner_id=admin.id, name=source_type, source_type=source_type,
                   is_active=True, accept_untimestamped=True)
    db.add(hook)
    await db.flush()
    secret = await issue_webhook_secret(db, hook)
    await db.flush()
    body = json.dumps(payload).encode()
    answer = await client.post(f"/api/v1/webhooks/{hook.id}/trigger", content=body, headers={
        **headers, "X-Hub-Signature-256": sign_body(secret, body)})
    assert answer.status_code == 202, answer.text
    return answer.json()


async def s1_publication_systems(db, project, monkeypatch, *, requester):
    from types import SimpleNamespace

    from app.config import get_settings
    from app.models import BuiltInToolConfig
    from app.services.workflow_runs.documentation import publication_v2, s1_graph
    from app.services.workflow_runs.documentation.write_intent import reserve_publication_intent
    from app.services.workflow_runs.platform.dispatch import ToolOutcome
    from tests.knowledge_evidence_seed_support import seed_member, seed_outsider
    from tests.phased_workflow_fixtures import join_workspace
    from tests.s1_publish_cloud_support import PARENT, SITE, SPACE_KEY, FakeCloudV2

    cloud = FakeCloudV2()
    reader = await seed_member(db, workspace_id=project.id, role="member")
    outsider = await seed_outsider(db)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=project.id, is_active=True, config={
        "confluence_auth_mode": "basic", "confluence_url": SITE, "confluence_username": "docs-bot",
        "confluence_password": "docs-pw", "confluence_allowed_spaces": [{"space_key": SPACE_KEY, "enabled": True}]}))
    await join_workspace(db, requester, project.id)
    policy = dict(project.config.get("tool_policy") or {})
    confluence_tools = ["create_confluence_page", "update_confluence_page", "get_confluence_page"]
    project.config = {**project.config, "tool_policy": {
        **policy, "allowlist": [*policy.get("allowlist", []), *confluence_tools]}, "feature_documentation": {
        "confluence_space_key": SPACE_KEY, "parent_page_id": PARENT,
        "audience_proof": {"semantics": "workspace_readers", "principal_user_id": reader,
                           "outsider_user_id": outsider, "source_key": "docs"},
        "acceptance_environment": {"name": "Acceptance", "kind": "test", "url": "https://acceptance.example.test"}}}
    monkeypatch.setattr(get_settings(), "platform_public_origin", "https://octryx.example.test")

    monkeypatch.setattr(publication_v2, "v2_transport", cloud.transport)  # the publish/reconcile provider seam

    async def reserve(db_, run):  # the reservation resolves its target with the fake's transport
        return await reserve_publication_intent(db_, run, transport=cloud.transport())

    async def synced(_db, run):
        version = dict(s1_graph.facts(run).get("publication") or {}).get("version")
        return ToolOutcome("succeeded", {"page_version": version, "revision_id": "rev-1"})

    async def challenge(_db, run, *, principal_role):
        published = dict(s1_graph.facts(run).get("publication") or {})
        expected = reader if principal_role == "audience" else outsider
        return SimpleNamespace(id=f"receipt-{principal_role}", challenge_id=f"challenge-{principal_role}",
                               expected_principal_id=expected, page_id=published.get("page_id"),
                               page_version=published.get("version"), source_key="docs", expires_at=None)

    async def consumed(_db, run, *, principal_role):
        published = dict(s1_graph.facts(run).get("publication") or {})
        return ToolOutcome("succeeded", {"receipt_id": f"receipt-{principal_role}",
                                         "outcome": "negative" if principal_role == "outsider" else "positive",
                                         "page_id": published.get("page_id"), "page_version": published.get("version"),
                                         "result_digest": "sha256:" + "d" * 64})

    async def still_proven(_db, _run):
        return ToolOutcome("succeeded")

    for name, function in {"reserve_publication_intent": reserve, "sync_published_version": synced,
                           "issue_audience_challenge": challenge, "consume_audience_receipt": consumed,
                           "validate_current_publication_proof": still_proven}.items():
        monkeypatch.setitem(s1_graph.OVERRIDES, name, function)
    await db.commit()
    return cloud
