"""The internal platform gateway qualification records transport assurance and key retention, and the live gate still applies."""

from __future__ import annotations

import json
from typing import Any

from app.services.model_gateway.litellm import build_gateway_config
from app.services.model_gateway.litellm.client import LiteLLMGatewayHttpClient
from app.services.model_gateway.litellm.content_logging import VERIFIED_AGAINST_LIVE
from app.services.model_gateway.litellm.evidence_writer import write_qualification_evidence
from app.services.model_gateway.litellm.qualification import run_alias_qualification
from app.services.model_gateway.litellm.qualification_codes import (
    CHECK_CONTENT_LOGGING_POSTURE,
    CHECK_NETWORK_PATH_CONTRACT,
    EVIDENCE_ORIGIN_EXTERNAL_LIVE,
    EVIDENCE_ORIGIN_LOCAL_FIXTURE,
    LIVE_EVIDENCE_CONFIRMED,
    REASON_ORIGIN_NOT_EXTERNAL_LIVE,
    REASON_PLAINTEXT_TRANSPORT_NOT_SHARED,
    REASON_POSTURE_NOT_LIVE_VERIFIED,
    REQUIRED_CHECK_CODES,
    REQUIRED_FAIL_CLOSED_CODES,
    TRANSPORT_ASSURANCE_ATTESTED_NODE_ENCRYPTION,
    TRANSPORT_ASSURANCE_LOOPBACK_PLAINTEXT,
    TRANSPORT_ASSURANCE_VERIFIED_TLS,
)
from app.services.model_gateway.litellm.qualification_report import QualificationCheck, build_qualification_report
from tests.model_gateway.conftest import BASE_URL, VIRTUAL_KEY
from tests.model_gateway.litellm_qualification_support import (
    PLATFORM_GATEWAY_POSTURE,
    ScriptedGateway,
    qualification_section,
)

# For non-prod, Octryx uses the data platform's
# shared LiteLLM over plain http inside the cluster (Cilium WireGuard node
# encryption, Cilium policy admitting only the Octryx api), and that gateway keeps
# the key's identity in its own spend logs.

PLATFORM_HOST = "litellm.gateway.svc.cluster.local"


PLATFORM_URL = f"http://{PLATFORM_HOST}:4000"


PLATFORM_TLS = {
    "mode": "plaintext_cluster_internal",
    "node_encryption": "wireguard",
    "attested_on": "2026-11-06",
    "attestation_reference": "cluster-attestation-2026-11-06",
}


def platform_section(*, live_posture: bool = True) -> dict[str, Any]:
    posture = dict(PLATFORM_GATEWAY_POSTURE)
    if live_posture:
        posture["verified_against"] = VERIFIED_AGAINST_LIVE
    return qualification_section(host_allowlist=[PLATFORM_HOST], tls=dict(PLATFORM_TLS), content_logging=posture)


def platform_config(**kwargs: Any):
    return build_gateway_config(
        endpoint_url=PLATFORM_URL,
        virtual_key=VIRTUAL_KEY,
        config_json={"litellm_gateway": platform_section(**kwargs)},
    )


def all_required_checks_passed() -> list[QualificationCheck]:
    return [QualificationCheck(code, "passed") for code in (*REQUIRED_CHECK_CODES, *REQUIRED_FAIL_CLOSED_CODES)]


async def test_the_platform_gateway_qualification_records_transport_and_key_retention() -> None:
    gateway = ScriptedGateway()
    config = platform_config()
    client = LiteLLMGatewayHttpClient(config, transport=gateway.transport())
    try:
        checks = {check.code: check for check in await run_alias_qualification(client=client, config=config)}
    finally:
        await client.aclose()

    posture = checks[CHECK_CONTENT_LOGGING_POSTURE]
    assert posture.passed is True
    assert posture.to_evidence()["detail"]["key_metadata_retention"] == "retained_by_internal_platform_gateway"
    network = checks[CHECK_NETWORK_PATH_CONTRACT].to_evidence()["detail"]
    assert network["tls_mode"] == "plaintext_cluster_internal"
    assert network["node_encryption"] == "wireguard"
    assert network["transport_assurance"] == TRANSPORT_ASSURANCE_ATTESTED_NODE_ENCRYPTION
    assert network["proxy_mode"] == "direct"
    assert all(check.passed for check in checks.values())
    assert {request[1] for request in gateway.requests} == {"/models", "/chat/completions"}


async def test_an_attested_cluster_internal_transport_does_not_hold_the_live_gate_open() -> None:
    report = build_qualification_report(
        config=platform_config(),
        evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE,
        checks=all_required_checks_passed(),
    )

    assert report.live_evidence_blocking_reason == ""
    assert report.live_evidence_state == LIVE_EVIDENCE_CONFIRMED
    assert report.gate_satisfied is True
    assert report.transport_assurance == TRANSPORT_ASSURANCE_ATTESTED_NODE_ENCRYPTION
    evidence = report.to_evidence()
    assert evidence["transport_assurance"] == "operator_attested_node_encryption"
    gateway = evidence["gateway"]
    assert gateway["tls_mode"] == "plaintext_cluster_internal"
    assert gateway["tls_node_encryption"] == "wireguard"
    assert gateway["tls_attestation_reference"] == "cluster-attestation-2026-11-06"
    assert gateway["tls_attested_on"] == "2026-11-06"
    assert gateway["tls_ca_bundle_certificate_count"] == 0
    assert gateway["endpoint_scheme"] == "http"
    assert gateway["endpoint_cluster_internal"] is True
    assert gateway["endpoint_loopback"] is False
    assert gateway["content_logging_key_metadata_retention"] == "retained_by_internal_platform_gateway"


async def test_the_other_live_gate_conditions_still_apply_to_the_platform_gateway() -> None:
    declared = build_qualification_report(
        config=platform_config(live_posture=False),
        evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE,
        checks=all_required_checks_passed(),
    )
    assert declared.live_evidence_blocking_reason == REASON_POSTURE_NOT_LIVE_VERIFIED
    assert declared.gate_satisfied is False

    local = build_qualification_report(
        config=platform_config(),
        evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE,
        checks=all_required_checks_passed(),
    )
    assert local.live_evidence_blocking_reason == REASON_ORIGIN_NOT_EXTERNAL_LIVE
    assert local.gate_satisfied is False


async def test_the_transport_assurance_names_what_protects_the_key_for_every_mode() -> None:
    tls_report = build_qualification_report(
        config=build_gateway_config(
            endpoint_url=BASE_URL,
            virtual_key=VIRTUAL_KEY,
            config_json={"litellm_gateway": qualification_section()},
        ),
        evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE,
        checks=all_required_checks_passed(),
    )
    assert tls_report.transport_assurance == TRANSPORT_ASSURANCE_VERIFIED_TLS

    loopback_report = build_qualification_report(
        config=build_gateway_config(
            endpoint_url="http://127.0.0.1:4000/v1",
            virtual_key=VIRTUAL_KEY,
            config_json={
                "litellm_gateway": qualification_section(
                    host_allowlist=["127.0.0.1"], tls={"mode": "plaintext_loopback"}
                )
            },
        ),
        evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE,
        checks=all_required_checks_passed(),
    )
    assert loopback_report.transport_assurance == TRANSPORT_ASSURANCE_LOOPBACK_PLAINTEXT
    # Loopback plaintext still holds the gate open.
    assert loopback_report.live_evidence_blocking_reason == REASON_PLAINTEXT_TRANSPORT_NOT_SHARED


async def test_the_platform_gateway_report_writes_closed_evidence(tmp_path) -> None:
    report = build_qualification_report(
        config=platform_config(),
        evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE,
        checks=all_required_checks_passed(),
    )

    target = write_qualification_evidence(report, repo_root=tmp_path, slug="litellm-cluster", filename="platform")

    raw = target.read_text()
    for forbidden in (VIRTUAL_KEY, "Bearer", "://"):
        assert forbidden not in raw
    payload = json.loads(raw)
    assert payload["transport_assurance"] == "operator_attested_node_encryption"
    assert payload["gateway"]["endpoint_host"] == PLATFORM_HOST
    assert payload["gateway"]["tls_node_encryption"] == "wireguard"
    assert payload["gateway"]["content_logging_key_metadata_retention"] == "retained_by_internal_platform_gateway"
