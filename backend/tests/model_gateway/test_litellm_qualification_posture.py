"""The content-logging and callback posture is admitted only when neither prompts nor credentials can be retained."""

from __future__ import annotations

from typing import Any

from app.services.model_gateway.litellm.alias_catalog import config_contains_credential_material
from app.services.model_gateway.litellm.content_logging import (
    CONTENT_LOGGING_DENIAL_ATTESTATION_MISSING,
    CONTENT_LOGGING_DENIAL_ATTESTED_ON_INVALID,
    CONTENT_LOGGING_DENIAL_CALLBACK_MAY_RETAIN,
    CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED,
    CONTENT_LOGGING_DENIAL_CONTRACT_MISSING,
    CONTENT_LOGGING_DENIAL_HEADER_RETENTION,
    CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION,
    CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION_REQUIRES_NO_CALLBACKS,
    CONTENT_LOGGING_DENIAL_MODE_NOT_ADMITTED,
    CONTENT_LOGGING_DENIAL_PROMPT_RETENTION,
    CONTENT_LOGGING_DENIAL_RESPONSE_RETENTION,
    CONTENT_LOGGING_DENIAL_VERIFICATION_UNKNOWN,
    VERIFIED_AGAINST_LIVE,
    resolve_content_logging_posture,
)
from app.services.redaction_policy import is_sensitive_key
from tests.model_gateway.conftest import CONTENT_LOGGING_POSTURE, gateway_section
from tests.model_gateway.litellm_qualification_support import PLATFORM_GATEWAY_POSTURE

# --- Content-logging posture -------------------------------------------------


def test_the_admitted_posture_records_how_it_was_verified() -> None:
    declared, denial = resolve_content_logging_posture(gateway_section())

    assert denial == ""
    assert declared is not None
    assert declared.live_confirmed is False

    live_section = gateway_section(
        content_logging={**CONTENT_LOGGING_POSTURE, "verified_against": VERIFIED_AGAINST_LIVE}
    )
    live, _ = resolve_content_logging_posture(live_section)

    assert live.live_confirmed is True
    assert live.evidence()["content_logging_verified_against"] == VERIFIED_AGAINST_LIVE


def test_a_posture_that_could_retain_prompts_or_credentials_is_refused() -> None:
    cases: list[tuple[Any, str]] = [
        (None, CONTENT_LOGGING_DENIAL_CONTRACT_MISSING),
        ({}, CONTENT_LOGGING_DENIAL_MODE_NOT_ADMITTED),
        ({**CONTENT_LOGGING_POSTURE, "mode": "content_logged"}, CONTENT_LOGGING_DENIAL_MODE_NOT_ADMITTED),
        ({**CONTENT_LOGGING_POSTURE, "prompt_retention": "30d"}, CONTENT_LOGGING_DENIAL_PROMPT_RETENTION),
        ({**CONTENT_LOGGING_POSTURE, "response_retention": "enabled"}, CONTENT_LOGGING_DENIAL_RESPONSE_RETENTION),
        # The credential surfaces. A posture that retains no prompt but stores the
        # bearer token, or the key's identity in spend and audit records, has not
        # protected the credential boundary.
        (
            {**CONTENT_LOGGING_POSTURE, "header_retention": "enabled"},
            CONTENT_LOGGING_DENIAL_HEADER_RETENTION,
        ),
        (
            {key: value for key, value in CONTENT_LOGGING_POSTURE.items() if key != "header_retention"},
            CONTENT_LOGGING_DENIAL_HEADER_RETENTION,
        ),
        (
            {**CONTENT_LOGGING_POSTURE, "key_metadata_retention": "spend_logs"},
            CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION,
        ),
        (
            {key: value for key, value in CONTENT_LOGGING_POSTURE.items() if key != "key_metadata_retention"},
            CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION,
        ),
        ({**CONTENT_LOGGING_POSTURE, "success_callbacks": None}, CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED),
        ({**CONTENT_LOGGING_POSTURE, "success_callbacks": "langfuse"}, CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED),
        ({**CONTENT_LOGGING_POSTURE, "success_callbacks": ["langfuse"]}, CONTENT_LOGGING_DENIAL_CALLBACK_MAY_RETAIN),
        ({**CONTENT_LOGGING_POSTURE, "failure_callbacks": ["s3"]}, CONTENT_LOGGING_DENIAL_CALLBACK_MAY_RETAIN),
        ({**CONTENT_LOGGING_POSTURE, "attestation_reference": ""}, CONTENT_LOGGING_DENIAL_ATTESTATION_MISSING),
        ({**CONTENT_LOGGING_POSTURE, "attested_on": "soon"}, CONTENT_LOGGING_DENIAL_ATTESTED_ON_INVALID),
        ({**CONTENT_LOGGING_POSTURE, "verified_against": "trust_me"}, CONTENT_LOGGING_DENIAL_VERIFICATION_UNKNOWN),
    ]

    observed = []
    for posture, _expected in cases:
        section = gateway_section()
        if posture is None:
            section.pop("content_logging")
        else:
            section["content_logging"] = posture
        resolved, denial = resolve_content_logging_posture(section)
        assert resolved is None
        observed.append((posture, denial))

    assert observed == cases


def test_a_content_free_callback_is_admitted() -> None:
    section = gateway_section(content_logging={**CONTENT_LOGGING_POSTURE, "success_callbacks": ["prometheus"]})

    posture, denial = resolve_content_logging_posture(section)

    assert denial == ""
    assert posture.success_callbacks == ("prometheus",)


def test_key_identity_in_an_internal_platform_gateway_spend_log_is_admitted_and_named() -> None:
    posture, denial = resolve_content_logging_posture(gateway_section(content_logging=dict(PLATFORM_GATEWAY_POSTURE)))

    assert denial == ""
    assert posture.key_metadata_retention == "retained_by_internal_platform_gateway"
    assert posture.key_metadata_retained is True
    evidence = posture.evidence()
    # Recorded verbatim, so no reader mistakes it for ``disabled``.
    assert evidence["content_logging_key_metadata_retention"] == "retained_by_internal_platform_gateway"
    assert evidence["content_logging_prompt_retention"] == "disabled"
    assert evidence["content_logging_response_retention"] == "disabled"
    assert evidence["content_logging_header_retention"] == "disabled"
    assert evidence["content_logging_callbacks"] == []
    # The value itself must not trip the credential-key scan of the section.
    assert config_contains_credential_material(gateway_section(content_logging=dict(PLATFORM_GATEWAY_POSTURE))) is False

    # ``disabled`` keeps its meaning.
    plain, _ = resolve_content_logging_posture(gateway_section())
    assert plain.key_metadata_retained is False


def test_key_identity_retention_admits_nothing_else() -> None:
    """Prompts, responses, headers and every callback stay forbidden with it."""

    cases: list[tuple[dict[str, Any], str]] = [
        ({**PLATFORM_GATEWAY_POSTURE, "success_callbacks": ["prometheus"]},
         CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION_REQUIRES_NO_CALLBACKS),
        ({**PLATFORM_GATEWAY_POSTURE, "failure_callbacks": ["prometheus"]},
         CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION_REQUIRES_NO_CALLBACKS),
        ({**PLATFORM_GATEWAY_POSTURE, "success_callbacks": ["langfuse"]}, CONTENT_LOGGING_DENIAL_CALLBACK_MAY_RETAIN),
        ({**PLATFORM_GATEWAY_POSTURE, "failure_callbacks": None}, CONTENT_LOGGING_DENIAL_CALLBACKS_MALFORMED),
        ({**PLATFORM_GATEWAY_POSTURE, "prompt_retention": "enabled"}, CONTENT_LOGGING_DENIAL_PROMPT_RETENTION),
        ({**PLATFORM_GATEWAY_POSTURE, "prompt_retention": "retained_by_internal_platform_gateway"},
         CONTENT_LOGGING_DENIAL_PROMPT_RETENTION),
        ({**PLATFORM_GATEWAY_POSTURE, "response_retention": "retained_by_internal_platform_gateway"},
         CONTENT_LOGGING_DENIAL_RESPONSE_RETENTION),
        ({**PLATFORM_GATEWAY_POSTURE, "header_retention": "retained_by_internal_platform_gateway"},
         CONTENT_LOGGING_DENIAL_HEADER_RETENTION),
        ({**PLATFORM_GATEWAY_POSTURE, "header_retention": "enabled"}, CONTENT_LOGGING_DENIAL_HEADER_RETENTION),
        ({**PLATFORM_GATEWAY_POSTURE, "mode": "content_logged"}, CONTENT_LOGGING_DENIAL_MODE_NOT_ADMITTED),
        ({**PLATFORM_GATEWAY_POSTURE, "attestation_reference": ""}, CONTENT_LOGGING_DENIAL_ATTESTATION_MISSING),
        ({**PLATFORM_GATEWAY_POSTURE, "attested_on": "today"}, CONTENT_LOGGING_DENIAL_ATTESTED_ON_INVALID),
        # Only the one named value; nothing that sounds like it.
        ({**PLATFORM_GATEWAY_POSTURE, "key_metadata_retention": "retained_by_external_saas_gateway"},
         CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION),
        ({**PLATFORM_GATEWAY_POSTURE, "key_metadata_retention": "retained"},
         CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION),
        ({**PLATFORM_GATEWAY_POSTURE, "key_metadata_retention": "spend_logs"},
         CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION),
    ]

    observed = []
    for posture, _expected in cases:
        resolved, denial = resolve_content_logging_posture(gateway_section(content_logging=posture))
        assert resolved is None
        observed.append((posture, denial))

    assert observed == cases


def test_the_admitted_posture_records_every_retention_surface() -> None:
    posture, denial = resolve_content_logging_posture(gateway_section())

    assert denial == ""
    evidence = posture.evidence()
    assert evidence["content_logging_prompt_retention"] == "disabled"
    assert evidence["content_logging_response_retention"] == "disabled"
    assert evidence["content_logging_header_retention"] == "disabled"
    assert evidence["content_logging_key_metadata_retention"] == "disabled"


def test_no_posture_field_name_looks_like_credential_material() -> None:
    """The posture must not make a correct config look like it embeds a key.

    The gateway section is scanned for credential-looking keys at admission and at
    readiness, and that scan is deliberately broad — it matches ``credential``,
    ``token`` and ``virtual_key`` as substrings. A retention field named after one
    of them would deny every correctly configured provider, so the names are part
    of the contract and are pinned here.
    """

    section = gateway_section()
    assert config_contains_credential_material(section) is False
    for key in CONTENT_LOGGING_POSTURE:
        assert is_sensitive_key(key) is False, key
    posture, _denial = resolve_content_logging_posture(section)
    for key in posture.evidence():
        assert is_sensitive_key(key) is False, key
