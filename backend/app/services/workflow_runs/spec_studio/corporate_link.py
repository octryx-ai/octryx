"""The Corporate Identity on a run's Spec Studio."""

from __future__ import annotations

from typing import Any

from .corporate import corporate_direction
from .state import STUDIO_KEY, studio

CORPORATE_ID = "corporate"
SNAPSHOT_KEY = "corporate"


class StudioLockedError(ValueError):
    pass


def snapshot(run: Any) -> dict[str, Any] | None:
    found = studio(run).get(SNAPSHOT_KEY)
    return found if isinstance(found, dict) and isinstance(found.get("direction"), dict) else None


def _store(run: Any, value: dict[str, Any] | None) -> bool:
    record = studio(run)
    if record.get(SNAPSHOT_KEY) == value:
        return False
    if value is None:
        record.pop(SNAPSHOT_KEY, None)
    else:
        record[SNAPSHOT_KEY] = value
    run.context = {**dict(run.context or {}), STUDIO_KEY: record}
    return True


async def refresh(db: Any, run: Any) -> bool:
    from ...corp_identity.workspace import effective_profile
    from ..phase_outputs import output_hash
    from .service import artefact_of, base_of, frozen

    found = artefact_of(run)
    if found is None or frozen(run, found[1]):
        return False
    artefact = found[0]
    if artefact.get("mode") == "feature" and base_of(run, artefact):
        return _store(run, None)
    profile = await effective_profile(db, run.project_id)
    if not profile["profile_id"]:
        return _store(run, None)
    current = snapshot(run)
    key = [profile["profile_id"], profile.get("updated_at") or "", profile["locks"]]
    if current is not None and current.get("key") == key:
        return False
    from app.services.corp_identity.profile_edits import get_corp_identity_brief

    try:
        brief = await get_corp_identity_brief(db, profile["profile_id"])
    except (FileNotFoundError, OSError, ValueError):
        return _store(run, None)  # an unreadable profile: the spec's own directions, quietly
    direction = corporate_direction(brief)
    return _store(run, {"key": key, "profile_id": profile["profile_id"], "profile_name": profile["profile_name"],
                        "source": profile["source"], "locks": profile["locks"], "hash": output_hash(direction),
                        "direction": direction})


def asset_paths(corporate: dict[str, Any] | None) -> set[str]:
    if corporate is None:
        return set()
    extra = dict(corporate["direction"].get("corporate") or {})
    return {str(path) for path in [extra.get("logo"), *dict(extra.get("icons") or {}).values()] if path}


def _value(design: dict[str, Any], path: str) -> Any:
    head, _, tail = path.partition(".")
    return dict(design.get(head) or {}).get(tail) if tail else design.get(head)


def deviations(design: dict[str, Any], corporate: dict[str, Any] | None, state: dict[str, Any]
               ) -> list[dict[str, Any]]:
    if corporate is None:
        return []
    reasons = dict(state.get("reasons") or {})
    direction = corporate["direction"]
    if design.get("direction") != CORPORATE_ID:
        return [{"path": "direction", "corporate": direction["name"], "chosen": design.get("name") or "",
                 "reason": str(reasons.get("direction") or "")}]
    found = []
    for path, source in sorted(dict(direction["corporate"]["sources"]).items()):
        chosen, company = _value(design, path), _value(direction, path)
        if source == "ci" and chosen != company:
            found.append({"path": path, "corporate": company, "chosen": chosen, "reason": str(reasons.get(path) or "")})
    return found


def check_lock(corporate: dict[str, Any] | None, state: dict[str, Any], path: str) -> None:
    if corporate is None or not corporate.get("locks"):
        return
    on_corporate = str(state.get("direction") or CORPORATE_ID) == CORPORATE_ID
    if path == "direction" and on_corporate:
        raise StudioLockedError(f"The Corporate Identity locks {', '.join(corporate['locks'])}: the corporate "
                                "direction stays.")
    if on_corporate and path in corporate["locks"]:
        raise StudioLockedError(f"{path} is locked by the Corporate Identity {corporate['profile_name']}.")


__all__ = ["CORPORATE_ID", "asset_paths", "StudioLockedError", "check_lock", "deviations", "refresh", "snapshot"]
