"""Roles marks each permission enforced or not, and the marks follow the code."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.security_scope_contract import ENFORCED_PERMISSIONS, permission_catalog, permission_keys

APP = Path(__file__).resolve().parents[1] / "app"
CHECK = re.compile(r"(?:has_permission|require_permission|_require_admin_permission_api|user_has_permission)\("
                   r"[^)]*?resource=\"([a-z_]+)\",\s*action=\"([a-z_]+)\"", re.S)


def _checked_in_code() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in APP.rglob("*.py"):
        found |= {(match.group(1), match.group(2)) for match in CHECK.finditer(path.read_text(encoding="utf-8"))}
    return found


def test_every_checked_catalog_permission_is_marked_enforced_and_no_other():
    checked = _checked_in_code() & permission_keys()
    assert checked == set(ENFORCED_PERMISSIONS)
    assert ENFORCED_PERMISSIONS <= permission_keys()


def test_the_catalog_carries_the_mark():
    catalog = {(item["resource"], item["action"]): item["enforced"] for item in permission_catalog()}
    assert catalog[("users", "read")] is True and catalog[("providers", "write")] is False
    assert sum(catalog.values()) == 14
