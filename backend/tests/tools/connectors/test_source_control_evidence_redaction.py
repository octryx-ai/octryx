from __future__ import annotations

from app.services.source_control import (
    SourceControlOperation,
    redact_source_control_text,
    sanitize_source_control_payload,
)
from app.tools.bitbucket_impl._bitbucket_internal_core import _redact_bitbucket_git_output
from app.tools.bitbucket_impl._bitbucket_source_control import bitbucket_source_control_metadata
from app.tools.connectors.github_source_control_common import github_source_control_metadata, redact_github_git_output
from app.tools.connectors.gitlab_source_control_common import gitlab_source_control_metadata, redact_gitlab_git_output
from app.tools.context import ToolContext


def _context(project_config: dict) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["operator"],
        session_id="session-1",
        project_config=project_config,
    )


def test_source_control_text_redacts_credentialed_urls_and_secret_assignments():
    redacted = redact_source_control_text(
        "fatal: https://user:secret@source.example/org/repo.git "
        "Authorization: Bearer abc123 token=abc123 password=abc123",
    )

    assert "user:secret" not in redacted
    assert "Bearer abc123" not in redacted
    assert "token=abc123" not in redacted
    assert "password=abc123" not in redacted
    assert "https://source.example/org/repo.git" in redacted
    assert "Authorization: [redacted]" in redacted
    assert "token=[redacted]" in redacted
    assert "password=[redacted]" in redacted


def test_source_control_payload_sanitizer_drops_unsafe_keys_without_losing_safe_metadata():
    payload = {
        "remote_url": "https://source.example/org/repo.git",
        "stderr": "fatal: https://user:secret@source.example/org/repo.git",
        "headers": {"Authorization": "Bearer abc123"},
        "branches": [{"name": "main", "latest_commit": "abc123"}],
    }

    sanitized = sanitize_source_control_payload(payload)

    assert sanitized["remote_url"] == "https://source.example/org/repo.git"
    assert sanitized["stderr"] == "fatal: https://source.example/org/repo.git"
    assert sanitized["branches"] == [{"name": "main", "latest_commit": "abc123"}]
    assert "headers" not in sanitized
    assert sanitized["redacted_fields"] == ["headers"]


def test_provider_metadata_helpers_sanitize_output_and_evidence_before_serialization():
    output = {
        "remote_url": "https://source.example/org/repo.git",
        "branch_name": "codex/test",
        "token": "abc123",
    }
    evidence = {
        "stderr": "fatal: https://user:secret@source.example/org/repo.git Authorization: Bearer abc123",
        "headers": {"Authorization": "Bearer abc123"},
        "provider_response": {"clone_url": "https://user:secret@source.example/org/repo.git"},
    }

    metadata_items = [
        bitbucket_source_control_metadata(
            SourceControlOperation.PREPARE_REPOSITORY,
            project_key="PROJ",
            repo_slug="repo",
            status="failed",
            output=output,
            evidence=evidence,
        ),
        github_source_control_metadata(
            SourceControlOperation.PREPARE_REPOSITORY,
            owner="org",
            repo="repo",
            status="failed",
            output=output,
            evidence=evidence,
        ),
        gitlab_source_control_metadata(
            SourceControlOperation.PREPARE_REPOSITORY,
            project="org/repo",
            status="failed",
            output=output,
            evidence=evidence,
        ),
    ]

    for metadata in metadata_items:
        serialized = str(metadata)
        assert "user:secret" not in serialized
        assert "Bearer abc123" not in serialized
        assert "token': 'abc123" not in serialized
        assert metadata["output"]["redacted_fields"] == ["token"]
        assert metadata["evidence"]["redacted_fields"] == ["headers"]
        assert metadata["evidence"]["provider_response"]["clone_url"] == "https://source.example/org/repo.git"


def test_provider_git_output_redactors_use_shared_source_control_rules():
    bitbucket_output = _redact_bitbucket_git_output(
        _context({"bitbucket_username": "user", "bitbucket_token": "secret"}),
        "fatal: https://user:secret@source.example/org/repo.git token=secret password=secret",
    )
    github_output = redact_github_git_output(
        _context({"github_token": "gh-secret"}),
        "fatal: https://user:gh-secret@source.example/org/repo.git token=gh-secret",
    )
    gitlab_output = redact_gitlab_git_output(
        _context({"gitlab_token": "gl-secret"}),
        "fatal: https://user:gl-secret@source.example/org/repo.git token=gl-secret",
    )

    for output, secret in (
        (bitbucket_output, "secret"),
        (github_output, "gh-secret"),
        (gitlab_output, "gl-secret"),
    ):
        assert secret not in output
        assert "user:" not in output
        assert "token=[redacted]" in output
