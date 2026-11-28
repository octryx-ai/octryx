"""Contract for the four-eyes decision and its development-only exception (decision A2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.models import AuditLog
from app.services.governance import four_eyes
from app.services.governance.four_eyes import (
    DEV_SELF_APPROVAL_AUDIT_ACTION,
    dev_self_approval_permitted,
    evaluate_four_eyes,
)
from app.services.prompt_catalog import lifecycle as prompt_lifecycle

_LOOPBACK_ORIGINS = "http://localhost:8090,http://127.0.0.1:8090"


def _settings(*, flag: bool, profile: str = "local", origins: str = _LOOPBACK_ORIGINS) -> Settings:
    return Settings.model_construct(
        four_eyes_dev_self_approval=flag, runtime_profile=profile, cors_allowed_origins=origins
    )


def test_different_users_are_approved_without_the_exception():
    decision = evaluate_four_eyes("requester", "reviewer", settings=_settings(flag=False))

    assert decision.status == "approved"
    assert decision.dev_exception is False
    assert evaluate_four_eyes("requester", None, settings=_settings(flag=True)).status == "missing_approver"


def test_self_approval_is_refused_by_default():
    decision = evaluate_four_eyes("admin", "admin", settings=_settings(flag=False))

    assert decision.status == "invalid_self_approval"
    assert decision.dev_exception is False


def test_self_approval_is_allowed_with_the_flag_on_a_local_stack():
    # Local acceptance stack: production-like "staging" profile, loopback origins only.
    decision = evaluate_four_eyes("admin", "admin", settings=_settings(flag=True, profile="staging"))

    assert decision.status == "approved_dev_self_approval"
    assert decision.dev_exception is True


@pytest.mark.parametrize(
    ("profile", "origins"),
    [
        ("production", _LOOPBACK_ORIGINS),
        # EKS sets no profile (default "local") but serves a network origin.
        ("local", "https://octryx.example.com"),
        ("local", f"{_LOOPBACK_ORIGINS},https://octryx.example.com"),
        ("local", ""),
    ],
)
def test_self_approval_is_refused_with_the_flag_when_production_is_not_excluded(profile, origins):
    settings = _settings(flag=True, profile=profile, origins=origins)

    assert dev_self_approval_permitted(settings) is False
    assert evaluate_four_eyes("admin", "admin", settings=settings).status == "invalid_self_approval"


def test_startup_refuses_the_flag_outside_development_and_accepts_the_ranger_shape():
    secure = {
        "jwt_secret": "four-eyes-test-jwt-secret-0123456789",
        "encryption_key": "four-eyes-test-encryption-key-0123",
        "admin_default_password": "four-eyes-Test-Pw-12345",
        "admin_email": "admin@four-eyes.test",
        "database_url": "postgresql+asyncpg://octryx:unused@postgres:5432/octryx",
        "force_secure_auth_cookies": True,
        "debug": False,
        "four_eyes_dev_self_approval": True,
    }
    with pytest.raises(ValidationError) as refused:
        Settings(**secure, runtime_profile="local", cors_allowed_origins="https://octryx.example.com")
    assert "four-eyes self-approval exception is development-only" in str(refused.value)

    local_staging = Settings(**secure, runtime_profile="staging", cors_allowed_origins=_LOOPBACK_ORIGINS)
    assert dev_self_approval_permitted(local_staging) is True


@pytest.mark.asyncio
async def test_a_self_approved_prompt_publish_succeeds_only_under_the_dev_flag(db, monkeypatch, auth_user):
    _template, version = await prompt_lifecycle.create_draft(
        db, key="secure_work.gateway.deny.path_denied", scope_type="global", scope_id=None,
        body="Reviewed: {tool} is outside the allowed paths ({rule_id}).", change_note="", user=auth_user,
    )
    await prompt_lifecycle.submit_for_review(db, version_id=version.id, user=auth_user)

    monkeypatch.setattr(four_eyes, "get_settings", lambda: _settings(flag=False))
    with pytest.raises(prompt_lifecycle.PromptCatalogRefusal) as refused:
        await prompt_lifecycle.publish(db, version_id=version.id, user=auth_user, approval_id=None, self_approve=True)
    assert refused.value.code == "self_approval_not_allowed"

    monkeypatch.setattr(four_eyes, "get_settings", lambda: _settings(flag=True))
    published, gate = await prompt_lifecycle.publish(
        db, version_id=version.id, user=auth_user, approval_id=None, self_approve=True
    )

    assert published.state == "published"
    assert (gate["status"], gate["dev_self_approval"], gate["approval_mode"]) == ("approved_dev_self_approval", True, "self")
    audit_rows = (
        (await db.execute(select(AuditLog).where(AuditLog.action == DEV_SELF_APPROVAL_AUDIT_ACTION)))
        .scalars()
        .all()
    )
    assert [(row.resource_type, row.resource_id, row.user_id) for row in audit_rows] == [
        ("prompt_template_version", version.id, auth_user.id)
    ]
    assert audit_rows[0].details == {
        "approval_id": published.approval_id,
        "requested_by": auth_user.id,
        "approved_by": auth_user.id,
        "four_eyes_status": "approved_dev_self_approval",
        "approval_mode": "self",
    }
