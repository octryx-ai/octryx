"""Free-text MCP metadata is held to the same credential rule as a URI: real credential shapes and short secret assignments are refused, ordinary business wording and closed documentation statuses are not."""

from __future__ import annotations

import pytest

from app.services.mcp_resource_credentials import (
    CREDENTIAL_FINDING_QUERY,
    CREDENTIAL_FINDING_SECRET_VALUE,
    CREDENTIAL_FINDING_USERINFO,
    mcp_resource_text_credential_finding,
)
from app.services.redaction_policy import redact_secret_text
from tests.mcp_resource_support import POSTGRES_URI, PRESIGNED_URI, SECRET_URI

# Ordinary enterprise wording a remote server really does put in a name or a
# description. Every one of these looked like a credential to one loose rule —
# ``sk-``/``basic `` as substrings ("risk"/"task"/"desk", a sentence starting
# "Basic"), a case-insensitive ``akia``/``asia`` prefix with no delimiter (regions,
# product lines, a reviewer's name), or a secret label with any eight-character
# value — and none of them carries a credential. Refusing them would withhold a
# governed item and (before the lifecycle rule) retire an already-approved binding.
ORDINARY_METADATA = (
    "Quarterly risk-report for the desk-review board",
    # ``akia``/``asia`` folded into the case-insensitive prefix rule: these are
    # regions, product lines and reviewer names, and every one of them was a
    # credential finding.
    "asia-pacific",
    "Asia-Pacific",
    "asia_pacific",
    "asiapacificoperations",
    "akianakamura",
    "asia-pacific-operations",
    "asia_pacific_summary",
    "akianakamura-reports",
    "Asia-Pacific regional risk-report for the desk-review board",
    "ASIA and EMEA rollup, prepared by Akia Nakamura",
    # A secret *name* used as an ordinary field label. The label proves nothing;
    # these closed documentation statuses are explicitly non-secret values.
    "Password: Required",
    "Password: Required for download",
    "Authorization: Approved by the board",
    "Token: unlimited",
    "secret: undisclosed",
    "password: unspecified",
    "api_key: unavailable",
    "Client secret: undisclosed by the vendor",
    "Access token: inherited from the workspace binding",
    "risk-report",
    "task-summary",
    "desk-review",
    "Basic reporting guidance for the risk desk",
    "Basic internationalization notes for the task board",
    "Risk-Management-Report 2026, basic figures only",
    "Troubleshooting-Documentation for the task-summary pipeline",
    "A basic overview of risk-adjusted returns",
    "text/markdown",
    "application/vnd.octryx.risk-report+json",
)


# The shapes that really do carry a credential, each in a *free-text* field.
CREDENTIAL_METADATA = (
    ("Mirror of postgres://admin:s3cr3t-token@db.internal/reports", CREDENTIAL_FINDING_USERINFO),
    ("Served from https://svc:pw@internal.example/r.json", CREDENTIAL_FINDING_USERINFO),
    (
        "Download via https://b.s3.eu-central-1.amazonaws.com/r.json?X-Amz-Signature=abc&X-Amz-Expires=60",
        CREDENTIAL_FINDING_QUERY,
    ),
    ("Fetch https://api.example/report?access_token=abcdefghij", CREDENTIAL_FINDING_QUERY),
    ("Authorization: Bearer s3cr3t-token-value", CREDENTIAL_FINDING_SECRET_VALUE),
    ("Basic YWxhZGRpbjpvcGVuc2VzYW1l", CREDENTIAL_FINDING_SECRET_VALUE),
    (("Call it with sk-proj-AbCd" + "Ef0123456789xyz"), CREDENTIAL_FINDING_SECRET_VALUE),
    (("configure api_key=AbCd" + "Ef0123456789xyz first"), CREDENTIAL_FINDING_SECRET_VALUE),
    (("token: 8f3a" + "9c21bd77ee01"), CREDENTIAL_FINDING_SECRET_VALUE),
    ("AKIAIOSFODNN7EXAMPLE is the access key", CREDENTIAL_FINDING_SECRET_VALUE),
    (("ASIA" + "Y34FZKBOKMUTVV7A rotates hourly"), CREDENTIAL_FINDING_SECRET_VALUE),
    (("password: 'Xk9m" + "Q2vT7pL4zR8w'"), CREDENTIAL_FINDING_SECRET_VALUE),
    ("aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", CREDENTIAL_FINDING_SECRET_VALUE),
    (("client_secret: 4f8a" + "2b91c0de7356aa12"), CREDENTIAL_FINDING_SECRET_VALUE),
    ("Authorization: dG9rZW46c3VwZXItc2VjcmV0LXZhbHVl", CREDENTIAL_FINDING_SECRET_VALUE),
    ("-----BEGIN RSA PRIVATE KEY-----", CREDENTIAL_FINDING_SECRET_VALUE),
)


SECRET_ASSIGNMENT_LABELS = (
    "api_key",
    "api-key",
    "api key",
    "apikey",
    "access_key",
    "access-key",
    "access key",
    "accesskey",
    "access_token",
    "access-token",
    "access token",
    "accesstoken",
    "refresh_token",
    "refresh-token",
    "refresh token",
    "refreshtoken",
    "id_token",
    "id-token",
    "id token",
    "idtoken",
    "session_token",
    "session-token",
    "session token",
    "sessiontoken",
    "client_secret",
    "client-secret",
    "client secret",
    "clientsecret",
    "secret_key",
    "secret-key",
    "secret key",
    "secretkey",
    "private_key",
    "private-key",
    "private key",
    "privatekey",
    "aws_secret_access_key",
    "aws-secret-access-key",
    "aws secret access key",
    "awssecretaccesskey",
    "authorization",
    "password",
    "passwd",
    "token",
    "secret",
)


@pytest.mark.parametrize(
    ("text", "finding"),
    [
        (f"Mirror of {POSTGRES_URI}", CREDENTIAL_FINDING_USERINFO),
        (f"Download via {PRESIGNED_URI}", CREDENTIAL_FINDING_QUERY),
        (f"Call it with {SECRET_URI}", CREDENTIAL_FINDING_USERINFO),
        ("Authorization: Bearer s3cr3t-token-value", CREDENTIAL_FINDING_SECRET_VALUE),
        ("The quarterly React documentation, in markdown.", ""),
        ("text/markdown", ""),
        ("", ""),
    ],
)
def test_free_text_metadata_is_held_to_the_same_credential_rule_as_a_uri(text, finding) -> None:
    """A description is provider-controlled too, and the generic redactor misses it.

    ``redact_secret_text`` rewrites URI userinfo but not a presign query, so every
    shape has to be recognised anywhere inside a field rather than only at the
    start of a parsed URI.
    """
    assert mcp_resource_text_credential_finding(text) == finding


def test_the_generic_redactor_alone_would_have_published_these() -> None:
    """Why the rule above has to exist: a presign query survives ``redact_secret_text``.

    Userinfo of any scheme (``postgres://user:pw@``) is rewritten by the shared policy;
    the structural rule still finds it, so the item is refused either way.
    """
    presigned = f"Download via {PRESIGNED_URI}"
    assert "s3cr3t-token" in redact_secret_text(presigned)
    assert mcp_resource_text_credential_finding(presigned) != ""
    postgres = f"Mirror of {POSTGRES_URI}"
    assert "s3cr3t-token" not in redact_secret_text(postgres)
    assert mcp_resource_text_credential_finding(postgres) == CREDENTIAL_FINDING_USERINFO


@pytest.mark.parametrize("text", ORDINARY_METADATA)
def test_ordinary_business_wording_is_not_a_credential(text) -> None:
    """Each rule is anchored, exact, or value-gated, so ordinary wording passes.

    Three loose shapes each rejected a family of real enterprise vocabulary:
    ``sk-``/``basic `` tested as substrings ("risk-report", "desk-review", "Basic
    reporting guidance"); a case-insensitive delimiter-free ``akia``/``asia``
    prefix ("asia-pacific-operations", "akianakamura-reports"); and a secret label
    followed by any eight non-space characters ("Password: Required",
    "Token: unlimited"). Only a key prefix that starts a token, the exact AWS
    access-key shape, an auth scheme *or* secret name followed by credential
    material, a non-status secret assignment, a private-key block, or an embedded
    URI that parses as credential-bearing is a finding.
    """
    assert mcp_resource_text_credential_finding(text) == ""


def test_an_aws_access_key_identifier_is_matched_by_its_exact_shape() -> None:
    """``AKIA``/``ASIA`` plus sixteen uppercase alphanumerics, and nothing else.

    AWS issues exactly that shape, so the rule needs neither case folding nor a
    ``{12,}`` tail — both of which is what made "asia_pacific_summary" a finding.
    A lowercase or wrong-length lookalike is wording; the real shape is refused
    wherever it sits in a sentence.
    """
    key = "AKIA" + "IOSFODNN7EXAMPLE"
    for wording in (key.lower(), key[:-1], f"{key}X", f"{key}0123", "AKIA-IOSFODNN7EXAMPLE"):
        assert mcp_resource_text_credential_finding(wording) == "", wording
    for carrier in (key, f"rotate {key} before Friday", f"({key})", f"{key},{key}"):
        assert mcp_resource_text_credential_finding(carrier) == CREDENTIAL_FINDING_SECRET_VALUE, carrier


@pytest.mark.parametrize(
    "text",
    (
        "Password: Required for download",
        "Authorization: Approved by the board",
        "Token: unlimited",
        "secret: undisclosed",
        "password: unspecified",
        "api_key: unavailable",
        "Client secret: undisclosed by the vendor",
        "Access token: inherited from the workspace binding",
        "private_key: managed externally",
        "refresh_token: not configured",
        "session_token: provided-on-request",
    ),
)
def test_a_secret_label_accepts_only_closed_documentation_statuses(text) -> None:
    """A field label is harmless only with an explicitly recognised status."""
    assert mcp_resource_text_credential_finding(text) == ""


@pytest.mark.parametrize(
    "text",
    (
        "Password: Required for download",
        "Token: unlimited",
        "secret: undisclosed",
        "api_key: unavailable",
    ),
)
def test_a_redacted_documentation_status_remains_non_secret_on_policy_recheck(text) -> None:
    """The mirror's persisted projection must not deny an accepted status later."""
    projected = redact_secret_text(text)
    assert "[redacted]" in projected
    assert mcp_resource_text_credential_finding(projected) == ""


@pytest.mark.parametrize("label", SECRET_ASSIGNMENT_LABELS)
def test_every_secret_assignment_alias_fails_closed_for_a_short_real_value(label) -> None:
    """Explicit secret assignment is stronger evidence than bearer/basic prose."""
    assert mcp_resource_text_credential_finding(f"{label}=Ab3dE5f7") == CREDENTIAL_FINDING_SECRET_VALUE


@pytest.mark.parametrize(
    "text",
    (
        "passwd: correcthorse",
        "password: deadbeef",
        "token: 8f3a9c21",
        "api_key: abcdefgh",
        "aws_secret_access_key: shortSecret9",
        "Authorization: Abcd1234",
    ),
)
def test_alphabetic_hex_and_mixed_secret_assignments_are_not_business_prose(text) -> None:
    assert mcp_resource_text_credential_finding(text) == CREDENTIAL_FINDING_SECRET_VALUE


@pytest.mark.parametrize(("text", "finding"), CREDENTIAL_METADATA)
def test_real_credential_shapes_in_free_text_are_still_refused(text, finding) -> None:
    assert mcp_resource_text_credential_finding(text) == finding


def test_a_hostile_field_is_inspected_within_a_bound() -> None:
    """A megabyte-long name cannot make credential inspection the expensive part.

    Everything that reaches persistence is bounded far below the scan window, so
    the bound costs nothing real — and a credential inside the window is still
    found.
    """
    padding = "risk-report task-summary desk-review " * 500

    assert mcp_resource_text_credential_finding(padding) == ""
    assert mcp_resource_text_credential_finding(
        f"postgres://admin:s3cr3t-token@db.internal/reports {padding}"
    ) == CREDENTIAL_FINDING_USERINFO
