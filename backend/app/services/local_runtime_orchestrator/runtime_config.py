"""Where the managed local runtime lives and how it is configured: paths, defaults and compose commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models import LLMProvider
from ..provider_runtime_config import parse_provider_runtime_bool

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
LOCAL_RUNTIME_DATA_DIR = REPO_ROOT / "data" / "local-runtimes"
DEFAULT_START_TIMEOUT_SECONDS = 90.0
DEFAULT_STOP_TIMEOUT_SECONDS = 30.0


def _provider_config_dict(provider: LLMProvider | None, config_json: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(config_json, dict):
        return dict(config_json)
    if provider and isinstance(provider.config_json, dict):
        return dict(provider.config_json)
    return {}


def _local_runtime_defaults(driver: str) -> dict[str, str]:
    return {
        "strategy": "docker_compose",
        "compose_service": "ollama",
        "compose_profile": "",
    }


def _default_endpoint_url(driver: str) -> str:
    return "http://localhost:11434"


def resolve_local_runtime_config(
    *,
    driver: str,
    provider: LLMProvider | None = None,
    config_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = _provider_config_dict(provider, config_json)
    defaults = _local_runtime_defaults(driver)
    compose_file = str(config.get("local_runtime_compose_file") or DEFAULT_COMPOSE_FILE).strip()
    compose_file_path = Path(compose_file).expanduser().resolve()
    runtime_slug = "ollama"
    return {
        "strategy": str(config.get("local_runtime_strategy") or defaults["strategy"]).strip()
        or defaults["strategy"],
        "auto_start": parse_provider_runtime_bool(config.get("local_runtime_auto_start"), default=True),
        "allow_host_fallback": parse_provider_runtime_bool(
            config.get("local_runtime_allow_host_fallback"),
            default=False,
        ),
        "compose_service": str(config.get("local_runtime_compose_service") or defaults["compose_service"]).strip()
        or defaults["compose_service"],
        "compose_profile": str(config.get("local_runtime_compose_profile") or defaults["compose_profile"]).strip(),
        "compose_file": str(compose_file_path),
        "compose_cwd": str(compose_file_path.parent),
        "binary_path": str(
            config.get("local_runtime_binary_path") or getattr(provider, "binary_path", "") or ""
        ).strip(),
        "runtime_slug": runtime_slug,
        "pid_file": str((LOCAL_RUNTIME_DATA_DIR / f"{runtime_slug}.pid").resolve()),
        "log_file": str((LOCAL_RUNTIME_DATA_DIR / f"{runtime_slug}.log").resolve()),
    }


def _compose_command(
    *,
    compose_file: str,
    compose_profile: str,
    action: str,
    compose_service: str,
) -> list[str]:
    args = ["docker", "compose", "-f", compose_file]
    if compose_profile:
        args.extend(["--profile", compose_profile])
    args.extend([action, "-d" if action == "up" else "", compose_service])
    return [item for item in args if item]
