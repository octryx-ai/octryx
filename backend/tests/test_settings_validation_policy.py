"""Settings-validation failures must name the field and never the value.

Each case puts a synthetic marker into one setting and makes startup fail, then
proves the marker reaches none of the surfaces an operator or an aggregator sees:
the returned error text, its ``repr``, the rendered traceback, the plain log
rendering and the platform's JSON log rendering. The field location and the stable
reason code must still be there, because a failure nobody can act on is not an
improvement over a leak.

Markers are synthetic, unique per case and never a real secret.
"""

from __future__ import annotations

import pytest
from pydantic_settings import SettingsConfigDict

from app.config import Settings, get_settings
from app.settings_validation_policy import FAILURE_HEADER, SettingsValidationError, load_validated_settings
from tests.settings_validation_policy_support import MARKERS, _operator_surfaces, settings_environment  # noqa: F401


class _EnvFreeSettings(Settings):
    """The real settings contract, but never the developer's ``.env``.

    Same fields and same validators; only the file source is dropped, so a case
    describes the whole configuration it is testing.
    """

    model_config = SettingsConfigDict(env_file=None)


# id -> (environment for the case, expected field location, expected reason code)
REJECTION_CASES = {
    # Early field, credential-bearing: a production-like profile rejects the
    # insecure bootstrap defaults while the database URL carries a password.
    "early_database_url_credential": (
        {
            "RUNTIME_PROFILE": "production",
            "DATABASE_URL": f"postgresql+asyncpg://octryx:{MARKERS['database_url_credential']}@db/oe",
        },
        "jwt_secret",
        "insecure_default_configuration",
    ),
    # Middle field, provider token: the failing setting is a different one, so the
    # marker can only arrive as part of the echoed payload.
    "middle_provider_token": (
        {
            "DEBUG": "true",
            "OPENROUTER_API_KEY": MARKERS["provider_token"],
            "TRUSTED_PROXY_IPS": "10.0.0.0/8, not-an-ip",
        },
        "trusted_proxy_ips",
        "malformed_trusted_proxy_allowlist",
    ),
    # Late field, and the one a probe actually saw: the rejected value is
    # the marker itself.
    "late_proxy_allowlist_value": (
        {"DEBUG": "true", "TRUSTED_PROXY_IPS": MARKERS["proxy_allowlist"]},
        "trusted_proxy_ips",
        "malformed_trusted_proxy_allowlist",
    ),
    # Security-sensitive: a real-looking JWT secret is set, another security
    # default is not.
    "security_jwt_secret": (
        {
            "DEBUG": "false",
            "RUNTIME_PROFILE": "local",
            "JWT_SECRET": MARKERS["jwt_secret"],
            "ENCRYPTION_KEY": "change-me-32-chars-long-secret!",
        },
        "encryption_key",
        "insecure_default_configuration",
    ),
    # Security-sensitive: admin bootstrap credential set, cookie policy invalid.
    "security_admin_bootstrap_credential": (
        {
            "DEBUG": "true",
            "ADMIN_DEFAULT_PASSWORD": MARKERS["admin_password"],
            "AUTH_COOKIE_SAMESITE": "sideways",
        },
        "auth_cookie_samesite",
        "unsupported_auth_cookie_samesite",
    ),
    # Late field, and Pydantic's own error type rather than one of our rejections:
    # the marker is the unparsable value.
    "late_multipart_ceiling_type": (
        {"DEBUG": "true", "MAX_MULTIPART_REQUEST_BYTES": MARKERS["multipart_ceiling"]},
        "max_multipart_request_bytes",
        "int_parsing",
    ),
    # The cardinality bound uses the same value-free startup boundary after
    # its validator rejects an otherwise parseable integer.
    "rate_limit_key_bound": (
        {"DEBUG": "true", "OCTRYX_MAX_RATE_LIMIT_KEYS": "200001"},
        "max_rate_limit_keys",
        "invalid_rate_limit_key_bound",
    ),
}


@pytest.mark.parametrize(("environment", "location", "reason"), REJECTION_CASES.values(), ids=REJECTION_CASES)
def test_a_rejected_setting_is_reported_by_field_and_reason_without_its_value(
    settings_environment: pytest.MonkeyPatch,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    environment: dict[str, str],
    location: str,
    reason: str,
) -> None:
    for name, value in environment.items():
        settings_environment.setenv(name, value)

    with pytest.raises(SettingsValidationError) as failure:
        load_validated_settings(_EnvFreeSettings)

    error = failure.value
    surfaces = _operator_surfaces(error, caplog)
    for marker in MARKERS.values():
        assert marker not in surfaces
    for value in environment.values():
        # The configured values themselves, marker or not. Short enum-like values
        # (a boolean, a profile name) are skipped: they can collide with unrelated
        # words in a rendering, and every case's marker is checked above anyway.
        if len(value) >= 8:
            assert value not in surfaces
    assert (location, reason) in error.safe_field_reasons
    assert FAILURE_HEADER in surfaces
    assert location in str(error) and reason in str(error)
    # No chained original: a cause or context would be rendered by the same
    # surfaces and would carry the payload back.
    assert error.__cause__ is None and error.__context__ is None


def test_the_startup_entrypoint_fails_closed_with_the_safe_rendering(
    settings_environment: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture  # noqa: F811
) -> None:
    """The real ``get_settings`` boundary, not only the loader it delegates to.

    An unparsable ceiling is used because the process environment outranks any
    ``.env`` a checkout may have, so the case fails the same way everywhere.
    """
    settings_environment.setenv("MAX_MULTIPART_REQUEST_BYTES", MARKERS["multipart_ceiling"])
    get_settings.cache_clear()
    try:
        with pytest.raises(SettingsValidationError) as failure:
            get_settings()
        surfaces = _operator_surfaces(failure.value, caplog)
    finally:
        get_settings.cache_clear()

    assert MARKERS["multipart_ceiling"] not in surfaces
    assert ("max_multipart_request_bytes", "int_parsing") in failure.value.safe_field_reasons
    # Startup still fails: nothing was returned and nothing was cached.
    assert get_settings.cache_info().currsize == 0
