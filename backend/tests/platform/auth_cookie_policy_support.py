"""Shared helpers for the test_auth_cookie_policy_* modules."""

from app.config import Settings


def _settings(**overrides) -> Settings:
    values: dict[str, object] = {
        "debug": False,
        "runtime_profile": "local",
        "jwt_secret": "s" * 48,
        "encryption_key": "e" * 32,
        "admin_default_password": "S3cureAdminPass!",
        "admin_email": "admin@octryx.local",
        "cors_allowed_origins": "https://octryx.example",
        "force_secure_auth_cookies": True,
        "trusted_proxy_ips": "",
    }
    values.update(overrides)
    return Settings(**values)


def _forced_secure_settings(**overrides) -> Settings:
    return _settings(**overrides)


def _local_debug_settings(**overrides) -> Settings:
    return _settings(debug=True, force_secure_auth_cookies=False, **overrides)


def _set_cookie_values(response) -> list[str]:
    headers = response.headers
    reader = getattr(headers, "get_list", None) or headers.getlist
    return list(reader("set-cookie"))


def _cookie_headers(response) -> dict[str, str]:
    headers = {}
    for raw in _set_cookie_values(response):
        name = raw.split("=", 1)[0].strip()
        if name in {"access_token", "refresh_token"}:
            headers[name] = raw
    return headers


def _cookie_attributes(raw_cookie: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for part in raw_cookie.split(";")[1:]:
        key, _, value = part.partition("=")
        attributes[key.strip().lower()] = value.strip()
    return attributes


def _is_secure(raw_cookie: str) -> bool:
    return "secure" in _cookie_attributes(raw_cookie)
