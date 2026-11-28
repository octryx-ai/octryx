"""Where unauthenticated channel webhooks may be accepted at all."""

from __future__ import annotations

from .four_eyes_dev_policy import dev_self_approval_environment_permitted
from .settings_validation_policy import SettingsFieldError

SETTING_ENV_NAME = "OCTRYX_CHANNEL_WEBHOOK_DEV_UNAUTHENTICATED"


def channel_webhook_dev_environment_permitted(
    debug: bool, runtime_profile: str | None, cors_allowed_origins: str | None
) -> bool:
    return bool(debug) and dev_self_approval_environment_permitted(runtime_profile, cors_allowed_origins)


def validate_channel_webhook_dev_setting(
    enabled: bool, debug: bool, runtime_profile: str | None, cors_allowed_origins: str | None
) -> None:
    if enabled and not channel_webhook_dev_environment_permitted(debug, runtime_profile, cors_allowed_origins):
        raise SettingsFieldError(
            "channel_webhook_dev_exception_outside_development",
            "Unauthenticated channel webhooks are development-only. Unset "
            f"{SETTING_ENV_NAME}, or run with DEBUG=true, a non-production runtime_profile and "
            "only loopback cors_allowed_origins.",
            ("channel_webhook_dev_unauthenticated", "debug", "runtime_profile", "cors_allowed_origins"),
        )


def channel_webhook_dev_bypass_active(settings: object) -> bool:
    return bool(getattr(settings, "channel_webhook_dev_unauthenticated", False)) and (
        channel_webhook_dev_environment_permitted(
            bool(getattr(settings, "debug", False)),
            getattr(settings, "runtime_profile", None),
            getattr(settings, "cors_allowed_origins", None),
        )
    )


__all__ = [
    "SETTING_ENV_NAME",
    "channel_webhook_dev_bypass_active",
    "channel_webhook_dev_environment_permitted",
    "validate_channel_webhook_dev_setting",
]
