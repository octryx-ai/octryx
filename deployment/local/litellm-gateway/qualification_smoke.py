"""Local activation qualification for the governed LiteLLM gateway.

Drives the *product* client and the *product* qualification service
(``backend/app/services/model_gateway/litellm/``) against the deterministic
LiteLLM-compatible fixture in this directory, over a real TLS socket, and writes
the resulting report to the allowlisted evidence path (`<repo>/evidence/`).

What this proves against a server rather than a mock transport:

1. an explicit private CA bundle is the trust store: the same endpoint served by
   the same certificate is refused when only a foreign CA is configured;
2. hostile ambient ``HTTP_PROXY``/``HTTPS_PROXY``/``ALL_PROXY``/``NO_PROXY``
   variables are ignored: they are exported for the whole run and point at a
   closed port, and every call still succeeds;
2b. the ambient CA variables (``SSL_CERT_FILE``/``SSL_CERT_DIR``/
   ``REQUESTS_CA_BUNDLE``/``CURL_CA_BUNDLE``) are ignored *discriminatingly*:
   pointing them at a foreign bundle proves nothing, because the configured
   private CA already trusts the server and an extra anchor would not break the
   handshake. They are therefore pointed at the **genuine** CA while the product
   is configured with only the **foreign** one, so honouring them would turn a
   refusal into a success. The built trust store is then read back and must hold
   exactly the configured anchor;
3. a governed proxy really carries the call: the CONNECT tunnel is observed at the
   proxy, and the direct run never touches it;
4. per admitted alias: integral prompt/completion usage, the declared cost
   contract (``gateway_reported`` strictly positive, ``governed_free`` zero,
   ``catalog_pricing`` positive), governed model-group response identity, and
   ``model_info.supports_*`` capability parity;
5. each mismatch case is refused with its expected state and a fixed message;
6. the virtual key is sent to the gateway and appears nowhere else.

What it does not prove: the cluster's LiteLLM version, virtual-key scope,
content-logging configuration, model groups, or cost shape. The report therefore
records ``evidence_origin=local_contract_fixture`` and leaves
``live_evidence_state=pending_external_gate``.

Boundaries: no ``.env`` file, no application settings, no AWS, no cluster, no
network beyond loopback. The virtual key, the TLS private key, request bodies and
response bodies are never printed.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from fixture_contract import (  # noqa: E402
    ALLOWED_HOSTS,
    FAIL_CLOSED_SCENARIOS,
    GATEWAY_REPORTED_COST,
    HOST,
    QUALIFYING_SCENARIOS,
    endpoint_url,
    gateway_config_json,
    scenario_by_alias,
)
from forward_proxy import LocalConnectProxy  # noqa: E402
from gateway_fixture import CHAT_PATH, MODELS_PATH, LocalGatewayFixture  # noqa: E402
from tls_material import CA_COMMON_NAME, FOREIGN_CA_COMMON_NAME, generate_tls_material  # noqa: E402

from app.services.model_gateway.litellm import build_gateway_config  # noqa: E402
from app.services.model_gateway.litellm.capability_evidence import ProbeEvidenceCache  # noqa: E402
from app.services.model_gateway.litellm.client import LiteLLMGatewayHttpClient  # noqa: E402
from app.services.model_gateway.litellm.errors import (  # noqa: E402
    GATEWAY_STATE_CAPABILITY_NOT_PROVEN,
    GATEWAY_STATE_FALLBACK_VIOLATION,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
    GATEWAY_STATE_UNREACHABLE,
    LiteLLMGatewayError,
)
from app.services.model_gateway.litellm.evidence_writer import write_qualification_evidence  # noqa: E402
from app.services.model_gateway.litellm.qualification import (  # noqa: E402
    EVIDENCE_ORIGIN_LOCAL_FIXTURE,
    FAIL_CLOSED_CAPABILITY_NOT_PROVEN,
    FAIL_CLOSED_CATALOG_COST_NOT_POSITIVE,
    FAIL_CLOSED_FREE_CONTRACT_REPORTED_COST,
    FAIL_CLOSED_GATEWAY_COST_NOT_POSITIVE,
    FAIL_CLOSED_MODEL_GROUP_MISMATCH,
    FAIL_CLOSED_USAGE_NOT_REPORTED,
    LIVE_EVIDENCE_PENDING_EXTERNAL_GATE,
    STATUS_FAILED,
    STATUS_PASSED,
    FailClosedExpectation,
    QualificationCheck,
    build_qualification_report,
    qualify_fail_closed,
    run_alias_qualification,
)
from app.services.model_gateway.litellm.usage_contract import (  # noqa: E402
    COST_DENIAL_CATALOG_NOT_POSITIVE,
    COST_DENIAL_FREE_CONTRACT_REPORTED_COST,
    COST_DENIAL_GATEWAY_NOT_POSITIVE,
    USAGE_DENIAL_NOT_REPORTED,
)

# Harness-observed checks. They belong to the report because they are part of the
# activation gate, but only a hostile environment plus a real proxy can prove them,
# so they are produced here rather than by the product service.
CHECK_PRIVATE_CA_TRUST_ENFORCED = "private_ca_trust_enforced"
CHECK_AMBIENT_PROXY_IGNORED = "ambient_proxy_environment_ignored"
CHECK_AMBIENT_CA_IGNORED = "ambient_ca_environment_ignored"
CHECK_GOVERNED_PROXY_EGRESS = "governed_proxy_egress_observed"
CHECK_VIRTUAL_KEY_PRESENTED = "virtual_key_presented_to_gateway"

# Harness checks the run must produce. A check that was never appended is not a
# pass, exactly as ``QualificationReport.missing_check_codes`` treats the product
# ones, so a refactor that drops one fails the smoke instead of shrinking it.
HARNESS_REQUIRED_CHECKS = (
    CHECK_PRIVATE_CA_TRUST_ENFORCED,
    CHECK_AMBIENT_PROXY_IGNORED,
    CHECK_AMBIENT_CA_IGNORED,
    CHECK_GOVERNED_PROXY_EGRESS,
    CHECK_VIRTUAL_KEY_PRESENTED,
)

EVIDENCE_SLUG = "issue-825-litellm-qualification"
EVIDENCE_FILENAME = "local-contract-fixture"

# A closed loopback port and a foreign bundle: if the client honoured any of these
# the run would fail instead of passing.
SINKHOLE_PROXY = "http://127.0.0.1:1"
HOSTILE_PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
HOSTILE_CA_VARIABLES = ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")

FAIL_CLOSED_EXPECTATIONS: tuple[tuple[str, FailClosedExpectation], ...] = (
    (
        "octryx-fixture-mismatch",
        FailClosedExpectation(FAIL_CLOSED_MODEL_GROUP_MISMATCH, GATEWAY_STATE_FALLBACK_VIOLATION),
    ),
    (
        "octryx-fixture-no-usage",
        FailClosedExpectation(
            FAIL_CLOSED_USAGE_NOT_REPORTED, GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, USAGE_DENIAL_NOT_REPORTED
        ),
    ),
    (
        "octryx-fixture-zero-reported-cost",
        FailClosedExpectation(
            FAIL_CLOSED_GATEWAY_COST_NOT_POSITIVE,
            GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
            COST_DENIAL_GATEWAY_NOT_POSITIVE,
        ),
    ),
    (
        "octryx-fixture-paid-free",
        FailClosedExpectation(
            FAIL_CLOSED_FREE_CONTRACT_REPORTED_COST,
            GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
            COST_DENIAL_FREE_CONTRACT_REPORTED_COST,
        ),
    ),
    (
        "octryx-fixture-catalog-zero",
        FailClosedExpectation(
            FAIL_CLOSED_CATALOG_COST_NOT_POSITIVE,
            GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
            COST_DENIAL_CATALOG_NOT_POSITIVE,
        ),
    ),
    (
        "octryx-fixture-unproven-tools",
        FailClosedExpectation(FAIL_CLOSED_CAPABILITY_NOT_PROVEN, GATEWAY_STATE_CAPABILITY_NOT_PROVEN),
    ),
)

PROBE_MESSAGES = [{"role": "user", "content": "ping"}]
PROBE_TOOLS = [{"type": "function", "function": {"name": "qualification_noop", "parameters": {}}}]


def _check(code: str, passed: bool, **detail: object) -> QualificationCheck:
    return QualificationCheck(code, STATUS_PASSED if passed else STATUS_FAILED, detail=detail)


def _export_hostile_environment(foreign_bundle: Path) -> None:
    for name in HOSTILE_PROXY_VARIABLES:
        os.environ[name] = SINKHOLE_PROXY
    os.environ["NO_PROXY"] = ""
    os.environ["no_proxy"] = ""
    _point_ambient_ca_at(foreign_bundle)


def _point_ambient_ca_at(bundle: Path) -> None:
    for name in HOSTILE_CA_VARIABLES:
        os.environ[name] = str(bundle)


def _trust_store_subjects(config: object) -> set[str]:
    """Common names of the anchors the product actually loaded, or an empty set."""

    context = config.transport.tls.ssl_context()  # type: ignore[attr-defined]
    if context is None:
        return set()
    return {
        str(value)
        for certificate in context.get_ca_certs()
        for rdn in certificate.get("subject", ())
        for name, value in rdn
        if name == "commonName"
    }


def _build_client(config_json: dict, port: int, virtual_key: str) -> LiteLLMGatewayHttpClient:
    config = build_gateway_config(
        endpoint_url=endpoint_url(port),
        virtual_key=virtual_key,
        config_json=config_json,
    )
    # A fresh evidence cache per client, so every run really probes the fixture.
    return LiteLLMGatewayHttpClient(config, evidence_cache=ProbeEvidenceCache())


async def _run_fail_closed(config_json: dict, port: int, virtual_key: str) -> list[QualificationCheck]:
    checks: list[QualificationCheck] = []
    for alias, expectation in FAIL_CLOSED_EXPECTATIONS:
        client = _build_client(config_json, port, virtual_key)
        entry = next(item for item in client.config.aliases if item.alias == alias)
        scenario = scenario_by_alias(alias)
        tools = PROBE_TOOLS if scenario.model_info == {} else None
        try:
            checks.append(
                await qualify_fail_closed(
                    expectation,
                    lambda c=client, e=entry, t=tools: c.chat_completion(
                        entry=e, messages=PROBE_MESSAGES, tools=t
                    ),
                )
            )
        finally:
            await client.aclose()
    return checks


async def _trust_store_checks(material, port: int, virtual_key: str) -> list[QualificationCheck]:
    """Two checks over one deliberately hostile arrangement.

    The product is configured with the **foreign** CA while the ambient CA
    variables point at the **genuine** one. Both outcomes are then decidable:

    - the handshake must still fail, because only the configured bundle is the
      trust store (``private_ca_trust_enforced``);
    - honouring ``SSL_CERT_FILE``/``SSL_CERT_DIR``/``REQUESTS_CA_BUNDLE``/
      ``CURL_CA_BUNDLE`` would have made it succeed, so the refusal — plus a
      trust store that holds exactly the configured anchor and not the genuine
      one — is positive evidence that they were ignored
      (``ambient_ca_environment_ignored``).

    Pointing those variables at the foreign bundle instead, as this harness first
    did, decides nothing: the configured private CA already trusts the server, so
    an extra ambient anchor would not have changed a single result.
    """

    _point_ambient_ca_at(material.ca_bundle_path)
    try:
        config_json = gateway_config_json(
            ca_bundle_path=str(material.foreign_ca_bundle_path),
            scenarios=QUALIFYING_SCENARIOS,
        )
        client = _build_client(config_json, port, virtual_key)
        subjects = _trust_store_subjects(client.config)
        state = ""
        leaked = False
        try:
            await client.probe_evidence(force_refresh=True)
        except LiteLLMGatewayError as error:
            state = error.gateway_state
            message = str(error)
            leaked = any(token in message for token in (virtual_key, "certificate", "SSL", "verify failed"))
        finally:
            await client.aclose()
    finally:
        _point_ambient_ca_at(material.foreign_ca_bundle_path)

    refused = state == GATEWAY_STATE_UNREACHABLE
    return [
        _check(
            CHECK_PRIVATE_CA_TRUST_ENFORCED,
            refused and not leaked,
            gateway_state=state or "response_accepted",
            transport_text_leaked=leaked,
        ),
        _check(
            CHECK_AMBIENT_CA_IGNORED,
            refused and subjects == {FOREIGN_CA_COMMON_NAME},
            ambient_ca_variables=len(HOSTILE_CA_VARIABLES),
            ambient_ca_points_at_valid_anchor=True,
            trust_store_anchor_count=len(subjects),
            trust_store_holds_ambient_anchor=CA_COMMON_NAME in subjects,
        ),
    ]


async def _qualify(config_json: dict, port: int, virtual_key: str) -> tuple[list[QualificationCheck], object]:
    client = _build_client(config_json, port, virtual_key)
    try:
        checks = await run_alias_qualification(client=client, config=client.config)
        return list(checks), client.config
    finally:
        await client.aclose()


async def main() -> int:
    virtual_key = os.environ.pop("OCTRYX_FIXTURE_VIRTUAL_KEY", "") or f"sk-fixture-{secrets.token_hex(16)}"
    tls_directory = Path(os.environ.get("OCTRYX_FIXTURE_TLS_DIR") or tempfile.mkdtemp(prefix="octryx-litellm-fixture-"))
    material = generate_tls_material(tls_directory)
    _export_hostile_environment(material.foreign_ca_bundle_path)

    with LocalGatewayFixture(
        virtual_key=virtual_key,
        certificate_path=material.server_certificate_path,
        key_path=material.server_key_path,
    ) as gateway:
        direct_config = gateway_config_json(
            ca_bundle_path=str(material.ca_bundle_path),
            scenarios=QUALIFYING_SCENARIOS,
        )
        fail_closed_config = gateway_config_json(
            ca_bundle_path=str(material.ca_bundle_path),
            scenarios=FAIL_CLOSED_SCENARIOS,
        )

        print("[1/5] direct TLS qualification of every admitted alias")
        checks, config = await _qualify(direct_config, gateway.port, virtual_key)
        direct_requests = gateway.requests
        checks.append(
            # Discriminating on its own: every hostile proxy variable names a
            # closed loopback port, so a client that honoured one would have
            # reached no gateway at all and recorded zero requests here.
            _check(
                CHECK_AMBIENT_PROXY_IGNORED,
                bool(direct_requests) and all(request.authorization_matched for request in direct_requests),
                hostile_proxy_variables=len(HOSTILE_PROXY_VARIABLES),
                observed_request_count=len(direct_requests),
            )
        )
        checks.append(
            _check(
                CHECK_VIRTUAL_KEY_PRESENTED,
                all(request.authorization_matched for request in direct_requests)
                and {request.path for request in direct_requests} == {MODELS_PATH, CHAT_PATH},
                authorized_request_count=len(direct_requests),
            )
        )

        print("[2/5] fail-closed response contract")
        gateway.reset()
        checks.extend(await _run_fail_closed(fail_closed_config, gateway.port, virtual_key))

        print("[3/5] private CA trust store enforcement and ambient CA discrimination")
        gateway.reset()
        checks.extend(await _trust_store_checks(material, gateway.port, virtual_key))

        print("[4/5] governed proxy egress")
        gateway.reset()
        with LocalConnectProxy(allowed_targets=((HOST, gateway.port),)) as proxy:
            proxied_config = gateway_config_json(
                ca_bundle_path=str(material.ca_bundle_path),
                scenarios=QUALIFYING_SCENARIOS,
                proxy_url=proxy.url,
                proxy_hosts=("127.0.0.1",),
            )
            proxied_checks, _ = await _qualify(proxied_config, gateway.port, virtual_key)
            tunnel_targets = set(proxy.tunnel_targets)
        proxied_passed = all(check.passed for check in proxied_checks)
        checks.append(
            _check(
                CHECK_GOVERNED_PROXY_EGRESS,
                proxied_passed and tunnel_targets == {f"{HOST}:{gateway.port}"},
                proxied_check_count=len(proxied_checks),
                tunnel_target_count=len(tunnel_targets),
                direct_run_used_proxy=False,
            )
        )

        print("[5/5] report and evidence")
        report = build_qualification_report(
            config=config,
            evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE,
            checks=checks,
        )
        target = write_qualification_evidence(
            report,
            repo_root=REPO_ROOT,
            slug=EVIDENCE_SLUG,
            filename=EVIDENCE_FILENAME,
        )

    written = target.read_text(encoding="utf-8")
    key_leaked = virtual_key in written or ALLOWED_HOSTS[0] not in written
    for check in report.checks:
        print(f"  {check.status:6} {check.code}{(' ' + check.alias) if check.alias else ''}")
    print(f"  evidence_origin      : {report.evidence_origin}")
    print(f"  live_evidence_state  : {report.live_evidence_state}")
    print(f"  live gate held by    : {report.live_evidence_blocking_reason}")
    print(f"  gate_satisfied       : {report.gate_satisfied}")
    print(f"  evidence file        : {target.relative_to(REPO_ROOT)}")
    print(f"  gateway_reported cost: strictly positive ({GATEWAY_REPORTED_COST > 0})")

    failures = [check.code for check in report.failed_checks]
    if failures:
        print(f"FAILED checks: {sorted(failures)}")
        return 1
    if report.missing_check_codes:
        print(f"FAILED missing required checks: {list(report.missing_check_codes)}")
        return 1
    produced = {check.code for check in report.checks}
    missing_harness = [code for code in HARNESS_REQUIRED_CHECKS if code not in produced]
    if missing_harness:
        print(f"FAILED missing harness checks: {missing_harness}")
        return 1
    if key_leaked:
        print("FAILED evidence content guard")
        return 1
    if (
        report.live_evidence_state != LIVE_EVIDENCE_PENDING_EXTERNAL_GATE
        or report.gate_satisfied
        or not report.live_evidence_blocking_reason
    ):
        # A local fixture must never be able to close the live gate, and it must
        # say which condition held the gate open.
        print("FAILED local run claimed live evidence")
        return 1
    print(
        "PASSED local contract qualification. The shared-environment activation gate stays open: "
        "external live gateway evidence is still required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
