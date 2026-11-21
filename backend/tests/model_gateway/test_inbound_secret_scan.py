"""Contract: the gateway refuses credential material, not source code that names secrets."""

import pytest

from app.services.model_gateway.inbound.secret_scan import secret_kinds

# Built from parts so this file is not itself a scanner hit.
_AWS_ID = "AKIA" + "IOSFODNN7EXAMPLE"
_GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
_JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"my key is {_AWS_ID}", "aws_access_key_id"),
        (f"export GITHUB_TOKEN={_GITHUB}", "vendor_token"),
        (f"curl -H 'x: {_JWT}'", "jwt"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIE", "private_key"),
        ("https://deploy:hunter2secret@git.example.com/repo.git", "credential_url"),
        ("aws_secret_access_key = " + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "aws_secret_access_key"),
    ],
)
def test_credential_material_is_detected(text, kind):
    assert kind in secret_kinds(text)


@pytest.mark.parametrize(
    "text",
    [
        "password = settings.db_password",
        "token: str = request.headers['authorization']",
        'headers = {"Authorization": f"Bearer {token}"}',
        "DATABASE_URL: postgresql://octryx:${OCTRYX_POSTGRES_PASSWORD:?required}@postgres:5432/db",
        "risk-based task-list for scikit-learn",
        "secret_ref = provider.api_key_secret_ref",
    ],
)
def test_source_code_naming_secrets_passes(text):
    assert secret_kinds(text) == ()
