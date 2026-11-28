"""There is no ``diagnosis_review_commands`` setting: it would never change an outcome."""

from __future__ import annotations

from app.services.exec_policy.policy_config import DEFAULT_EXEC_POLICY_CONFIG, normalize_exec_policy_config
from app.services.security_analyzer.builtins import read_only_command_finding


def test_unrecognized_commands_need_review():
    config = normalize_exec_policy_config({})

    assert read_only_command_finding("terraform apply", config).action == "review"
    assert read_only_command_finding("npm install", config).action == "review"
    assert read_only_command_finding("ls -la", config).action == "allow"


def test_a_stored_review_list_is_dropped_from_the_config():
    config = normalize_exec_policy_config({"diagnosis_review_commands": ["npm"]})

    assert "diagnosis_review_commands" not in DEFAULT_EXEC_POLICY_CONFIG
    assert "diagnosis_review_commands" not in config
