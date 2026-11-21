"""Admin access to the control plane page, provider saves and adding and reprioritizing runtime models."""

import uuid

import pytest
from sqlalchemy import select

from app.models import ControlPlaneConfig, ControlPlaneRuntimeTarget, LLMProvider, Role, User, UserRole
from app.services.auth import create_access_token
from tests.conftest import ADMIN_PASSWORD
from tests.control_plane_support import _clear_runtime_targets, _set_provider_api_key_secret


async def _make_auth_cookies(client, password: str) -> dict:
    """Log in admin and return auth cookies for subsequent requests.

    Uses the API endpoint so it bypasses the admin login flow entirely,
    avoiding middleware's DB operations during the admin login redirect.
    """
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": password},
    )
    if resp.status_code == 200:
        token = resp.json()["access_token"]
        return {"access_token": token}
    raise RuntimeError(f"Auth login failed ({resp.status_code}): {resp.text}")


async def _create_control_plane_viewer(db):
    viewer_role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    user = User(
        id=str(uuid.uuid4()),
        username="control-plane-viewer",
        email="control-plane-viewer@example.com",
        password_hash="unused",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=viewer_role.id))
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_control_plane_requires_admin_for_page_and_mutations(client, db):
    provider_form = {
        "driver": "bedrock_api",
        "display_name": "Denied Provider",
        "aws_region": "eu-central-1",
        "model_id": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "is_active": "true",
    }

    login_redirect = await client.post("/admin/control-plane/save", data=provider_form)
    assert login_redirect.status_code == 303
    assert login_redirect.headers["location"] == "/chat/login"

    viewer = await _create_control_plane_viewer(db)
    client.cookies.set("access_token", create_access_token(viewer.id), path="/")

    page_response = await client.get("/admin/control-plane")
    assert page_response.status_code == 403

    mutation_cases = [
        ("/admin/control-plane/save", provider_form),
        ("/admin/control-plane/copilot/device/start", {"provider_id": "provider-id"}),
        ("/admin/control-plane/copilot/device/complete", {"provider_id": "provider-id", "flow_id": "flow-id"}),
        (
            "/admin/control-plane/runtime-targets/save",
            {"provider_id": "provider-id", "model_id": "model-id", "is_active": "true"},
        ),
        ("/admin/control-plane/runtime-targets/target-id/move", {"direction": "up"}),
        ("/admin/control-plane/runtime-targets/target-id/toggle", {}),
        ("/admin/control-plane/runtime-targets/target-id/delete", {}),
        ("/admin/control-plane/test-chat", {"prompt": "hello"}),
    ]
    for path, payload in mutation_cases:
        response = await client.post(path, data=payload)
        assert response.status_code == 403, path


@pytest.mark.asyncio
async def test_admin_control_plane_page_and_provider_save(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    page_resp = await client.get("/admin/control-plane")
    assert page_resp.status_code == 200
    assert "Runtime Priority" in page_resp.text
    assert "Add Runtime Target" in page_resp.text
    assert "Copilot Authentication" in page_resp.text
    assert "Connect GitHub Copilot" in page_resp.text
    assert "Save the provider before starting GitHub login." in page_resp.text

    new_page_resp = await client.get("/admin/control-plane?new=true")
    assert new_page_resp.status_code == 200
    assert "Add Provider" in new_page_resp.text

    save_resp = await client.post(
        "/admin/control-plane/save",
        data={
            "driver": "bedrock_api",
            "display_name": "Bedrock QA",
            "aws_region": "eu-central-1",
            "aws_role_arn": "arn:aws:iam::123456789012:role/bedrock-access",
            "model_id": "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "is_active": "true",
        },
    )
    assert save_resp.status_code == 303

    await db.rollback()
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.display_name == "Bedrock QA"))).scalar_one()
    config = (await db.execute(select(ControlPlaneConfig).where(ControlPlaneConfig.name == "default"))).scalar_one()
    assert provider.default_model_id == "anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert config.provider_id != provider.id


@pytest.mark.asyncio
async def test_admin_can_add_multiple_runtime_models_and_reprioritize(client, db):
    await _clear_runtime_targets(db)

    # Create provider using the db fixture session
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Route Provider",
        default_model_id="stepfun/step-3.5-flash:free",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await _set_provider_api_key_secret(db, provider, "route-key")
    await db.commit()

    # Build auth cookies via API login (bypasses admin login middleware).
    # Using /admin/login triggers concurrent DB writes from RLS + audit
    # middlewares, which causes SQLite "database is locked" when the login
    # handler itself also tries to write refresh_tokens.
    cookies = await _make_auth_cookies(client, ADMIN_PASSWORD)

    first_resp = await client.post(
        "/admin/control-plane/runtime-targets/save",
        data={
            "provider_id": provider.id,
            "model_id": "stepfun/step-3.5-flash:free",
            "make_primary": "true",
            "is_active": "true",
        },
        cookies=cookies,
    )
    assert first_resp.status_code == 303

    second_resp = await client.post(
        "/admin/control-plane/runtime-targets/save",
        data={
            "provider_id": provider.id,
            "model_id": "nvidia/nemotron-3-super-120b-a12b:free",
            "is_active": "true",
        },
        cookies=cookies,
    )
    assert second_resp.status_code == 303

    await db.rollback()
    targets = (
        (await db.execute(select(ControlPlaneRuntimeTarget).order_by(ControlPlaneRuntimeTarget.priority)))
        .scalars()
        .all()
    )
    assert [target.model_id for target in targets[:2]] == [
        "stepfun/step-3.5-flash:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
    ]

    move_resp = await client.post(
        f"/admin/control-plane/runtime-targets/{targets[1].id}/move",
        data={"direction": "up"},
        cookies=cookies,
    )
    assert move_resp.status_code == 303

    await db.rollback()
    targets = (
        (await db.execute(select(ControlPlaneRuntimeTarget).order_by(ControlPlaneRuntimeTarget.priority)))
        .scalars()
        .all()
    )
    assert [target.model_id for target in targets[:2]] == [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "stepfun/step-3.5-flash:free",
    ]
