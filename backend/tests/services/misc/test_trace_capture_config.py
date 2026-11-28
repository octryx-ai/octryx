from __future__ import annotations

from app.services.trace_capture import ensure_default_trace_capture_config


def test_a_new_workspace_config_starts_in_standard_capture_mode():
    config = ensure_default_trace_capture_config({"managed_repo_root": "var/repos"})

    assert config == {"managed_repo_root": "var/repos", "trace_capture": {"mode": "standard"}}


def test_an_existing_trace_capture_setting_is_kept():
    config = ensure_default_trace_capture_config({"trace_capture": {"mode": "minimal"}})

    assert config["trace_capture"] == {"mode": "minimal"}
