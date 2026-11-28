"""Synthetic origins, the panel path and the policy settings shared by the panel cookie mutation guard tests."""

from __future__ import annotations

from tests.support.trusted_proxy_test_utils import settings

APP_HOST = "octryx.example"
APP_ORIGIN = f"http://{APP_HOST}"
FOREIGN_ORIGIN = "https://attacker.example"
PANEL_PATH = "/admin/chat/api/panel/feature-flags"

# One allowed origin other than the request's own keeps "same origin" and "explicitly allowed" distinguishable.
ALLOWLIST_ORIGIN = "https://admin.octryx.example"
POLICY_SETTINGS = settings(cors_allowed_origins=ALLOWLIST_ORIGIN)
