"""Where unauthenticated channel webhooks may be accepted at all.

Every inbound channel webhook is authenticated by its channel's own scheme
(``services/channel_webhook_auth``). The only exception is a developer driving a channel from a
local stub (the Bot Framework Emulator, a hand-written ``curl``) on a machine-local stack, and
only when ``OCTRYX_CHANNEL_WEBHOOK_DEV_UNAUTHENTICATED`` is explicitly true. It is off
by default and never set in Helm/EKS.

Startup refuses the setting unless all of these hold, and the webhook gate re-checks the same
condition on every request, so a settings object that bypassed validation still fails closed:

* ``DEBUG`` is true;
* production is positively excluded, the same evidence the four-eyes development exception
  needs (``four_eyes_dev_policy``): a named non-production runtime profile and only loopback
  browser origins.

Only fixed values are inspected; nothing here is logged or echoed.
"""

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
    """Startup check: the exception never starts outside a debug, machine-local stack."""
    if enabled and not channel_webhook_dev_environment_permitted(debug, runtime_profile, cors_allowed_origins):
        raise SettingsFieldError(
            "channel_webhook_dev_exception_outside_development",
            "Unauthenticated channel webhooks are development-only. Unset "
            f"{SETTING_ENV_NAME}, or run with DEBUG=true, a non-production runtime_profile and "
            "only loopback cors_allowed_origins.",
            ("channel_webhook_dev_unauthenticated", "debug", "runtime_profile", "cors_allowed_origins"),
        )


def channel_webhook_dev_bypass_active(settings: object) -> bool:
    """True only when the setting is on and its environment condition still holds."""
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
