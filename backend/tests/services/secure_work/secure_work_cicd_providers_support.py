"""Shared helpers for the test_secure_work_cicd_providers_* modules."""

from __future__ import annotations

from sqlalchemy import select

from app.models import WorkItem


def _work_item(**overrides) -> WorkItem:
    payload = {
        "source_type": "jira",
        "source_instance": "cicd-test",
        "source_key": "OCX-336",
        "source_project_key": "OCX",
        "title": "Wire CI/CD provider evidence",
        "source_status": "Open",
        "work_state": "testing",
        "sync_state": "imported",
    }
    payload.update(overrides)
    return WorkItem(**payload)


def _provider_payload(**overrides) -> dict:
    payload = {
        "name": "Jenkins shop non-prod",
        "description": "Acme Orders Jenkins provider.",
        "provider_type": "jenkins",
        "base_url": "https://jenkins.example.test",
        "credential_ref": "secret://jenkins/nonprod-api-token",
        "allowed_actions": [
            "discover_jobs",
            "discover_builds",
            "read_logs",
            "read_artifacts",
            "read_tests",
            "trigger",
            "rerun",
            "cancel",
        ],
        "job_scopes": [{"job_name": "acme-orders/*", "enabled": True}],
        "polling": {"mode": "polling", "interval_seconds": 300},
        "webhook": {"enabled": True, "secret_ref": "secret://jenkins/webhook"},
        "repository_mapping": {"acme-orders/api": "acme-orders/api-main"},
        "metadata": {"owner": "platform"},
        "is_active": True,
    }
    payload.update(overrides)
    return payload


async def _create_provider(client, auth_headers, **overrides) -> dict:
    from app.db import core as db_core
    from app.models import User, WorkCicdProviderConfig

    payload = _provider_payload(**overrides)
    async with db_core.async_session_factory() as session:
        admin = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
        row = WorkCicdProviderConfig(name=payload["name"], provider_type="jenkins", base_url=payload["base_url"],
                                     credential_ref=payload["credential_ref"], allowed_actions_json=payload["allowed_actions"],
                                     job_scopes_json=payload["job_scopes"], created_by=admin.id)
        session.add(row)
        await session.commit()
        return {"id": row.id, "name": row.name}
