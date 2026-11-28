"""Which PowerPoint template applies when no corporate identity is configured (O1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..system_config import get_system_config_value, set_system_config_value
from .neutral_presentation_template import NEUTRAL_TEMPLATE_PATH

PRESENTATION_FALLBACK_KEY = "agent.office_presentation_fallback_template"
MODE_BUILTIN_NEUTRAL = "builtin_neutral"
MODE_DISABLED = "disabled"
PRESENTATION_FALLBACK_MODES = (MODE_BUILTIN_NEUTRAL, MODE_DISABLED)
DEFAULT_PRESENTATION_FALLBACK_MODE = MODE_BUILTIN_NEUTRAL

SOURCE_BUILTIN_NEUTRAL = "builtin_neutral_template"
SOURCE_CORP_IDENTITY = "corp_identity_profile"

#: The closed ``needs_configuration`` codes of presentation template resolution.
PRESENTATION_TEMPLATE_UNCONFIGURED = "presentation_template_unconfigured"
CORP_IDENTITY_TEMPLATE_MISSING = "corp_identity_template_missing"
NEEDS_CONFIGURATION = "needs_configuration"


class InvalidPresentationFallbackModeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PresentationFallback:
    mode: str
    #: The template the mode resolves to; ``None`` when disabled or the tracked file is missing.
    path: Path | None
    #: ``True`` when the stored value is outside the closed set (treated as ``disabled``).
    invalid_setting: bool = False

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "modes": list(PRESENTATION_FALLBACK_MODES),
            "template_file": self.path.name if self.path is not None else "",
            "available": self.path is not None,
            "invalid_setting": self.invalid_setting,
            "setting_key": PRESENTATION_FALLBACK_KEY,
        }


async def presentation_fallback(db: AsyncSession | None) -> PresentationFallback:
    stored = (await get_system_config_value(db, PRESENTATION_FALLBACK_KEY) if db is not None else None) or ""
    mode = stored.strip() or DEFAULT_PRESENTATION_FALLBACK_MODE
    if mode not in PRESENTATION_FALLBACK_MODES:
        return PresentationFallback(mode=MODE_DISABLED, path=None, invalid_setting=True)
    if mode == MODE_DISABLED:
        return PresentationFallback(mode=mode, path=None)
    return PresentationFallback(mode=mode, path=NEUTRAL_TEMPLATE_PATH if NEUTRAL_TEMPLATE_PATH.is_file() else None)


async def set_presentation_fallback_mode(db: AsyncSession, *, mode: str, updated_by: str | None) -> None:
    normalized = str(mode or "").strip()
    if normalized not in PRESENTATION_FALLBACK_MODES:
        raise InvalidPresentationFallbackModeError(normalized)
    await set_system_config_value(
        db,
        key=PRESENTATION_FALLBACK_KEY,
        value=normalized,
        description="Presentation template used when no corporate identity profile is configured.",
    )


def fallback_template_resolution(fallback: PresentationFallback) -> dict[str, Any]:
    path = fallback.path
    return {
        "source": SOURCE_BUILTIN_NEUTRAL,
        "fallback_mode": fallback.mode,
        "path": str(path) if path is not None else "",
        "template_file": path.name if path is not None else "",
    }


def needs_configuration(code: str, message: str) -> dict[str, Any]:
    return {
        "status": NEEDS_CONFIGURATION,
        "error": message,
        "error_code": code,
        "configure": ["corp_identity_profile", PRESENTATION_FALLBACK_KEY],
    }


async def describe_effective_presentation_template(db: AsyncSession) -> dict[str, Any]:
    from ..corp_identity_service import get_default_corp_identity_profile, resolve_corp_identity_composer_template

    fallback = await presentation_fallback(db)
    profile = await get_default_corp_identity_profile(db)
    if isinstance(profile, dict) and profile:
        resolved = resolve_corp_identity_composer_template(profile)
        path = Path(str(getattr(resolved, "path", "") or ""))
        usable = path.is_file()
        return {
            "source": SOURCE_CORP_IDENTITY if usable else NEEDS_CONFIGURATION,
            "error_code": "" if usable else CORP_IDENTITY_TEMPLATE_MISSING,
            "profile_id": str(profile.get("id") or ""),
            "profile_name": str(profile.get("name") or ""),
            "template_file": path.name if usable else "",
            "fallback": fallback.describe(),
        }
    if fallback.path is not None:
        return {
            "source": SOURCE_BUILTIN_NEUTRAL,
            "error_code": "",
            "profile_id": "",
            "profile_name": "",
            "template_file": fallback.path.name,
            "fallback": fallback.describe(),
        }
    return {
        "source": NEEDS_CONFIGURATION,
        "error_code": PRESENTATION_TEMPLATE_UNCONFIGURED,
        "profile_id": "",
        "profile_name": "",
        "template_file": "",
        "fallback": fallback.describe(),
    }


__all__ = [
    "CORP_IDENTITY_TEMPLATE_MISSING",
    "DEFAULT_PRESENTATION_FALLBACK_MODE",
    "MODE_BUILTIN_NEUTRAL",
    "MODE_DISABLED",
    "NEEDS_CONFIGURATION",
    "PRESENTATION_FALLBACK_KEY",
    "PRESENTATION_FALLBACK_MODES",
    "PRESENTATION_TEMPLATE_UNCONFIGURED",
    "SOURCE_BUILTIN_NEUTRAL",
    "SOURCE_CORP_IDENTITY",
    "InvalidPresentationFallbackModeError",
    "PresentationFallback",
    "describe_effective_presentation_template",
    "fallback_template_resolution",
    "needs_configuration",
    "presentation_fallback",
    "set_presentation_fallback_mode",
]
