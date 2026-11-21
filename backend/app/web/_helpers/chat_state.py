"""Chat state builders and branding helpers."""

# ruff: noqa: I001

import json
import logging
import re
from pathlib import Path

from fastapi import HTTPException

from ...services.branding_feature_policy import branding_enabled, require_branding_enabled
from .branding_svg import _sanitize_logo_svg

logger = logging.getLogger(__name__)
root_logger = logging.getLogger()

__all__ = [
    "ARTIFACT_LINE_PATTERN",
    "CHAT_MESSAGE_PAGE_SIZE",
    "_BRANDING_DATA_FILE",
    "_default_branding_config",
    "_load_branding_config",
    "_save_branding_config",
]

ARTIFACT_LINE_PATTERN = re.compile(r"(?i)(?:saved\s+(?:as|to)|written\s+to)\s*:\s*(.+)")
CHAT_MESSAGE_PAGE_SIZE = 80
_BRANDING_DATA_FILE = Path(__file__).resolve().parents[5] / "data" / "branding.json"


def _log_exception(message: str, *args: object) -> None:
    logger.exception(message, *args)
    if logger.disabled or not logger.propagate:
        root_logger.exception(message, *args)


def _log_warning(message: str, *args: object) -> None:
    logger.warning(message, *args)
    if logger.disabled or not logger.propagate:
        root_logger.warning(message, *args)


def _default_branding_config() -> dict:
    return {
        "app_name": "Octryx",
        "logo_url": "/chat/static/chat/message-logo.svg",
        "logo_svg": "",
    }


def _invalid_branding_fallback_config() -> dict:
    return {
        "app_name": "Octryx",
        "logo_url": "",
        "logo_svg": "",
    }


def _load_branding_config() -> dict:
    # Feature off: the built-in defaults; any stored branding stays on disk unapplied.
    if not branding_enabled():
        return {**_default_branding_config(), "enabled": False}
    return {**_load_stored_branding_config(), "enabled": True}


def _load_stored_branding_config() -> dict:
    try:
        if _BRANDING_DATA_FILE.exists():
            data = json.loads(_BRANDING_DATA_FILE.read_text())
            default = _default_branding_config()
            logo_url = (
                str(data["logo_url"]).strip()
                if "logo_url" in data
                else str(default["logo_url"]).strip()
            )
            logo_svg = str(data.get("logo_svg") or "")
            try:
                sanitized_logo_svg = _sanitize_logo_svg(logo_svg)
            except ValueError:
                _log_warning("Dropping unsafe inline SVG branding from %s", _BRANDING_DATA_FILE)
                sanitized_logo_svg = ""
            if logo_url:
                sanitized_logo_svg = ""
            default.update(
                {
                    "app_name": str(data.get("app_name") or default["app_name"]),
                    "logo_url": logo_url,
                    "logo_svg": sanitized_logo_svg,
                }
            )
            return default
    except Exception:
        _log_exception("Failed to load branding config from %s", _BRANDING_DATA_FILE)
    return _invalid_branding_fallback_config()


def _save_branding_config(config: dict) -> dict:
    require_branding_enabled()
    try:
        logo_svg = _sanitize_logo_svg(str(config.get("logo_svg") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload = {
        "app_name": str(config.get("app_name") or "Octryx").strip() or "Octryx",
        "logo_url": str(config.get("logo_url") or "").strip(),
        "logo_svg": logo_svg,
    }
    if payload["logo_url"]:
        payload["logo_svg"] = ""
    _BRANDING_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    _BRANDING_DATA_FILE.write_text(json.dumps(payload, indent=2))
    return {**payload, "enabled": True}
