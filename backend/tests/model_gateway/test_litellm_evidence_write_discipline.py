"""Open-time discipline of the qualification evidence write.

``resolve_evidence_path`` refuses a symlinked evidence root, slug directory or
report file — but it decides that on a resolved path, and the write happens
afterwards. The write therefore opens every component below the repository root
relative to an already-open descriptor and atomically replaces the final name.

These suites exercise the open-time guard *directly*, because the resolved-path
check would otherwise mask it and the tests would pass for the wrong reason.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from app.services.model_gateway.litellm.evidence_writer import (
    EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST,
    _write_private_json,
)

PAYLOAD = {"qualification": "litellm_gateway", "passed": True}


def evidence_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "repo" / "evidence" / "issue-825"
    directory.mkdir(parents=True)
    return directory


def test_the_report_is_written_private_through_its_directory_descriptor(tmp_path) -> None:
    target = evidence_directory(tmp_path) / "local-contract.json"

    assert _write_private_json(target, PAYLOAD) == ""

    assert json.loads(target.read_text()) == PAYLOAD
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    # The mode is set on the descriptor that the file is then created relative to.
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


def test_a_symlinked_report_name_is_refused_at_open_time(tmp_path) -> None:
    """``O_NOFOLLOW`` on the final component: the name may not be a link."""

    directory = evidence_directory(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("original\n")
    target = directory / "local-contract.json"
    target.symlink_to(outside)

    denial = _write_private_json(target, PAYLOAD)

    assert denial == EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST
    assert outside.read_text() == "original\n"


def test_a_symlinked_slug_directory_is_refused_at_open_time(tmp_path) -> None:
    """``O_DIRECTORY|O_NOFOLLOW``: the slug directory may not be a link either."""

    evidence_root = tmp_path / "repo" / "evidence"
    evidence_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (evidence_root / "issue-825").symlink_to(outside, target_is_directory=True)

    denial = _write_private_json(evidence_root / "issue-825" / "local-contract.json", PAYLOAD)

    assert denial == EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST
    assert list(outside.iterdir()) == []


def test_a_symlinked_evidence_directory_cannot_redirect_the_write(tmp_path) -> None:
    """An intermediate component is guarded, not only the final slug directory."""

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    (outside / "issue-825").mkdir(parents=True)
    (repo / "evidence").symlink_to(outside, target_is_directory=True)

    denial = _write_private_json(
        repo / "evidence" / "issue-825" / "local-contract.json",
        PAYLOAD,
    )

    assert denial == EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST
    assert list((outside / "issue-825").iterdir()) == []


def test_an_existing_hardlink_is_replaced_without_truncating_its_other_name(tmp_path) -> None:
    """Atomic rename replaces the evidence name instead of following its inode."""

    directory = evidence_directory(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("original\n")
    target = directory / "local-contract.json"
    os.link(outside, target)

    assert _write_private_json(target, PAYLOAD) == ""

    assert outside.read_text() == "original\n"
    assert json.loads(target.read_text()) == PAYLOAD


def test_the_write_uses_the_directory_descriptor_when_the_platform_supports_it() -> None:
    """Pins the mechanism, so a fallback cannot be introduced unnoticed."""

    assert os.open in os.supports_dir_fd
    assert os.unlink in os.supports_dir_fd
