"""The app a workflow run works on, in a repository that holds several."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .spec import MAX_ENVIRONMENT_FILE_CHARS, app_folder, validate_environment_file

APP_KEY = "app"
APP_ENVIRONMENT_FILE = ".octryx/environment.json"
APP_SOURCE_START, APP_SOURCE_RECORD, APP_SOURCE_INTAKE = "start", "record", "intake"
# The record's apps: config_json["apps"], outside the admin's coding_setup, from the launcher's preparation report.
RECORD_APPS_KEY = "apps"
MAX_APPS = 50


def validate_app(raw: Any) -> tuple[str | None, list[str]]:
    text = raw.strip().rstrip("/") if isinstance(raw, str) else ""
    path = PurePosixPath(text or ".")
    if not isinstance(raw, str) or len(text) > MAX_ENVIRONMENT_FILE_CHARS or path.is_absolute() or (
            ".." in path.parts) or "\\" in text:
        return None, ["app is the app's folder relative to the repository (no '..', at most 200 characters), e.g. "
                      "services/api"]
    return path.as_posix(), []


def app_context(app: str, source: str) -> dict[str, Any]:
    folder = PurePosixPath(app)
    return {"path": folder.as_posix(), "environment_file": (folder / APP_ENVIRONMENT_FILE).as_posix(), "source": source}


def record_default(run: Any, pointer: str | None) -> str | None:
    # A record changed mid-run never moves the run's app.
    if pointer:
        run.context = {**dict(run.context or {}),
                       APP_KEY: {**app_context(app_folder(pointer), APP_SOURCE_RECORD), "environment_file": pointer}}
    return pointer


def run_environment_file(run: Any) -> str | None:
    path, errors = validate_environment_file(dict(dict(getattr(run, "context", None) or {}).get(APP_KEY) or {})
                                             .get("environment_file"))
    return None if errors else path


def reported_apps(report: dict[str, Any]) -> list[dict[str, str]]:
    files = [validate_environment_file(name)[0] for name in list(report.get(RECORD_APPS_KEY) or [])[:MAX_APPS]
             if isinstance(name, str)]
    return [{"path": app_folder(file), "environment_file": file} for file in sorted({file for file in files if file})]


async def remember_apps(db: Any, run: Any, report: dict[str, Any]) -> None:
    from ..platform.repo_ref import _record, parse_repository

    apps = reported_apps(report)
    ref = parse_repository(run.repository) if apps else None
    record = await _record(db, run, ref) if ref is not None else None
    if record is not None and dict(record.config_json or {}).get(RECORD_APPS_KEY) != apps:
        record.config_json = {**dict(record.config_json or {}), RECORD_APPS_KEY: apps}


async def record_apps(db: Any, run: Any) -> list[dict[str, str]]:
    from ..platform.repo_ref import _record, parse_repository

    ref = parse_repository(run.repository)
    record = await _record(db, run, ref) if ref is not None else None
    apps = dict(record.config_json or {}).get(RECORD_APPS_KEY) if record is not None else None
    return [app for app in apps if isinstance(app, dict) and app.get("path")] if isinstance(apps, list) else []


__all__ = ["APP_ENVIRONMENT_FILE", "APP_KEY", "APP_SOURCE_INTAKE", "APP_SOURCE_RECORD", "APP_SOURCE_START",
           "RECORD_APPS_KEY", "app_context", "record_apps", "record_default", "remember_apps", "reported_apps",
           "run_environment_file", "validate_app"]
