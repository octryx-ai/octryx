"""Shared fake service manager and registration helpers for the device CLI tests."""

from __future__ import annotations

import pytest

from octryx_claude import device_folder_access, device_service


class FakeManager:
    kind = "systemd"

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def install(self, shim, log_file):
        self.calls.append("install")
        if self.fail:
            raise device_service.ServiceError("systemd_command_failed")

    def uninstall(self):
        self.calls.append("uninstall")

    def status(self):
        return device_service.ServiceStatus("systemd", True, True)


@pytest.fixture(autouse=True)
def no_service_probe(monkeypatch):
    monkeypatch.setattr(device_folder_access, "probe_from_service", lambda state, folders: None)
