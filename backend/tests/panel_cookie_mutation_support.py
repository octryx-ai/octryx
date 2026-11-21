"""Synthetic origins, the panel path and the policy settings shared by the panel cookie mutation guard tests."""

from __future__ import annotations

from tests.trusted_proxy_test_utils import settings

APP_HOST = "octryx.example"
APP_ORIGIN = f"http://{APP_HOST}"
FOREIGN_ORIGIN = "https://attacker.example"
PANEL_PATH = "/admin/chat/api/panel/feature-flags"

# A configured allowlist that names one origin other than the request's own, so
# "same origin" and "explicitly allowed origin" stay distinguishable.
ALLOWLIST_ORIGIN = "https://admin.octryx.example"
POLICY_SETTINGS = settings(cors_allowed_origins=ALLOWLIST_ORIGIN)
