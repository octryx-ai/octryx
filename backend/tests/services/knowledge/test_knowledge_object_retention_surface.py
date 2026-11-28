"""Retention reports without addresses, isolation from the agent surface and the admin-only operator routes."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.models.project.knowledge_object_retention import RETENTION_MODE_REPORT_ONLY
from app.services.knowledge.objects import content_digest
from app.services.knowledge.retention.errors import RetentionState
from app.services.knowledge.retention.reconcile import reconcile_workspace
from app.services.knowledge.retention.reports import latest_run_report
from app.services.knowledge.runtime import EvidenceRuntime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.services.knowledge.knowledge_object_retention_support import (
    ABANDONED,
    OPERATOR,
    _abandon,
    _authorized,
    _wired,
)
from tests.support.knowledge_evidence_s3_support import PREFIX


@pytest.fixture
def as_user(db):
    from app.main import app
    from app.services.auth import get_current_user

    def _install(user):
        app.dependency_overrides[get_current_user] = lambda: user

    yield _install
    app.dependency_overrides.pop(get_current_user, None)


def _body_without_request_id(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "request_id"}


def _admin_base(workspace_id: str) -> str:
    return f"/api/v1/admin/knowledge/retention/workspaces/{workspace_id}"


async def test_a_report_carries_measurements_and_never_an_address(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    key = await _abandon(runtime, client, authorized, age_hours=200)
    digest = content_digest(ABANDONED)
    await reconcile_workspace(db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR)

    report = await latest_run_report(db, workspace_id)
    assert report is not None and len(report.findings) == 1
    rendered = json.dumps(
        {
            "report": {name: str(getattr(report, name)) for name in report.__slots__ if name != "findings"},
            "findings": [
                {name: str(getattr(finding, name)) for name in finding.__slots__}
                for finding in report.findings
            ],
        }
    )

    for secret in (key, digest, maintain.bucket, PREFIX, "127.0.0.1"):
        assert secret not in rendered, secret
    assert report.findings[0].byte_size == len(ABANDONED)
    assert report.findings[0].observed_age_hours >= 200


async def test_the_retention_service_is_not_reachable_from_the_agent_surface():
    backend = Path(__file__).resolve().parents[3]
    forbidden = ("knowledge.retention", "knowledge_retention", "objects.maintenance", "objects import maintenance")
    for area in ("app/tools", "app/agent"):
        for path in sorted((backend / area).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for name in forbidden:
                assert name not in source, f"{path.relative_to(backend)} references {name}"
    assert "maintenance" not in {field for field in EvidenceRuntime.__slots__}
    tree = ast.parse((backend / "app/services/knowledge/runtime.py").read_text(encoding="utf-8"))
    imported = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("retention" in module or "maintenance" in module for module in imported)


async def test_the_operator_routes_expose_policy_and_report_only():
    from app.api.routes.knowledge import knowledge_object_retention as routes

    paths = {(sorted(route.methods - {"HEAD", "OPTIONS"})[0], route.path) for route in routes.router.routes}
    suffixes = {(method, path.rsplit("{workspace_id}", 1)[-1]) for method, path in paths}
    assert suffixes == {
        ("GET", "/policy"),
        ("PUT", "/policy"),
        ("GET", "/runs/latest"),
    }
    source = Path(routes.__file__).read_text(encoding="utf-8")
    for name in ("reconcile_workspace", "build_object_maintenance"):
        assert name not in source, name


def test_every_failure_state_has_an_explicit_transport_mapping():
    from app.api.routes.knowledge import knowledge_object_retention as routes

    assert set(routes._STATUS_BY_STATE) == set(RetentionState) - {RetentionState.OK}


async def test_the_operator_routes_require_a_global_admin(client, db, as_user):
    workspace_id = await seed_workspace(db)
    base = _admin_base(workspace_id)

    assert (await client.get(f"{base}/policy")).status_code == 401

    owner_id = await seed_member(db, workspace_id=workspace_id, role="owner")
    as_user(await fetch_user(db, owner_id))
    assert (await client.get(f"{base}/policy")).status_code == 403
    assert (
        await client.put(f"{base}/policy", json={"mode": RETENTION_MODE_REPORT_ONLY})
    ).status_code == 403


async def test_the_operator_routes_round_trip_policy_and_report(client, db, as_user, auth_user):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, object_client = _wired()
    key = await _abandon(runtime, object_client, authorized, age_hours=200)
    as_user(auth_user)
    base = _admin_base(workspace_id)

    assert (await client.get(f"{base}/runs/latest")).json() == {
        "workspace_id": workspace_id,
        "reconciled": False,
    }
    default_policy = (await client.get(f"{base}/policy")).json()
    assert default_policy["mode"] == RETENTION_MODE_REPORT_ONLY
    assert default_policy["explicit"] is False and "allows_deletion" not in default_policy

    refused = await client.put(f"{base}/policy", json={"mode": "delete_approved", "min_object_age_hours": 24})
    assert refused.status_code == 400
    updated = await client.put(
        f"{base}/policy",
        json={"mode": RETENTION_MODE_REPORT_ONLY, "min_object_age_hours": 24, "legal_hold": False},
    )
    assert updated.status_code == 200
    assert (updated.json()["explicit"], updated.json()["legal_hold"]) == (True, False)
    await reconcile_workspace(db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR)

    report = await client.get(f"{base}/runs/latest")
    body = report.json()

    assert report.status_code == 200 and body["reconciled"] is True
    assert body["counts"]["unreferenced_objects"] == 1 and body["counts"]["deletion_candidates"] == 1
    finding = body["findings"][0]
    assert set(finding) == {"finding_id", "byte_size", "observed_age_hours", "age_eligible", "state"}
    for secret in (key, content_digest(ABANDONED), maintain.bucket, PREFIX):
        assert secret not in report.text, secret
    assert (maintain.bucket, key) in object_client.source.objects


async def test_an_unreconciled_or_unknown_workspace_answers_without_disclosure(client, db, as_user, auth_user):
    as_user(auth_user)
    unknown = await client.get(f"{_admin_base('11111111-2222-3333-4444-555555555555')}/policy")
    malformed = await client.get(f"{_admin_base('not-a-uuid')}/policy")

    assert unknown.status_code == 404 and malformed.status_code == 404
    assert _body_without_request_id(unknown.json()) == _body_without_request_id(malformed.json())
