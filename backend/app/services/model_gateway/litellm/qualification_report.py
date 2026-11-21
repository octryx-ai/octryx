"""Qualification checks and the closed report built from them (see ``qualification`` for the gate contract)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .config import LiteLLMGatewayConfig
from .content_logging import VERIFIED_AGAINST_LIVE
from .evidence import close_evidence
from .network_path import build_network_path_contract
from .qualification_codes import (
    _CODE_RE,
    _PATH_RE,
    EVIDENCE_ORIGIN_EXTERNAL_LIVE,
    EVIDENCE_ORIGIN_LOCAL_FIXTURE,
    EVIDENCE_ORIGINS,
    LIVE_EVIDENCE_CONFIRMED,
    LIVE_EVIDENCE_PENDING_EXTERNAL_GATE,
    REASON_LOOPBACK_ENDPOINT_NOT_SHARED,
    REASON_ORIGIN_NOT_EXTERNAL_LIVE,
    REASON_PLAINTEXT_TRANSPORT_NOT_SHARED,
    REASON_POSTURE_NOT_LIVE_VERIFIED,
    REQUIRED_CHECK_CODES,
    REQUIRED_FAIL_CLOSED_CODES,
    STATUS_FAILED,
    STATUS_PASSED,
    TRANSPORT_ASSURANCE_ATTESTED_NODE_ENCRYPTION,
    TRANSPORT_ASSURANCE_LOOPBACK_PLAINTEXT,
    TRANSPORT_ASSURANCE_VERIFIED_TLS,
)
from .transport_codes import TLS_MODE_PLAINTEXT_LOOPBACK
from .transport_decisions import TlsTrustPolicy


def _closed_detail(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only numbers, booleans, and closed lowercase codes.

    Structural, not cosmetic: a body fragment, a header, or a prompt cannot
    survive this filter, so the report is safe to persist by construction.
    """

    def _value(value: Any) -> Any:
        if isinstance(value, bool) or isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            return value if _CODE_RE.match(value) or _PATH_RE.match(value) else ""
        if isinstance(value, (list, tuple)):
            return [item for item in (_value(entry) for entry in value) if item != ""]
        return ""

    return {key: _value(value) for key, value in payload.items() if isinstance(key, str) and _CODE_RE.match(key)}


@dataclass(frozen=True, slots=True)
class QualificationCheck:
    code: str
    status: str
    alias: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == STATUS_PASSED

    def to_evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"check": self.code, "status": self.status}
        if self.alias:
            payload["alias"] = self.alias
        detail = _closed_detail(self.detail)
        if detail:
            payload["detail"] = detail
        return payload


def _passed(code: str, *, alias: str = "", **detail: Any) -> QualificationCheck:
    return QualificationCheck(code, STATUS_PASSED, alias, detail)


def _failed(code: str, *, alias: str = "", **detail: Any) -> QualificationCheck:
    return QualificationCheck(code, STATUS_FAILED, alias, detail)


@dataclass(frozen=True, slots=True)
class QualificationReport:
    evidence_origin: str
    live_evidence_state: str
    gateway_evidence: Mapping[str, Any]
    checks: tuple[QualificationCheck, ...]
    # Which condition kept the live gate open; "" when the run is live evidence.
    live_evidence_blocking_reason: str = ""
    # How the gateway leg is protected (``TRANSPORT_ASSURANCE_*``).
    transport_assurance: str = ""

    @property
    def failed_checks(self) -> tuple[QualificationCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and not self.failed_checks

    @property
    def missing_check_codes(self) -> tuple[str, ...]:
        """Required checks that were never run. A missing check is not a pass."""

        present = {check.code for check in self.checks}
        return tuple(
            code for code in (*REQUIRED_CHECK_CODES, *REQUIRED_FAIL_CLOSED_CODES) if code not in present
        )

    @property
    def gate_satisfied(self) -> bool:
        """True only when every required check passed against confirmed live evidence.

        Read it as "this report is ready for operator review", not as an
        attestation of the peer's identity (see the module docstring).
        """

        return (
            self.passed
            and not self.missing_check_codes
            and self.live_evidence_state == LIVE_EVIDENCE_CONFIRMED
        )

    def to_evidence(self) -> dict[str, Any]:
        return {
            "qualification": "litellm_gateway",
            "evidence_origin": self.evidence_origin,
            "live_evidence_state": self.live_evidence_state,
            "live_evidence_blocking_reason": self.live_evidence_blocking_reason,
            "transport_assurance": self.transport_assurance,
            "passed": self.passed,
            "gate_satisfied": self.gate_satisfied,
            "missing_check_codes": list(self.missing_check_codes),
            "gateway": dict(self.gateway_evidence),
            "checks": [check.to_evidence() for check in self.checks],
        }


def transport_assurance(tls: TlsTrustPolicy) -> str:
    """The closed code for what protects the gateway leg."""

    if tls.cluster_internal:
        return TRANSPORT_ASSURANCE_ATTESTED_NODE_ENCRYPTION
    if tls.plaintext:
        return TRANSPORT_ASSURANCE_LOOPBACK_PLAINTEXT
    return TRANSPORT_ASSURANCE_VERIFIED_TLS


def live_evidence_blocking_reason(config: LiteLLMGatewayConfig, origin: str) -> str:
    """Why this run is not live evidence, or "" when it is.

    Ordered so the returned code names the *first* condition an operator has to
    change. The endpoint and transport conditions are the load-bearing ones: they
    are validated facts about the run, while the origin and the posture's
    ``verified_against`` are declarations a caller supplies.
    """

    if origin != EVIDENCE_ORIGIN_EXTERNAL_LIVE:
        return REASON_ORIGIN_NOT_EXTERNAL_LIVE
    # Transport before endpoint: ``plaintext_loopback`` is only admitted for a
    # loopback endpoint, so checking loopback first would make this branch
    # unreachable and report the less specific of the two facts.
    # ``plaintext_cluster_internal`` is not a fixture shape (a cluster Service
    # name, operator-attested node encryption), so it does not hold the gate
    # open; ``transport_assurance`` records that it is not verified TLS.
    if config.transport.tls.mode == TLS_MODE_PLAINTEXT_LOOPBACK:
        return REASON_PLAINTEXT_TRANSPORT_NOT_SHARED
    if config.endpoint.loopback:
        # A loopback answer came from this machine, so it is a fixture whatever the
        # caller declared.
        return REASON_LOOPBACK_ENDPOINT_NOT_SHARED
    if config.content_logging.verified_against != VERIFIED_AGAINST_LIVE:
        return REASON_POSTURE_NOT_LIVE_VERIFIED
    return ""


def build_qualification_report(
    *,
    config: LiteLLMGatewayConfig,
    evidence_origin: str,
    checks: Sequence[QualificationCheck],
) -> QualificationReport:
    """Assemble the closed report. An unknown origin is never treated as live."""

    origin = evidence_origin if evidence_origin in EVIDENCE_ORIGINS else EVIDENCE_ORIGIN_LOCAL_FIXTURE
    blocking_reason = live_evidence_blocking_reason(config, origin)
    contract = build_network_path_contract(
        endpoint=config.endpoint,
        transport=config.transport,
        probe=config.probe,
    )
    return QualificationReport(
        evidence_origin=origin,
        live_evidence_state=(
            LIVE_EVIDENCE_PENDING_EXTERNAL_GATE if blocking_reason else LIVE_EVIDENCE_CONFIRMED
        ),
        live_evidence_blocking_reason=blocking_reason,
        transport_assurance=transport_assurance(config.transport.tls),
        # The least-privilege network path travels with the report: an operator
        # reads the required egress from the evidence, not from the adapter.
        # ``close_evidence`` keeps the payload inside the shared allowlist.
        gateway_evidence=close_evidence({**config.evidence(), **contract.evidence()}),
        checks=tuple(checks),
    )
