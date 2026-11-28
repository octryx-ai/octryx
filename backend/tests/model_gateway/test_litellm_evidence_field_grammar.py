"""Closed value grammars for the identifier and reference evidence fields: deployment names such as ``task-router``
(which contain ``sk-``) are written, while real secrets under the same keys still fail closed."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from app.services.model_gateway.litellm import build_gateway_config
from app.services.model_gateway.litellm.evidence import build_call_evidence
from app.services.model_gateway.litellm.evidence_payload_check import (
    EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE,
    EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_ADMISSIBLE,
)
from app.services.model_gateway.litellm.evidence_value_shape import (
    IDENTIFIER_EVIDENCE_KEYS,
    PATH_EVIDENCE_KEYS,
    has_declared_grammar,
    is_admissible_evidence_value,
)
from app.services.model_gateway.litellm.evidence_writer import (
    EvidenceWriteDeniedError,
    write_qualification_evidence,
)
from app.services.model_gateway.litellm.qualification_codes import (
    EVIDENCE_ORIGIN_LOCAL_FIXTURE,
    REQUIRED_CHECK_CODES,
    REQUIRED_FAIL_CLOSED_CODES,
)
from app.services.model_gateway.litellm.qualification_report import QualificationCheck, build_qualification_report
from app.services.redaction_policy import looks_like_secret_value
from tests.model_gateway.conftest import VIRTUAL_KEY, gateway_section
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

TARGET_GATEWAY_HOST = "litellm.shop-nonprod.example.com"


HOSTILE_VALUES = (
    REAL_KEY,
    AUTH_HEADER,
    CREDENTIAL_URL,
    SECRET_ASSIGNMENT,
    PEM_BLOCK,
    FREE_TEXT,
    GITLAB_TOKEN,
    SLACK_TOKEN,
    GITHUB_TOKEN,
)


def target_section() -> dict[str, Any]:
    section = gateway_section(
        host_allowlist=[TARGET_GATEWAY_HOST],
        aliases={
            TARGET_ALIAS: {
                "model_group": TARGET_MODEL_GROUP,
                "context_limit": 128000,
                "data_policy_class": "internal",
                "capabilities": {"tools": True},
                "cost": {"source": "gateway_reported", "contract_reference": TARGET_COST_REFERENCE},
            }
        },
    )
    section["content_logging"]["attestation_reference"] = TARGET_ATTESTATION_REFERENCE
    return section


def target_config():
    return build_gateway_config(
        endpoint_url=f"https://{TARGET_GATEWAY_HOST}/v1",
        virtual_key=VIRTUAL_KEY,
        config_json={"litellm_gateway": target_section()},
    )


def target_report(*, with_alias_identity: bool = False):
    config = target_config()
    report = build_qualification_report(
        config=config,
        evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE,
        checks=[
            QualificationCheck(code, "passed", alias=TARGET_ALIAS)
            for code in (*REQUIRED_CHECK_CODES, *REQUIRED_FAIL_CLOSED_CODES)
        ],
    )
    if not with_alias_identity:
        return report
    call_evidence = build_call_evidence(config=config, entry=config.aliases[0])
    return dataclasses.replace(
        report, gateway_evidence={**report.gateway_evidence, **call_evidence}
    )


def test_every_refused_target_identifier_is_secret_shaped_to_the_shared_policy() -> None:
    for value in TARGET_IDENTIFIERS:
        assert looks_like_secret_value(value) is True, value


def test_the_target_identifiers_write_evidence_instead_of_being_refused(tmp_path) -> None:
    report = target_report(with_alias_identity=True)

    target = write_qualification_evidence(
        report, repo_root=tmp_path, slug="issue-825", filename="local-contract"
    )

    payload = json.loads(target.read_text())
    gateway = payload["gateway"]
    assert gateway["alias"] == TARGET_ALIAS
    assert gateway["model_group"] == TARGET_MODEL_GROUP
    assert gateway["cost_contract_reference"] == TARGET_COST_REFERENCE
    assert gateway["content_logging_attestation_reference"] == TARGET_ATTESTATION_REFERENCE
    assert {check["alias"] for check in payload["checks"]} == {TARGET_ALIAS}
    assert VIRTUAL_KEY not in target.read_text()


def test_the_product_call_evidence_of_the_target_alias_is_admissible() -> None:
    evidence = build_call_evidence(config=target_config(), entry=target_config().aliases[0])

    assert evidence["alias"] == TARGET_ALIAS
    assert evidence["model_group"] == TARGET_MODEL_GROUP
    assert evidence["cost_contract_reference"] == TARGET_COST_REFERENCE
    # Stated per key rather than only swept, so removing the grammars makes this
    # fail instead of making the loop below vacuous.
    for key in ("alias", "model_group", "cost_contract_reference"):
        assert is_admissible_evidence_value(key, evidence[key]) is True, key
    for key, value in evidence.items():
        if isinstance(value, str) and value and has_declared_grammar(key):
            assert is_admissible_evidence_value(key, value) is True, (key, value)


def test_a_hostile_value_under_every_grammar_field_fails_closed(tmp_path) -> None:
    report = target_report()
    fields = sorted(IDENTIFIER_EVIDENCE_KEYS | PATH_EVIDENCE_KEYS)
    assert len(fields) >= 11

    for key in fields:
        for value in HOSTILE_VALUES:
            poisoned = dataclasses.replace(
                report, gateway_evidence={**report.gateway_evidence, key: value}
            )
            with pytest.raises(EvidenceWriteDeniedError) as excinfo:
                write_qualification_evidence(
                    poisoned, repo_root=tmp_path, slug="issue-825", filename="denied"
                )
            assert excinfo.value.denial_reason in (
                EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE,
                EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_ADMISSIBLE,
            ), (key, value)
            assert excinfo.value.denial_field == key, (key, value)
    assert not (tmp_path / "evidence" / "issue-825" / "denied.json").exists()


def test_a_hostile_callback_name_in_a_list_field_fails_closed(tmp_path) -> None:
    report = target_report()
    poisoned = dataclasses.replace(
        report,
        gateway_evidence={**report.gateway_evidence, "content_logging_callbacks": ["prometheus", REAL_KEY]},
    )

    with pytest.raises(EvidenceWriteDeniedError) as excinfo:
        write_qualification_evidence(poisoned, repo_root=tmp_path, slug="issue-825", filename="denied")

    assert excinfo.value.denial_reason == EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE
    assert excinfo.value.denial_field == "content_logging_callbacks"
