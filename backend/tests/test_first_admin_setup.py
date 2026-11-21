"""First-start admin setup: no built-in password, a one-time setup code from the server log."""

import pytest
from sqlalchemy import select

from app.config import Settings, _security_sensitive_default_fields, get_settings
from app.models import User
from app.services.auth import first_admin, verify_password

STRONG_PASSWORD = "first-Admin-Pw-2026"


async def _make_admin_pending(db) -> User:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    admin.auth_source = first_admin.AUTH_SOURCE_SETUP_PENDING
    await db.flush()
    return admin


def _form(code: str, **overrides) -> dict:
    return {"code": code, "display_name": "Erika Muster", "email": "erika@example.org", "password": STRONG_PASSWORD} | overrides


def test_seed_without_configured_password_leaves_the_admin_pending(monkeypatch):
    monkeypatch.setenv("ADMIN_DEFAULT_PASSWORD", "")
    get_settings.cache_clear()
    try:
        credential = first_admin.seed_credential()
    finally:
        get_settings.cache_clear()
    assert credential.auth_source == first_admin.AUTH_SOURCE_SETUP_PENDING
    assert not verify_password("", credential.password_hash)


def test_configured_password_keeps_the_unattended_path(monkeypatch):
    monkeypatch.setenv("ADMIN_DEFAULT_PASSWORD", STRONG_PASSWORD)
    get_settings.cache_clear()
    try:
        credential = first_admin.seed_credential()
    finally:
        get_settings.cache_clear()
    assert credential.auth_source == first_admin.AUTH_SOURCE_LOCAL
    assert verify_password(STRONG_PASSWORD, credential.password_hash)


def test_empty_admin_password_is_not_an_insecure_default():
    settings = Settings(
        _env_file=None,
        debug=True,
        jwt_secret="a" * 40,
        encryption_key="b" * 40,
        admin_default_password="",
        cors_allowed_origins="https://octryx.example.org",
        force_secure_auth_cookies=True,
    )
    fields = _security_sensitive_default_fields(settings)
    assert "admin_default_password" not in fields
    assert "admin_email" not in fields


def test_setup_code_is_stable_and_per_install():
    code = first_admin.setup_code("admin-id-1")
    assert code == first_admin.setup_code("admin-id-1")
    assert code != first_admin.setup_code("admin-id-2")
    assert len(code) == 14 and code.count("-") == 2


@pytest.mark.asyncio
async def test_login_page_sends_a_fresh_install_to_setup(client, db):
    await _make_admin_pending(db)
    response = await client.get("/chat/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == first_admin.SETUP_PATH
    page = await client.get(first_admin.SETUP_PATH)
    assert page.status_code == 200
    assert "Create the administrator" in page.text


@pytest.mark.asyncio
async def test_wrong_code_is_refused(client, db):
    await _make_admin_pending(db)
    response = await client.post(first_admin.SETUP_PATH, data=_form("AAAA-BBBB-CCCC"), follow_redirects=False)
    assert response.status_code == 400
    assert "setup code is not correct" in response.text
    assert await first_admin.pending_admin(db) is not None


@pytest.mark.asyncio
async def test_setup_creates_the_admin_once(client, db):
    admin = await _make_admin_pending(db)
    code = first_admin.setup_code(admin.id)

    short = await client.post(first_admin.SETUP_PATH, data=_form(code, password="short"), follow_redirects=False)
    assert short.status_code == 400

    done = await client.post(first_admin.SETUP_PATH, data=_form(code.lower()), follow_redirects=False)
    assert done.status_code == 303
    assert done.headers["location"] == "/chat?area=help&tab=setup"
    assert "access_token" in done.headers.get("set-cookie", "")

    await db.refresh(admin)
    assert admin.auth_source == first_admin.AUTH_SOURCE_LOCAL
    assert admin.email == "erika@example.org"
    assert verify_password(STRONG_PASSWORD, admin.password_hash)

    login = await client.post("/api/v1/auth/login", data={"username": "admin", "password": STRONG_PASSWORD})
    assert login.status_code == 200

    again = await client.post(first_admin.SETUP_PATH, data=_form(code), follow_redirects=False)
    assert again.status_code == 409
    closed = await client.get(first_admin.SETUP_PATH, follow_redirects=False)
    assert closed.status_code == 303


def test_setup_code_is_one_greppable_line_on_stderr(capsys):
    admin = User(id="admin-id-log", username="admin", email="a@b.c", password_hash="x")
    first_admin.log_setup_code(admin)
    lines = [line for line in capsys.readouterr().err.splitlines() if "setup" in line]
    assert len(lines) == 1
    assert lines[0].startswith("[setup] ") and lines[0].endswith(first_admin.setup_code("admin-id-log"))
    assert first_admin.SETUP_PATH in lines[0]
