"""Shared leak markers and narrow texts for the connection test and admin redaction tests."""

from __future__ import annotations

import re

FAKE_TOKEN = "octryx-fake-token-9f8e7d6c5b4a"


FAKE_HOST = "internal-host.example.test"


FAKE_PATH = "/srv/octryx-internal/kubeconfig"


LEAK = f"svc-account token={FAKE_TOKEN} at https://{FAKE_HOST}:8443/rest?auth={FAKE_TOKEN} from {FAKE_PATH}"


LEAK_MARKERS = (FAKE_TOKEN, FAKE_HOST, FAKE_PATH, "svc-account")


NARROW_TEXT = re.compile(r"^[A-Za-z0-9_=.,() -]+$")
