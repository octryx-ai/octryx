"""The evidence writer stays under the allowlisted path and never writes secrets, prompts, URLs or open state details."""

from __future__ import annotations

import json
import stat
from typing import Any

import pytest

from app.services.model_gateway.litellm.evidence_payload_check import (
    EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_KEY,
    EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE,
)
from app.services.model_gateway.litellm.evidence_writer import (
    EVIDENCE_DENIAL_FILENAME_INVALID,
    EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST,
    EVIDENCE_DENIAL_REPO_ROOT_INVALID,
    EVIDENCE_DENIAL_SLUG_INVALID,
    EvidenceWriteDeniedError,
    write_qualification_evidence,
)
from app.services.model_gateway.litellm.qualification_codes import (
    EVIDENCE_ORIGIN_LOCAL_FIXTURE,
    FAIL_CLOSED_MODEL_GROUP_MISMATCH,
    LIVE_EVIDENCE_PENDING_EXTERNAL_GATE,
    REASON_UNEXPECTED_GATEWAY_STATE,
    REQUIRED_CHECK_CODES,
    REQUIRED_FAIL_CLOSED_CODES,
)
from app.services.model_gateway.litellm.qualification_report import QualificationCheck
from tests.model_gateway.conftest import GATEWAY_HOST, VIRTUAL_KEY
from tests.model_gateway.litellm_qualification_support import full_report


async def test_the_evidence_writer_refuses_a_symlinked_evidence_root(tmp_path) -> None:
    report = await full_report(evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE)
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo_root / "evidence").symlink_to(outside, target_is_directory=True)

    with pytest.raises(EvidenceWriteDeniedError) as excinfo:
        write_qualification_evidence(report, repo_root=repo_root, slug="issue-825", filename="local-contract")

    assert excinfo.value.denial_reason == EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST
    assert list(outside.iterdir()) == []


async def test_the_evidence_writer_refuses_a_symlinked_slug_directory(tmp_path) -> None:
    report = await full_report(evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE)
    repo_root = tmp_path / "repo"
    evidence_root = repo_root / "evidence"
    evidence_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (evidence_root / "issue-825").symlink_to(outside, target_is_directory=True)

    with pytest.raises(EvidenceWriteDeniedError) as excinfo:
        write_qualification_evidence(report, repo_root=repo_root, slug="issue-825", filename="local-contract")

    assert excinfo.value.denial_reason == EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST
    assert list(outside.iterdir()) == []


async def test_a_repository_reached_through_a_symlinked_parent_still_writes(tmp_path) -> None:
    report = await full_report(evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE)
    real_repo = tmp_path / "real-repo"
    real_repo.mkdir(parents=True)
    linked_repo = tmp_path / "linked-repo"
    linked_repo.symlink_to(real_repo, target_is_directory=True)

    target = write_qualification_evidence(
        report, repo_root=linked_repo, slug="issue-825", filename="local-contract"
    )

    assert target == real_repo.resolve() / "evidence" / "issue-825" / "local-contract.json"
    assert target.is_file()


async def test_the_report_evidence_carries_no_secret_prompt_or_url(tmp_path) -> None:
    report = await full_report(evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE)

    target = write_qualification_evidence(report, repo_root=tmp_path, slug="issue-825", filename="local-contract")

    assert target == tmp_path / "evidence" / "issue-825" / "local-contract.json"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    raw = target.read_text()
    for forbidden in (VIRTUAL_KEY, "Bearer", "://", "ping", "pong"):
        assert forbidden not in raw
    payload = json.loads(raw)
    assert payload["gateway"]["endpoint_host"] == GATEWAY_HOST
    assert payload["live_evidence_state"] == LIVE_EVIDENCE_PENDING_EXTERNAL_GATE
    assert {check["check"] for check in payload["checks"]} == set(
        (*REQUIRED_CHECK_CODES, *REQUIRED_FAIL_CLOSED_CODES)
    )


async def test_the_evidence_writer_refuses_any_path_outside_the_allowlist(tmp_path) -> None:
    report = await full_report(evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE)

    cases: list[tuple[dict[str, Any], str]] = [
        ({"repo_root": tmp_path / "absent", "slug": "issue-825", "filename": "x"}, EVIDENCE_DENIAL_REPO_ROOT_INVALID),
        ({"repo_root": "relative", "slug": "issue-825", "filename": "x"}, EVIDENCE_DENIAL_REPO_ROOT_INVALID),
        ({"repo_root": tmp_path, "slug": "../../etc", "filename": "x"}, EVIDENCE_DENIAL_SLUG_INVALID),
        ({"repo_root": tmp_path, "slug": "issue 825", "filename": "x"}, EVIDENCE_DENIAL_SLUG_INVALID),
        ({"repo_root": tmp_path, "slug": "issue-825", "filename": "../secrets"}, EVIDENCE_DENIAL_FILENAME_INVALID),
        ({"repo_root": tmp_path, "slug": "issue-825", "filename": "report.json"}, EVIDENCE_DENIAL_FILENAME_INVALID),
    ]

    observed = []
    for kwargs, _expected in cases:
        with pytest.raises(EvidenceWriteDeniedError) as excinfo:
            write_qualification_evidence(report, **kwargs)
        observed.append((kwargs, excinfo.value.denial_reason))

    assert observed == cases


async def test_the_evidence_writer_refuses_a_secret_shaped_payload(tmp_path) -> None:
    report = await full_report(evidence_origin=EVIDENCE_ORIGIN_LOCAL_FIXTURE)

    with_key = report.__class__(
        evidence_origin=report.evidence_origin,
        live_evidence_state=report.live_evidence_state,
        gateway_evidence={**report.gateway_evidence, "api_key": "sk-should-never-be-written"},
        checks=report.checks,
    )
    with pytest.raises(EvidenceWriteDeniedError) as key_error:
        write_qualification_evidence(with_key, repo_root=tmp_path, slug="issue-825", filename="denied")
    assert key_error.value.denial_reason == EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_KEY

    with_url = report.__class__(
        evidence_origin=report.evidence_origin,
        live_evidence_state=report.live_evidence_state,
        gateway_evidence={**report.gateway_evidence, "endpoint_host": f"https://{GATEWAY_HOST}/v1"},
        checks=report.checks,
    )
    with pytest.raises(EvidenceWriteDeniedError) as value_error:
        write_qualification_evidence(with_url, repo_root=tmp_path, slug="issue-825", filename="denied")
    assert value_error.value.denial_reason == EVIDENCE_DENIAL_PAYLOAD_SENSITIVE_VALUE


def test_an_unexpected_state_detail_only_carries_closed_codes() -> None:
    check = QualificationCheck(
        FAIL_CLOSED_MODEL_GROUP_MISMATCH,
        "failed",
        detail={
            "reason": REASON_UNEXPECTED_GATEWAY_STATE,
            "leaked prompt": "hello there",
            "denial_reason": "Bearer sk-secret-value",
        },
    )

    evidence = check.to_evidence()

    assert evidence["detail"] == {"reason": REASON_UNEXPECTED_GATEWAY_STATE, "denial_reason": ""}
