"""Shared helpers for the remote device session tests."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserDevice
from app.models.security.oauth_provider import OAuthClient, OAuthGrant
from app.services.devices.credential import issue_device_grant

GATEWAY_LOGIN_SCOPES = ["model:invoke", "knowledge:read", "knowledge:write", "work:manage"]


def new_key_pair() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private, base64.urlsafe_b64encode(raw).decode().rstrip("=")


async def oauth_client(db: AsyncSession, client_id: str = "octryx-test-client") -> OAuthClient:
    existing = (await db.execute(select(OAuthClient).where(OAuthClient.client_id == client_id))).scalar_one_or_none()
    if existing is not None:
        return existing
    row = OAuthClient(client_id=client_id, client_name="octryx-claude", redirect_uris=["http://localhost:1/cb"],
                      grant_types=["authorization_code", "refresh_token"], scopes=GATEWAY_LOGIN_SCOPES)
    db.add(row)
    await db.flush()
    return row


async def user_named(db: AsyncSession, username: str) -> User:
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        user = User(username=username, email=f"{username}@example.invalid", password_hash="x", is_active=True)
        db.add(user)
        await db.flush()
    return user


async def device_with_grant(
    db: AsyncSession, user: User, *, name: str = "Test device", folders: list[str] | None = None,
    profiles: list[str] | None = None,
) -> tuple[UserDevice, str]:
    """A registered device of ``user`` and the raw refresh token of its device grant."""
    client = await oauth_client(db)
    _private, public = new_key_pair()
    device = UserDevice(owner_user_id=user.id, name=name, name_key=name.lower(), os="linux", public_key=public,
                        folders=folders or ["/home/sample/src"], profiles=profiles or ["governed"])
    db.add(device)
    await db.flush()
    grant, refresh = await issue_device_grant(db, user_id=user.id, client_id=client.client_id, device_id=device.id,
                                              login_scopes=GATEWAY_LOGIN_SCOPES)
    device.grant_id = grant.id
    await db.flush()
    return device, refresh


async def gateway_login_token(db: AsyncSession, user: User, *, scopes: list[str] | None = None) -> str:
    """A gateway token of ``user``'s ordinary octryx-claude login (no device grant)."""
    from app.services.agent_gateway.contract import GATEWAY_AUDIENCE
    from app.services.oauth_provider import mint_access_token

    client = await oauth_client(db)
    grant_scopes = scopes or GATEWAY_LOGIN_SCOPES
    grant = OAuthGrant(user_id=user.id, client_id=client.client_id, scopes=grant_scopes)
    db.add(grant)
    await db.flush()
    token, _ = mint_access_token(user_id=user.id, client_id=client.client_id, grant_id=grant.id, scopes=grant_scopes,
                                 resource=GATEWAY_AUDIENCE)
    return token


async def member_with_headers(client, db: AsyncSession, username: str) -> tuple[User, dict[str, str]]:
    """A non-admin user with a password, and its API login headers."""
    from app.models import Role, UserRole
    from app.services.auth import hash_password

    user = await user_named(db, username)
    user.password_hash = hash_password("Device-test-pass-1")
    role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.flush()
    response = await client.post("/api/v1/auth/login", data={"username": username, "password": "Device-test-pass-1"})
    assert response.status_code == 200, response.text
    return user, {"Authorization": f"Bearer {response.json()['access_token']}"}


def registration_body(name: str = "Test device", **overrides) -> dict:
    _private, public = new_key_pair()
    return {"name": name, "os": "linux", "public_key": public, "folders": ["/home/sample/src/one",
            "/home/sample/src/two"], "profiles_available": ["governed", "seat"], "client_version": "0.9.0",
            "service_kind": "systemd", **overrides}


class SharedSession:
    """A session factory over the test's own session (no commit is lost, nothing leaks between tests)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def __call__(self):
        return self

    async def __aenter__(self) -> AsyncSession:
        return self.db

    async def __aexit__(self, *exc) -> None:
        return None


class FakeSocket:
    """A WebSocket stand-in: the test feeds frames in and reads what the platform sent."""

    def __init__(self) -> None:
        import asyncio

        self.incoming: asyncio.Queue = asyncio.Queue()
        self.outgoing: asyncio.Queue = asyncio.Queue()
        self.closed: tuple[int, str] | None = None

    async def receive_json(self):
        message = await self.incoming.get()
        if message is None:
            raise RuntimeError("disconnected")
        return message

    async def send_json(self, data) -> None:
        await self.outgoing.put(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed is None:
            self.closed = (code, reason)
        await self.incoming.put(None)

    async def next(self, timeout: float = 2.0):
        import asyncio

        return await asyncio.wait_for(self.outgoing.get(), timeout)


async def keyed_device(db: AsyncSession, user: User, *, name: str = "Keyed device", folders=None, profiles=None):
    """A device with a known private key and a channel token: ``(device, private_key, token)``."""
    from app.services.devices.contract import DEVICE_AUDIENCE
    from app.services.oauth_provider import mint_access_token

    client = await oauth_client(db)
    private, public = new_key_pair()
    device = UserDevice(owner_user_id=user.id, name=name, name_key=name.lower(), os="linux", public_key=public,
                        folders=folders or ["/home/sample/src"], profiles=profiles or ["governed"])
    db.add(device)
    await db.flush()
    grant, _refresh = await issue_device_grant(db, user_id=user.id, client_id=client.client_id, device_id=device.id,
                                               login_scopes=GATEWAY_LOGIN_SCOPES)
    device.grant_id = grant.id
    await db.flush()
    token, _ = mint_access_token(user_id=user.id, client_id=client.client_id, grant_id=grant.id,
                                 scopes=list(grant.scopes), resource=DEVICE_AUDIENCE, expires_minutes=15)
    return device, private, token


def signed_hello(private, device_id: str, nonce: str, **report) -> dict:
    from app.services.devices.channel_protocol import envelope, hello_payload

    signature = base64.urlsafe_b64encode(private.sign(hello_payload(device_id, nonce))).decode().rstrip("=")
    return envelope("hello", {"device_id": device_id, "signature": signature, **report})


async def chat_session(db: AsyncSession, user: User):
    from app.models import Project, Session

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(user_id=user.id, project_id=project.id, agent_type="diagnosis", metadata_={})
    db.add(session)
    await db.flush()
    return session


class RecordingConnection:
    """A connected device as the channel tick sees it: records what the platform sends."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.sent: list[tuple[str, dict]] = []

    async def send(self, message_type: str, body: dict, **extra) -> None:
        self.sent.append((message_type, body))


async def enable_device_runs(db: AsyncSession, project_name: str = "acme-orders", **section):
    """Store a Workspace's device runs section (on by default; a test sets the other keys explicitly)."""
    from app.models import Project

    project = (await db.execute(select(Project).where(Project.name == project_name))).scalar_one()
    config = dict(project.config or {})
    policy = dict(config.get("agent_gateway_policy") or {})
    policy["device_runs"] = {"enabled": True, **section}
    config["agent_gateway_policy"] = policy
    project.config = config
    await db.flush()
    return project
