"""The live gate closes only on live evidence with every required check run and a verified posture."""

from __future__ import annotations

from app.services.model_gateway.litellm import build_gateway_config
from app.services.model_gateway.litellm.content_logging import VERIFIED_AGAINST_LIVE
from app.services.model_gateway.litellm.qualification_codes import (
    EVIDENCE_ORIGIN_EXTERNAL_LIVE,
    EVIDENCE_ORIGIN_LOCAL_FIXTURE,
    FAIL_CLOSED_MODEL_GROUP_MISMATCH,
    LIVE_EVIDENCE_CONFIRMED,
    LIVE_EVIDENCE_PENDING_EXTERNAL_GATE,
    REASON_LOOPBACK_ENDPOINT_NOT_SHARED,
    REASON_ORIGIN_NOT_EXTERNAL_LIVE,
    REASON_PLAINTEXT_TRANSPORT_NOT_SHARED,
    REASON_POSTURE_NOT_LIVE_VERIFIED,
    REQUIRED_CHECK_CODES,
    REQUIRED_FAIL_CLOSED_CODES,
)
from app.services.model_gateway.litellm.qualification_report import (
    QualificationCheck,
    build_qualification_report,
    live_evidence_blocking_reason,
)
from tests.model_gateway.conftest import BASE_URL, CONTENT_LOGGING_POSTURE, VIRTUAL_KEY
from tests.model_gateway.litellm_qualification_support import full_report, qualification_section


async def test_a_local_fixture_run_passes_but_leaves_the_live_gate_open() -> None:
    report = await full_report(evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE)

    assert report.passed is True
    assert report.missing_check_codes == ()
    assert report.live_evidence_state == LIVE_EVIDENCE_PENDING_EXTERNAL_GATE
    # A local contract run must never present itself as live proof.
    assert report.gate_satisfied is False


async def test_the_gate_closes_only_on_live_evidence_with_a_live_verified_posture() -> None:
    declared_live_run = await full_report(evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE)
    assert declared_live_run.live_evidence_state == LIVE_EVIDENCE_PENDING_EXTERNAL_GATE
    assert declared_live_run.gate_satisfied is False

    confirmed = await full_report(evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE, live_posture=True)
    assert confirmed.live_evidence_state == LIVE_EVIDENCE_CONFIRMED
    assert confirmed.gate_satisfied is True


async def test_an_unknown_evidence_origin_is_never_treated_as_live() -> None:
    report = await full_report(evidence_origin="production_probably")

    assert report.evidence_origin == EVIDENCE_ORIGIN_LOCAL_FIXTURE
    assert report.gate_satisfied is False


async def test_a_missing_required_check_keeps_the_gate_closed() -> None:
    report = await full_report(evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE, live_posture=True)
    trimmed = build_qualification_report(
        config=build_gateway_config(
            endpoint_url=BASE_URL,
            virtual_key=VIRTUAL_KEY,
            config_json={"litellm_gateway": qualification_section()},
        ),
        evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE,
        checks=[check for check in report.checks if check.code != FAIL_CLOSED_MODEL_GROUP_MISMATCH],
    )

    assert trimmed.passed is True
    assert trimmed.missing_check_codes == (FAIL_CLOSED_MODEL_GROUP_MISMATCH,)
    assert trimmed.gate_satisfied is False


async def test_two_declarations_alone_cannot_close_the_live_gate() -> None:
    """``evidence_origin`` and ``verified_against`` are both caller-supplied.

    One is an argument, the other a string in the provider config, so on their own
    two edits would let the local fixture present itself as live proof. The state
    therefore also requires facts the run cannot assert about itself.
    """

    loopback_section = qualification_section(
        host_allowlist=["127.0.0.1"],
        content_logging={**CONTENT_LOGGING_POSTURE, "verified_against": VERIFIED_AGAINST_LIVE},
    )
    config = build_gateway_config(
        endpoint_url="https://127.0.0.1:4000/v1",
        virtual_key=VIRTUAL_KEY,
        config_json={"litellm_gateway": loopback_section},
    )

    # Both declarations say "live". The endpoint says otherwise, and it wins.
    report = build_qualification_report(
        config=config,
        evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE,
        checks=[QualificationCheck(code, "passed") for code in (*REQUIRED_CHECK_CODES, *REQUIRED_FAIL_CLOSED_CODES)],
    )

    assert report.passed is True
    assert report.missing_check_codes == ()
    assert report.live_evidence_state == LIVE_EVIDENCE_PENDING_EXTERNAL_GATE
    assert report.live_evidence_blocking_reason == REASON_LOOPBACK_ENDPOINT_NOT_SHARED
    assert report.gate_satisfied is False


async def test_a_plaintext_transport_is_never_live_evidence() -> None:
    section = qualification_section(
        host_allowlist=["127.0.0.1"],
        tls={"mode": "plaintext_loopback"},
        content_logging={**CONTENT_LOGGING_POSTURE, "verified_against": VERIFIED_AGAINST_LIVE},
    )
    config = build_gateway_config(
        endpoint_url="http://127.0.0.1:4000/v1",
        virtual_key=VIRTUAL_KEY,
        config_json={"litellm_gateway": section},
    )

    assert config.transport.tls.plaintext is True
    # The transport is reported rather than the endpoint: a plaintext trust mode is
    # admitted only on loopback, so it is the more specific of the two facts.
    assert live_evidence_blocking_reason(config, EVIDENCE_ORIGIN_EXTERNAL_LIVE) == (
        REASON_PLAINTEXT_TRANSPORT_NOT_SHARED
    )
    # A TLS endpoint on loopback is still refused, by the endpoint rule.
    assert live_evidence_blocking_reason(
        build_gateway_config(
            endpoint_url="https://127.0.0.1:4000/v1",
            virtual_key=VIRTUAL_KEY,
            config_json={"litellm_gateway": qualification_section(host_allowlist=["127.0.0.1"])},
        ),
        EVIDENCE_ORIGIN_EXTERNAL_LIVE,
    ) == REASON_LOOPBACK_ENDPOINT_NOT_SHARED


async def test_the_report_records_why_the_live_gate_stayed_open() -> None:
    local = await full_report(evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE)
    assert local.live_evidence_blocking_reason == REASON_ORIGIN_NOT_EXTERNAL_LIVE

    declared = await full_report(evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE)
    assert declared.live_evidence_blocking_reason == REASON_POSTURE_NOT_LIVE_VERIFIED

    confirmed = await full_report(evidence_origin=EVIDENCE_ORIGIN_EXTERNAL_LIVE, live_posture=True)
    assert confirmed.live_evidence_blocking_reason == ""
    assert confirmed.to_evidence()["live_evidence_blocking_reason"] == ""
