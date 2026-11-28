"""A pipeline of the repository's environment file (``pipeline``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .pipeline_commands import _env


def _pointer(view: dict[str, Any]) -> dict[str, Any] | None:
    pointer = view.get("environment_file")
    return pointer if isinstance(pointer, dict) and pointer.get("file") else None


def from_file(view: dict[str, Any], root: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    from . import environment_file  # noqa: PLC0415

    pointer = _pointer(view) or {}
    account = environment_file.resolve(root, str(pointer.get("file") or ""), view.get("environment_pin"))
    folder = environment_file.folder_of(root, account)
    environment_file.exclude(root, account)
    if account["state"] != environment_file.OK or account["app_folder"] != pointer.get("app_folder"):
        if account["state"] == environment_file.OK:
            account = {**account, "state": environment_file.INVALID, "commands": [],
                       "errors": ["the app folder is not the one the platform named"]}
        return {**view, "commands": [], "path": []}, account, folder
    environment = account["environment"]
    commands = list(account["commands"])
    if view.get("system_test") is False and environment.get("system_test"):
        # The run's size class leaves the system test out (server ``size_class/pipeline_scope``).
        commands = [command for command in commands if command != environment["system_test"]]
    return {**view, "commands": commands, "path": list(environment.get("path") or []),
            **({"browser": environment["browser"]} if environment.get("browser") else {}),
            **({"system_test_command": environment["system_test"]} if environment.get("system_test") else {})}, \
        account, folder


def ready_folder(view: dict[str, Any], account: dict[str, Any], folder: Path) -> dict[str, Any]:
    from . import environment_file  # noqa: PLC0415

    environment = account["environment"]
    env = _env(folder, list(view.get("path") or []), {"browser": view["browser"]} if view.get("browser") else None)
    ready, log = environment_file.setup(folder, environment, env)
    return {**account, "setup": log, **({} if ready else {"state": environment_file.SETUP_FAILED})}


def _repository_files(results: list[dict[str, Any]], app_folder: str) -> list[dict[str, Any]]:
    if app_folder in ("", "."):
        return results
    for item in results:
        for part in (item, item.get("rerun") if isinstance(item.get("rerun"), dict) else None):
            if part and part.get("junit_files"):
                part["junit_files"] = [f"{app_folder}/{name}" for name in part["junit_files"]]
    return results
