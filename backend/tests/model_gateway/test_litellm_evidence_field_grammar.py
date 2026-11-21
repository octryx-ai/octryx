"""Closed value grammars for the identifier and reference evidence fields.

The evidence writer runs every string through the shared redaction policy, which
matches a credential prefix such as ``sk-`` as a *substring*. The identifier and
reference fields are checked against closed grammars first, so the deployment's
own naming is written instead of being refused as
``evidence_payload_sensitive_value``:

    model_group='task-router'
    model_group='desk-nova-lite'
    alias='task-router'
    cost_contract_reference='desk-pricing-2026'
    content_logging_attestation_reference=
        'litellm-posture-task-non-prod-2026-09-27'

``task-`` and ``desk-`` both contain ``sk-``, and ``model_group`` is the
*cluster's* naming, so it cannot simply be renamed.

What holds per field:

- the five values above are written, verbatim, by the product;
- a real token, an auth header, a credential-bearing URL, a secret assignment, a
  PEM block and arbitrary free text still fail closed under every one of those
  keys;
- the generic scan is unchanged for every key that has no grammar, and no
  backend-owned closed code is itself secret-shaped.
"""

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
    """A governed config whose every identifier is the target environment's."""

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
    """A complete, passing report built by the product from that config.

    ``with_alias_identity`` merges the product's own per-call evidence
    (``build_call_evidence``), which is where ``model_group``,
    ``cost_contract_reference`` and ``data_policy_class`` are produced. Both
    payloads are already closed to the shared allowlist, so the merge adds keys
    rather than widening it.
    """

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
    """Without the grammars these values are refused, so the fix is load-bearing."""

    for value in TARGET_IDENTIFIERS:
        assert looks_like_secret_value(value) is True, value


def test_the_target_identifiers_write_evidence_instead_of_being_refused(tmp_path) -> None:
    """The review's reproductions, end to end, through the product writer.

    Every value is produced by the product — the alias by the qualification
    checks, the attestation reference by the posture contract, the model group
    and the cost reference by ``build_call_evidence`` — so the test cannot pass
    with a value the product would not actually emit.
    """

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
    # The per-check alias is the same operator naming and reaches the file too.
    assert {check["alias"] for check in payload["checks"]} == {TARGET_ALIAS}
    assert VIRTUAL_KEY not in target.read_text()


def test_the_product_call_evidence_of_the_target_alias_is_admissible() -> None:
    """The producer's own payload, judged key by key by the writer's grammar."""

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
    """The grammar is a shape, not a key-name allowlist: nothing hostile passes.

    A secret-shaped value is reported as such; anything else that is not the
    promised shape — arbitrary free text included — is reported as not
    admissible. Both refuse the write, and both name the field.
    """

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
    # Nothing was written for any of them.
    assert not (tmp_path / "evidence" / "issue-825" / "denied.json").exists()


def test_a_hostile_callback_name_in_a_list_field_fails_closed(tmp_path) -> None:
    """A list-valued field judges every entry under its own key."""

    report = target_report()
    poisoned = dataclasses.replace(
        report,
        gateway_evidence={**report.gateway_evidence, "content_logging_callbacks": ["prometheus", REAL_KEY]},
    )

    with pytest.raises(EvidenceWriteDeniedError) as excinfo:
        write_qualification_evidence(poisoned, repo_root=tmp_path, slug="issue-825", filename="denied")

    assert excinfo.value.denial_reason == EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE
    assert excinfo.value.denial_field == "content_logging_callbacks"
