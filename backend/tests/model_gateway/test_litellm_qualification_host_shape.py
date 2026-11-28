"""Closed host-shaped evidence fields admit deployment hostnames while credentials and non-finite values still fail closed."""

from __future__ import annotations

import dataclasses
import json
import math
from typing import Any

import pytest

from app.services.model_gateway.litellm import build_gateway_config
from app.services.model_gateway.litellm.evidence_host_shape import (
    is_hop_rule_shaped,
    is_host_shaped,
)
from app.services.model_gateway.litellm.evidence_payload_check import (
    EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE,
    EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_FINITE,
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
from tests.model_gateway.conftest import VIRTUAL_KEY, gateway_section

# The shape of the environment this gate is actually for. Both labels carry
# ``sk-`` inside ``nonprod``, which the shared redaction policy matches as
# a substring — the evidence writer must still accept its own hostnames.
TARGET_GATEWAY_HOST = "litellm.nonprod.example.com"


TARGET_PROXY_HOST = "egress.nonprod.example.com"


# The evidence writer runs every string
# through the shared redaction policy, which matches ``sk-`` as a *substring* so
# a key pasted into free text is caught. The intended deployment's own hostnames
# contain that substring inside ``nonprod``, so the qualification could not
# write evidence for the environment it gates. The closed fields that are defined
# to hold a host now admit a value only when it is provably host-shaped; every
# other value, and any non-host under those same keys, still fails closed.


def target_gateway_config() -> dict[str, Any]:
    section = gateway_section(
        host_allowlist=[TARGET_GATEWAY_HOST],
        proxy={
            "mode": "governed_proxy",
            "url": f"https://{TARGET_PROXY_HOST}:3128",
            "host_allowlist": [TARGET_PROXY_HOST],
        },
    )
    return {"litellm_gateway": section}


def target_host_report():
    config = build_gateway_config(
        endpoint_url=f"https://{TARGET_GATEWAY_HOST}/v1",
        virtual_key=VIRTUAL_KEY,
        config_json=target_gateway_config(),
    )
    return build_qualification_report(
        config=config,
        evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE,
        checks=[
            QualificationCheck(code, "passed")
            for code in (*REQUIRED_CHECK_CODES, *REQUIRED_FAIL_CLOSED_CODES)
        ],
    )


def test_a_hostname_carrying_a_credential_prefix_inside_a_label_is_host_shaped() -> None:
    assert is_host_shaped(TARGET_GATEWAY_HOST) is True
    assert is_host_shaped(TARGET_PROXY_HOST) is True
    assert is_host_shaped("127.0.0.1") is True
    # A credential prefix is a prefix: at the start of a label it is refused.
    assert is_host_shaped("sk-live-4ec39hqlyjwdarjtt1zdp7dc.example.com") is False
    assert is_host_shaped("sk-live-4ec39hqlyjwdarjtt1zdp7dc") is False
    assert is_host_shaped("glpat-ab" + "cdefghijklmnopqrst.example.com") is False
    # Anything that is not a bare host leaves the exemption entirely.
    assert is_host_shaped(f"https://{TARGET_GATEWAY_HOST}/v1") is False
    assert is_host_shaped(f"user:pass@{TARGET_GATEWAY_HOST}") is False
    assert is_host_shaped("Bearer sk-secret-value") is False


def test_a_hop_rule_is_admitted_only_when_every_part_is_the_closed_shape() -> None:
    assert is_hop_rule_shaped(f"direct_egress:https:{TARGET_GATEWAY_HOST}:443") is True
    assert is_hop_rule_shaped(f"proxy_egress:https:{TARGET_PROXY_HOST}:3128") is True
    assert is_hop_rule_shaped("tunneled_destination:https:127.0.0.1:8443") is True
    for refused in (
        f"unknown_role:https:{TARGET_GATEWAY_HOST}:443",
        f"direct_egress:ftp:{TARGET_GATEWAY_HOST}:21",
        f"direct_egress:https:{TARGET_GATEWAY_HOST}:0",
        f"direct_egress:https:{TARGET_GATEWAY_HOST}:99999",
        "direct_egress:https:sk-live-4ec39hqlyjwdarjtt1zdp7dc.example.com:443",
        f"https://virtual:sk-secret@{TARGET_GATEWAY_HOST}:443",
    ):
        assert is_hop_rule_shaped(refused) is False, refused


async def test_the_target_host_shape_writes_evidence_instead_of_being_refused(tmp_path) -> None:
    report = target_host_report()

    target = write_qualification_evidence(
        report, repo_root=tmp_path, slug="issue-825", filename="local-contract"
    )

    payload = json.loads(target.read_text())
    assert payload["gateway"]["endpoint_host"] == TARGET_GATEWAY_HOST
    assert payload["gateway"]["proxy_host"] == TARGET_PROXY_HOST
    # The hops are rendered by the product, not restated here, so the assertion
    # fails if the rule format and the admitted shape ever drift apart.
    assert payload["gateway"]["network_path_hops"] == [
        f"proxy_egress:https:{TARGET_PROXY_HOST}:3128",
        f"tunneled_destination:https:{TARGET_GATEWAY_HOST}:443",
    ]
    assert VIRTUAL_KEY not in target.read_text()


async def test_a_real_key_or_credential_url_under_a_host_key_still_fails_closed(tmp_path) -> None:
    report = target_host_report()

    refused: list[tuple[str, Any]] = [
        ("endpoint_host", "sk-live-4ec39hqlyjwdarjtt1zdp7dc"),
        ("endpoint_host", f"https://virtual:sk-secret@{TARGET_GATEWAY_HOST}/v1"),
        ("proxy_host", "xoxb-1234-5678-abcdefghijklmnop"),
        ("proxy_host", "Bearer sk-secret-value"),
        ("network_path_hops", ["direct_egress:https:sk-live-4ec39hqlyjwdarjtt1zdp7dc.example.com:443"]),
        ("network_path_hops", [f"https://virtual:sk-secret@{TARGET_GATEWAY_HOST}:443"]),
        # A closed field that is *not* host-shaped keeps the generic scan.
        ("cost_contract_reference", "sk-live-4ec39hqlyjwdarjtt1zdp7dc"),
    ]

    for key, value in refused:
        poisoned = dataclasses.replace(report, gateway_evidence={**report.gateway_evidence, key: value})
        with pytest.raises(EvidenceWriteDeniedError) as excinfo:
            write_qualification_evidence(poisoned, repo_root=tmp_path, slug="issue-825", filename="denied")
        assert excinfo.value.denial_reason == EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE, (key, value)
    assert not (tmp_path / "evidence" / "issue-825" / "denied.json").exists()


async def test_a_non_finite_evidence_value_is_refused_and_never_written(tmp_path) -> None:
    report = target_host_report()

    for value in (float("nan"), float("inf"), float("-inf")):
        poisoned = dataclasses.replace(
            report,
            checks=(*report.checks, QualificationCheck("cost_contract", "passed", detail={"cost": value})),
        )
        with pytest.raises(EvidenceWriteDeniedError) as excinfo:
            write_qualification_evidence(poisoned, repo_root=tmp_path, slug="issue-825", filename="denied")
        assert excinfo.value.denial_reason == EVIDENCE_DENIAL_PAYLOAD_VALUE_NOT_FINITE
        assert not (tmp_path / "evidence" / "issue-825" / "denied.json").exists()

    written = write_qualification_evidence(
        report, repo_root=tmp_path, slug="issue-825", filename="local-contract"
    )
    raw = written.read_text()
    for literal in ("NaN", "Infinity"):
        assert literal not in raw
    # ``parse_constant`` is only called for exactly those literals, so a strict
    # reader's view of the file is asserted, not merely Python's.
    parsed = json.loads(raw, parse_constant=lambda name: pytest.fail(f"non-JSON literal {name}"))
    assert all(
        math.isfinite(value)
        for value in parsed["gateway"].values()
        if isinstance(value, float)
    )
