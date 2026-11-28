"""Settings validation rejects insecure production defaults, accepts explicit secure values and handles SQLite database URLs per runtime profile."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_settings_reject_insecure_defaults():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            debug=False,
            jwt_secret="change-me-in-production",
            encryption_key="change-me-32-chars-long-secret!",
            admin_default_password="admin",
            admin_email="admin@localhost",
            cors_allowed_origins="*",
            force_secure_auth_cookies=False,
        )

    message = str(exc_info.value)
    assert "jwt_secret" in message
    assert "encryption_key" in message
    assert "admin_default_password" in message
    assert "admin_email" in message
    assert "cors_allowed_origins" in message
    assert "force_secure_auth_cookies" in message


def test_debug_settings_allow_local_defaults():
    settings = Settings(
        debug=True,
        runtime_profile="local",
        jwt_secret="change-me-in-production",
        encryption_key="change-me-32-chars-long-secret!",
        admin_default_password="admin",
        admin_email="admin@localhost",
    )

    assert settings.debug is True
    assert settings.admin_default_password == "admin"


def test_debug_local_settings_report_local_only_defaults_without_values():
    settings = Settings(
        debug=True,
        runtime_profile="local",
        jwt_secret="change-me-in-production",
        encryption_key="change-me-32-chars-long-secret!",
        admin_default_password="admin",
        admin_email="admin@localhost",
        cors_allowed_origins="*",
        force_secure_auth_cookies=False,
    )

    report = settings.security_defaults_report()

    assert report["status"] == "local_only_defaults"
    assert report["runtime_profile"] == "local"
    assert report["production_like"] is False
    assert report["local_only_defaults_allowed"] is True
    assert set(report["local_only_default_fields"]) == {
        "jwt_secret",
        "encryption_key",
        "admin_default_password",
        "admin_email",
        "cors_allowed_origins",
        "force_secure_auth_cookies",
    }
    rendered = str(report)
    assert "change-me-in-production" not in rendered
    assert "change-me-32-chars-long-secret!" not in rendered
    assert "'admin'" not in rendered


def test_production_like_runtime_profile_rejects_insecure_defaults_even_when_debug_enabled():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            debug=True,
            runtime_profile="production",
            database_url="postgresql+asyncpg://octryx:secret@db/octryx",
            jwt_secret="change-me-in-production",
            encryption_key="change-me-32-chars-long-secret!",
            admin_default_password="admin",
            admin_email="admin@localhost",
            cors_allowed_origins="*",
            force_secure_auth_cookies=False,
        )

    message = str(exc_info.value)
    assert "jwt_secret" in message
    assert "encryption_key" in message
    assert "admin_default_password" in message
    assert "admin_email" in message
    assert "cors_allowed_origins" in message
    assert "force_secure_auth_cookies" in message


def test_production_settings_accept_explicit_secure_values():
    settings = Settings(
        debug=False,
        jwt_secret="x" * 48,
        encryption_key="y" * 48,
        admin_default_password="S3cureAdminPass!",
        admin_email="admin@octryx.local",
        cors_allowed_origins="https://octryx.example",
        force_secure_auth_cookies=True,
    )

    assert settings.debug is False
    assert settings.jwt_secret == "x" * 48
    assert settings.security_defaults_report()["status"] == "secure"


def test_production_settings_reject_wildcard_cors_or_insecure_cookie_flags():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            debug=False,
            jwt_secret="x" * 48,
            encryption_key="y" * 48,
            admin_default_password="S3cureAdminPass!",
            admin_email="admin@octryx.local",
            cors_allowed_origins="*",
            force_secure_auth_cookies=False,
        )

    message = str(exc_info.value)
    assert "cors_allowed_origins" in message
    assert "force_secure_auth_cookies" in message


def test_relative_sqlite_database_url_is_normalized_to_repo_root():
    settings = Settings(
        debug=True,
        database_url="sqlite+aiosqlite:///data/octryx.db",
        jwt_secret="change-me-in-production",
        encryption_key="change-me-32-chars-long-secret!",
        admin_default_password="admin",
        admin_email="admin@localhost",
    )

    expected_path = Path(__file__).resolve().parents[3] / "data" / "octryx.db"
    assert settings.database_url == f"sqlite+aiosqlite:///{expected_path}"


def test_absolute_sqlite_database_url_is_left_unchanged():
    absolute_url = "sqlite+aiosqlite:////tmp/octryx-test.db"
    settings = Settings(
        debug=True,
        database_url=absolute_url,
        jwt_secret="change-me-in-production",
        encryption_key="change-me-32-chars-long-secret!",
        admin_default_password="admin",
        admin_email="admin@localhost",
    )

    assert settings.database_url == absolute_url


def test_local_runtime_profile_allows_sqlite_database_url():
    settings = Settings(
        debug=False,
        runtime_profile="local",
        database_url="sqlite+aiosqlite:///data/octryx.db",
        jwt_secret="x" * 48,
        encryption_key="y" * 48,
        admin_default_password="S3cureAdminPass!",
        admin_email="admin@octryx.local",
        cors_allowed_origins="https://octryx.example",
        force_secure_auth_cookies=True,
    )

    assert settings.runtime_profile == "local"
    assert settings.database_url.startswith("sqlite+aiosqlite:///")


def test_production_like_runtime_profile_rejects_sqlite_database_url():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            debug=False,
            runtime_profile="production",
            database_url="sqlite+aiosqlite:///data/octryx.db",
            jwt_secret="x" * 48,
            encryption_key="y" * 48,
            admin_default_password="S3cureAdminPass!",
            admin_email="admin@octryx.local",
            cors_allowed_origins="https://octryx.example",
            force_secure_auth_cookies=True,
        )

    message = str(exc_info.value)
    assert "SQLite database_url is local/test only" in message
    # The rejection names the settings it concerns and no longer echoes the
    # configured profile. The safe startup rendering is covered by
    # tests/platform/test_settings_validation_policy.py.
    assert "Affected settings: database_url, runtime_profile." in message
    assert "runtime_profile='production'" not in message


def test_production_like_runtime_profile_accepts_postgresql_database_url():
    settings = Settings(
        debug=False,
        runtime_profile="production",
        database_url="postgresql+asyncpg://octryx:secret@db/octryx",
        jwt_secret="x" * 48,
        encryption_key="y" * 48,
        admin_default_password="S3cureAdminPass!",
        admin_email="admin@octryx.local",
        cors_allowed_origins="https://octryx.example",
        force_secure_auth_cookies=True,
    )

    assert settings.runtime_profile == "production"
    assert settings.database_url.startswith("postgresql+asyncpg://")
