"""Instance settings of the skill catalog, stored in ``system_config`` and edited by platform admins.

- ``licence_allowlist``: SPDX ids a published version may carry (default MIT, Apache-2.0, BSD-2-Clause,
  BSD-3-Clause, ISC and MPL-2.0). ``Internal`` (written on the platform) is always allowed.
- ``allowed_hosts``: Git hosts the importer and the update check may contact (default ``github.com``); every
  fetch also passes ``outbound_url_policy``.
- ``update_check_hours``: how often the scheduled upstream check runs (default 24; 0 turns it off).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, SystemConfig
from .errors import SkillCatalogError

CONFIG_KEY = "skill_catalog.settings"
LICENCE_INTERNAL = "Internal"
DEFAULT_LICENCE_ALLOWLIST = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0")
DEFAULT_ALLOWED_HOSTS = ("github.com",)
DEFAULT_UPDATE_CHECK_HOURS = 24
MAX_UPDATE_CHECK_HOURS = 24 * 30
_SPDX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$")
_HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
AUDIT_SETTINGS_SAVED = "skill_catalog.settings_saved"


@dataclass(frozen=True, slots=True)
class CatalogSettings:
    licence_allowlist: tuple[str, ...] = DEFAULT_LICENCE_ALLOWLIST
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    update_check_hours: int = DEFAULT_UPDATE_CHECK_HOURS

    def licence_allowed(self, spdx: str | None) -> bool:
        if not spdx:
            return False
        return spdx == LICENCE_INTERNAL or spdx in self.licence_allowlist

    def as_dict(self) -> dict[str, Any]:
        return {"licence_allowlist": list(self.licence_allowlist), "allowed_hosts": list(self.allowed_hosts),
                "update_check_hours": self.update_check_hours, "always_allowed_licences": [LICENCE_INTERNAL]}


def _validated(payload: dict[str, Any], current: CatalogSettings) -> CatalogSettings:
    licences = payload.get("licence_allowlist", list(current.licence_allowlist))
    hosts = payload.get("allowed_hosts", list(current.allowed_hosts))
    hours = payload.get("update_check_hours", current.update_check_hours)
    if not isinstance(licences, list) or not all(isinstance(item, str) and _SPDX.match(item) for item in licences):
        raise SkillCatalogError("skill_settings_licence_invalid", 422, message="Licences are SPDX identifiers.")
    normalized_hosts = [str(item).strip().lower() for item in hosts] if isinstance(hosts, list) else None
    if normalized_hosts is None or not all(_HOST.match(item) for item in normalized_hosts):
        raise SkillCatalogError("skill_settings_host_invalid", 422, message="Hosts are DNS names like github.com.")
    if not isinstance(hours, int) or isinstance(hours, bool) or not 0 <= hours <= MAX_UPDATE_CHECK_HOURS:
        raise SkillCatalogError("skill_settings_schedule_invalid", 422,
                                message=f"The check interval is 0-{MAX_UPDATE_CHECK_HOURS} hours.")
    return CatalogSettings(tuple(sorted(set(licences))), tuple(sorted(set(normalized_hosts))), hours)


async def load_settings(db: AsyncSession) -> CatalogSettings:
    row = await db.get(SystemConfig, CONFIG_KEY)
    if row is None or not row.value:
        return CatalogSettings()
    try:
        stored = json.loads(row.value)
        return _validated(stored if isinstance(stored, dict) else {}, CatalogSettings())
    except (ValueError, SkillCatalogError):
        # A hand-edited row that does not validate falls back to the defaults, which are the strict ones.
        return CatalogSettings()


async def save_settings(db: AsyncSession, payload: dict[str, Any], *, actor_id: str) -> CatalogSettings:
    settings = _validated(payload, await load_settings(db))
    row = await db.get(SystemConfig, CONFIG_KEY)
    value = json.dumps(settings.as_dict(), sort_keys=True)
    if row is None:
        db.add(SystemConfig(key=CONFIG_KEY, value=value, description="Skill catalog settings"))
    else:
        row.value = value
    db.add(AuditLog(user_id=actor_id, action=AUDIT_SETTINGS_SAVED, resource_type="skill_catalog",
                    resource_id=CONFIG_KEY, details=settings.as_dict()))
    await db.flush()
    return settings


__all__ = [
    "DEFAULT_ALLOWED_HOSTS",
    "DEFAULT_LICENCE_ALLOWLIST",
    "LICENCE_INTERNAL",
    "CatalogSettings",
    "load_settings",
    "save_settings",
]
