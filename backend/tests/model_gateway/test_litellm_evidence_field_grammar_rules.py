"""The closed value grammars themselves: identifier and per-key grammars admit real naming and refuse real tokens, request paths stay bounded, and only operator-supplied fields carry a grammar."""

from __future__ import annotations

import importlib
import pkgutil

import app.services.model_gateway.litellm as litellm_package
from app.services.model_gateway.litellm.evidence_value_shape import (
    MAX_IDENTIFIER_LENGTH,
    has_declared_grammar,
    is_admissible_evidence_value,
    is_identifier_shaped,
    is_request_path_shaped,
)
from app.services.redaction_policy import looks_like_secret_value
from tests.model_gateway.litellm_evidence_field_grammar_support import (
    AUTH_HEADER,
    CREDENTIAL_URL,
    FREE_TEXT,
    GITHUB_TOKEN,
    GITLAB_TOKEN,
    PEM_BLOCK,
    REAL_KEY,
    SECRET_ASSIGNMENT,
    SLACK_TOKEN,
    TARGET_ALIAS,
    TARGET_ATTESTATION_REFERENCE,
    TARGET_COST_REFERENCE,
    TARGET_IDENTIFIERS,
    TARGET_MODEL_GROUP,
)


def test_the_identifier_grammar_admits_real_naming_and_refuses_real_tokens() -> None:
    """The grammar pinned directly, on both sides."""

    for admitted in (
        *TARGET_IDENTIFIERS,
        "octryx-general",
        "general-group",
        "cost-contract-2026-09",
        "azure/gpt-4o",
        "bedrock-converse-eu-anthropic-claude-3-7-sonnet-20250219-v1-0",
        "2026-09-27",
        "prometheus",
        "internal",
        "d0390ac57ade4f1e9b2c8d7a6f5e4d3c2b1a09876543210fedcba9876543210f",
    ):
        assert is_identifier_shaped(admitted) is True, admitted

    for refused in (
        # A credential prefix at the start of the value or after a separator.
        REAL_KEY,
        GITLAB_TOKEN,
        SLACK_TOKEN,
        GITHUB_TOKEN,
        "gho_AbCdEfGhIjKlMnOpQrSt",
        "github_pat_AbCdEfGhIjKlMnOpQrSt",
        ("pricing-sk-li" + "ve-4eC39HqLyjWDarjtT1zdp7dc"),
        ("pricing/sk-li" + "ve-4eC39HqLyjWDarjtT1zdp7dc"),
        ("xsk-li" + "ve-4eC39HqLyjWDarjtT1zdp7dc"),
        ("xdesk-li" + "ve-4eC39HqLyjWDarjtT1zdp7dc"),
        ("desk-sk-li" + "ve-4eC39HqLyjWDarjtT1zdp7dc"),
        ("task-sk-li" + "ve-4eC39HqLyjWDarjtT1zdp7dc"),
        # A named secret marker.
        "aws_secret_access_key",
        # Characters the grammar excludes, which is what keeps every remaining
        # redaction rule structurally unable to match an admitted value.
        AUTH_HEADER,
        CREDENTIAL_URL,
        SECRET_ASSIGNMENT,
        PEM_BLOCK,
        FREE_TEXT,
        "group:with:colons",
        "group with spaces",
        "-leading-separator",
        "trailing-separator-",
        "x" * (MAX_IDENTIFIER_LENGTH + 1),
        "",
        None,
        42,
    ):
        assert is_identifier_shaped(refused) is False, refused


def test_each_identifier_evidence_key_has_its_own_closed_value_grammar() -> None:
    """A field name never grants a generic identifier-shaped exemption."""

    digest = "d0390ac57ade4f1e9b2c8d7a6f5e4d3c2b1a09876543210fedcba9876543210f"
    assertions = (
        ("alias", TARGET_ALIAS, True),
        ("model_group", TARGET_MODEL_GROUP, True),
        ("cost_contract_reference", TARGET_COST_REFERENCE, True),
        ("content_logging_attestation_reference", TARGET_ATTESTATION_REFERENCE, True),
        ("data_policy_class", "internal", True),
        ("data_policy_class", "desk-internal", False),
        ("content_logging_callbacks", "prometheus", True),
        ("content_logging_callbacks", "desk-exporter", False),
        ("content_logging_attested_on", "2026-09-27", True),
        ("content_logging_attested_on", "2026-02-30", False),
        ("content_logging_attested_on", TARGET_ALIAS, False),
        ("tls_ca_bundle_sha256", digest, True),
        ("tls_ca_bundle_sha256", TARGET_COST_REFERENCE, False),
        ("tls_attestation_reference", "cluster-attestation-2026-11-06", True),
        ("tls_attestation_reference", "see the wiki", False),
        ("tls_attested_on", "2026-11-06", True),
        ("tls_attested_on", "2026-02-30", False),
        ("tls_attested_on", TARGET_ALIAS, False),
    )
    for key, value, admitted in assertions:
        assert is_admissible_evidence_value(key, value) is admitted, (key, value)


def test_the_request_path_grammar_admits_only_bounded_absolute_paths() -> None:
    for admitted in ("/v1", "/models", "/model/info", "/v1/chat/completions", "/desk-audit/v1/models"):
        assert is_request_path_shaped(admitted) is True, admitted

    for refused in (
        "v1/models",
        "/v1//models",
        ("/v1/sk-li" + "ve-4eC39HqLyjWDarjtT1zdp7dc"),
        CREDENTIAL_URL,
        "/v1/models?tenant=alpha",
        "/v1/models /etc/passwd",
        "",
    ):
        assert is_request_path_shaped(refused) is False, refused


def test_only_operator_supplied_fields_have_a_grammar() -> None:
    """The exemption stays where the defect is: no backend code inherits one."""

    for operator_field in (
        "alias",
        "model_group",
        "cost_contract_reference",
        "content_logging_attestation_reference",
        "endpoint_host",
        "proxy_host",
        "network_path_hops",
        "probe_models_path",
    ):
        assert has_declared_grammar(operator_field) is True, operator_field

    for backend_code_field in (
        "gateway",
        "gateway_state",
        "denial_reason",
        "cost_source",
        "tls_mode",
        "tls_node_encryption",
        "proxy_mode",
        "proxy_tls_trust_source",
        "content_logging_mode",
        "content_logging_verified_against",
        "network_path_direction",
        "check",
        "status",
    ):
        assert has_declared_grammar(backend_code_field) is False, backend_code_field


def test_no_backend_owned_gateway_code_is_itself_secret_shaped() -> None:
    """The backend's closed codes keep the generic scan, so none may trip it.

    This is what makes "only operator-supplied fields get a grammar" safe: if a
    future denial code, mode or reason ever contained a credential-prefix
    substring, it would be refused at write time — so it fails here instead,
    where it is one rename away from being fixed.
    """

    checked = 0
    for module_info in pkgutil.iter_modules(litellm_package.__path__):
        module = importlib.import_module(f"{litellm_package.__name__}.{module_info.name}")
        for name, value in vars(module).items():
            if not name.isupper() or not isinstance(value, str) or not value:
                continue
            checked += 1
            assert looks_like_secret_value(value) is False, f"{module_info.name}.{name}"
    assert checked > 100, "constant scrape looks broken"
