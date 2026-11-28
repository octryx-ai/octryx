from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from app.services.admin.provider import admin_runtime_service
from app.services.control_plane_service import (
    delete_runtime_target,
    get_or_create_control_plane_config,
    get_runtime_targets,
    move_runtime_target,
    toggle_runtime_target,
    upsert_runtime_target,
)


async def _audit_log(db, action: str, resource_id: str) -> AuditLog:
    return (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == action,
                AuditLog.resource_id == resource_id,
            )
        )
    ).scalar_one()


def _serialize_runtime_target(
    target: ControlPlaneRuntimeTarget,
    provider: LLMProvider | None,
    model: LLMModel | None = None,
) -> dict:
    return {
        "id": target.id,
        "provider_id": target.provider_id,
        "provider_name": provider.name if provider else "unknown",
        "provider_display_name": provider.display_name or (provider.name if provider else "Unknown"),
        "model_id": target.model_id,
        "supports_tools": bool(model.supports_tools) if model else None,
        "supports_vision": bool(model.supports_vision) if model else None,
        "priority": target.priority,
        "is_active": target.is_active,
        "use_case_tags": target.use_case_tags,
    }


def _runtime_provider(*, name: str, model_id: str) -> LLMProvider:
    return LLMProvider(
        id=str(uuid.uuid4()),
        name=name,
        display_name=name.replace("-", " ").title(),
        provider_family="manual",
        driver="manual",
        runtime_kind="chat",
        default_model_id=model_id,
        is_global=True,
        is_active=True,
    )


def _assert_runtime_audit_has_no_test_secret_values(details: dict) -> None:
    details_text = str(details)
    assert "sk-runtime-audit" not in details_text
    assert "runtime-password-value" not in details_text


@pytest.mark.asyncio
async def test_update_runtime_settings_records_secret_safe_audit_log(db):
    before = await admin_runtime_service.get_runtime_settings(
        db,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
    )
    next_default = 3072 if before["max_output_tokens_default"] != 3072 else 4096
    result = await admin_runtime_service.update_runtime_settings(
        db,
        payload={"max_output_tokens_default": next_default},
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
        actor_user_id="runtime-audit-admin",
    )

    assert result["max_output_tokens_default"] == next_default
    audit = await _audit_log(db, "admin.runtime.settings.updated", "global")
    assert audit.user_id == "runtime-audit-admin"
    assert audit.resource_type == "runtime_settings"
    assert "max_output_tokens_default" in audit.details["changed_keys"]
    assert audit.details["operation"] == "update_runtime_settings"
    assert audit.details["payload_keys"] == ["max_output_tokens_default"]
    _assert_runtime_audit_has_no_test_secret_values(audit.details)


@pytest.mark.asyncio
async def test_runtime_target_mutations_record_secret_safe_audit_logs(db):
    suffix = uuid.uuid4().hex[:8]
    primary_provider = _runtime_provider(name=f"runtime-audit-primary-{suffix}", model_id="model-a")
    secondary_provider = _runtime_provider(name=f"runtime-audit-secondary-{suffix}", model_id="model-c")
    db.add_all([primary_provider, secondary_provider])
    await db.commit()

    created = await admin_runtime_service.add_runtime(
        db,
        payload={
            "provider_id": primary_provider.id,
            "model_id": "model-a",
            "make_primary": True,
            "use_case_tags": ["chat"],
        },
        upsert_runtime_target_func=upsert_runtime_target,
        serialize_runtime_target=_serialize_runtime_target,
        actor_user_id="runtime-audit-admin",
    )
    created_audit = await _audit_log(db, "admin.runtime.target.created", created["id"])
    assert created_audit.user_id == "runtime-audit-admin"
    assert created_audit.resource_type == "runtime_target"
    assert created_audit.details["operation"] == "add_runtime"
    assert "model_id" in created_audit.details["changed_keys"]

    updated = await admin_runtime_service.update_runtime(
        db,
        target_id=created["id"],
        payload={"model_id": "model-b", "is_active": False, "use_case_tags": ["coding"]},
        serialize_runtime_target=_serialize_runtime_target,
        actor_user_id="runtime-audit-admin",
    )
    assert updated["model_id"] == "model-b"
    updated_audit = await _audit_log(db, "admin.runtime.target.updated", created["id"])
    assert set(updated_audit.details["changed_keys"]) >= {"model_id", "is_active", "use_case_tags"}
    assert updated_audit.details["payload_keys"] == ["is_active", "model_id", "use_case_tags"]

    toggled = await admin_runtime_service.toggle_runtime(
        db,
        target_id=created["id"],
        toggle_runtime_target_func=toggle_runtime_target,
        serialize_runtime_target=_serialize_runtime_target,
        actor_user_id="runtime-audit-admin",
    )
    assert toggled["is_active"] is True
    toggled_audit = await _audit_log(db, "admin.runtime.target.toggled", created["id"])
    assert toggled_audit.details["operation"] == "toggle_runtime"
    assert "is_active" in toggled_audit.details["changed_keys"]

    second = await admin_runtime_service.add_runtime(
        db,
        payload={
            "provider_id": secondary_provider.id,
            "model_id": "model-c",
            "make_primary": False,
        },
        upsert_runtime_target_func=upsert_runtime_target,
        serialize_runtime_target=_serialize_runtime_target,
        actor_user_id="runtime-audit-admin",
    )
    before_move = await admin_runtime_service.list_runtimes(
        db,
        get_runtime_targets_func=get_runtime_targets,
        serialize_runtime_target=_serialize_runtime_target,
    )
    second_index = [target["id"] for target in before_move].index(second["id"])
    move_direction = "down" if second_index == 0 else "up"
    expected_index = second_index + 1 if move_direction == "down" else second_index - 1
    moved = await admin_runtime_service.move_runtime(
        db,
        target_id=second["id"],
        direction=move_direction,
        move_runtime_target_func=move_runtime_target,
        get_runtime_targets_func=get_runtime_targets,
        serialize_runtime_target=_serialize_runtime_target,
        actor_user_id="runtime-audit-admin",
    )
    assert [target["id"] for target in moved][expected_index] == second["id"]
    moved_audit = await _audit_log(db, "admin.runtime.target.moved", second["id"])
    assert moved_audit.resource_type == "runtime_targets"
    assert moved_audit.details["operation"] == "move_runtime"
    assert moved_audit.details["direction"] == move_direction

    result = await admin_runtime_service.delete_runtime(
        db,
        target_id=second["id"],
        delete_runtime_target_func=delete_runtime_target,
        actor_user_id="runtime-audit-admin",
    )
    assert result == {"status": "deleted"}
    deleted_audit = await _audit_log(db, "admin.runtime.target.deleted", second["id"])
    assert deleted_audit.resource_type == "runtime_target"
    assert deleted_audit.details["operation"] == "delete_runtime"
    assert deleted_audit.details["after"] == {}
    _assert_runtime_audit_has_no_test_secret_values(deleted_audit.details)


