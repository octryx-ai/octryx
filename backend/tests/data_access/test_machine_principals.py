from __future__ import annotations

import time
import uuid

from sqlalchemy import select

from app.models import ChannelConfig, ConnectorWatcher, DeviceJob, Webhook
from app.services.data_access import current_viewer, request_scope
from app.services.data_access.machine_principal import bind_authenticated_owner
from app.services.devices.contract import DEVICE_AUDIENCE
from app.services.devices.credential import DeviceCredential, resolve_device_credential
from app.services.inbound_alerts.signature import TIMESTAMP_HEADER, sign_timestamped
from app.services.plugins.package import files_from_folder
from app.services.plugins.ui import issue_token
from app.services.project.private_workspace import ensure_private_workspace
from app.services.webhook_secret import issue_webhook_secret
from tests.devices.device_support import chat_session, device_with_grant, user_named
from tests.services.misc.test_plugins_ui_settings import _install
from tests.support.plugins_support import SHIPPED, _workspace_admin
from tests.workspace_id_route_support import answer_text, refusal_code


async def _private(db, name: str):
    user = await user_named(db, f"{name}-{uuid.uuid4().hex[:6]}")
    return user, (await ensure_private_workspace(db, user)).id


async def _trigger(client, webhook_id: str, secret: str | None = None):
    body = b'{"status": "firing"}'
    headers = {"Content-Type": "application/json"}
    if secret:
        stamp = str(int(time.time()))
        headers |= {TIMESTAMP_HEADER: stamp, "X-Webhook-Signature": sign_timestamped(secret, stamp, body)}
    return await client.post(f"/api/v1/webhooks/{webhook_id}/trigger", content=body, headers=headers)


def _answer(response) -> tuple:
    return response.status_code, refusal_code(response), answer_text(response)


async def test_an_inbound_webhook_of_a_private_workspace_answers_like_an_unknown_one_until_its_secret_checks_out(
        client, db):
    owner, own_workspace = await _private(db, "hook-owner")
    other, _ = await _private(db, "hook-other")
    own = Webhook(project_id=own_workspace, owner_id=owner.id, name="own")
    foreign = Webhook(project_id=own_workspace, owner_id=other.id, name="foreign")  # its creator can't see it
    db.add_all([own, foreign])
    await db.flush()
    own_secret, foreign_secret = await issue_webhook_secret(db, own), await issue_webhook_secret(db, foreign)
    await db.commit()

    unknown = await _trigger(client, str(uuid.uuid4()))
    assert unknown.status_code == 404
    assert _answer(await _trigger(client, own.id)) == _answer(unknown)
    assert _answer(await _trigger(client, own.id, "wrong-secret")) == _answer(unknown)
    assert _answer(await _trigger(client, foreign.id, foreign_secret)) == _answer(unknown)
    assert (await _trigger(client, own.id, own_secret)).status_code not in (401, 404)


async def test_a_watcher_of_a_private_workspace_takes_no_call_without_its_secret(client, db):
    owner, workspace = await _private(db, "watcher-owner")
    watcher = ConnectorWatcher(project_id=workspace, created_by=owner.id, connector_name="jira", name="w",
                               is_active=False, mode="polling")
    db.add(watcher)
    await db.commit()
    unknown = await client.post(f"/api/v1/connector-watchers/{uuid.uuid4()}/webhook", json={})
    secretless = await client.post(f"/api/v1/connector-watchers/{watcher.id}/webhook", json={},
                                   headers={"X-Watcher-Secret": "guess"})
    assert unknown.status_code == 404
    assert _answer(secretless) == _answer(unknown)


async def test_a_plugin_page_reads_as_the_person_its_token_names_not_as_its_installer(client, db, tmp_path):
    user, ours, _ = await _workspace_admin(db)
    install = await _install(client, db, tmp_path, user.id, ours.id, files_from_folder(SHIPPED))
    outsider = await user_named(db, f"plugin-outsider-{uuid.uuid4().hex[:6]}")
    await db.commit()
    page = "/plugin-ui/{install}/{token}/index.html"
    for_installer = await client.get(page.format(install=install["id"], token=issue_token(install["id"], user.id)))
    for_outsider = await client.get(page.format(install=install["id"], token=issue_token(install["id"], outsider.id)))
    assert (for_installer.status_code, for_outsider.status_code) == (200, 404)


async def test_a_channel_in_a_private_workspace_reads_as_that_workspaces_owner(db):
    owner, workspace = await _private(db, "channel-owner")
    channel = ChannelConfig(plugin_id="slack", name="own", project_id=workspace, config="{}")
    db.add(channel)
    await db.commit()
    db.expunge_all()
    with request_scope():
        await bind_authenticated_owner(db, ChannelConfig, channel.id, owner_column=None)
        assert current_viewer().user_id == owner.id
        assert await db.get(ChannelConfig, channel.id) is not None


async def test_a_device_request_reads_as_the_devices_owner(client, db):
    owner, workspace = await _private(db, "device-owner")
    _other, foreign_workspace = await _private(db, "device-other")
    _device, refresh = await device_with_grant(db, owner)
    session = await chat_session(db, owner)
    own, foreign = (DeviceJob(workspace_id=space, owner_user_id=owner.id, device_id=_device.id, session_id=session.id,
                              folder="/home/sample/src", profile="governed")
                    for space in (workspace, foreign_workspace))
    db.add_all([own, foreign])
    await db.commit()
    token = (await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": refresh, "client_id": "octryx-test-client",
        "resource": DEVICE_AUDIENCE})).json()["access_token"]
    db.expunge_all()
    with request_scope():
        assert isinstance(await resolve_device_credential(db, token), DeviceCredential)
        assert current_viewer().user_id == owner.id
        seen = set((await db.execute(select(DeviceJob.id))).scalars())
    assert own.id in seen and foreign.id not in seen
