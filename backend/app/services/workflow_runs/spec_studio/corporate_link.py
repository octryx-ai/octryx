"""The Corporate Identity on a run's Spec Studio.

- Snapshot: the Workspace's CI profile (``corp_identity.workspace.effective_profile``) as the direction "Corporate:
  <profile>" in ``context.spec_studio.corporate``, refreshed while the spec is open (a changed profile, Workspace
  choice or lock reaches open specs) and never after approval (an approved version keeps its snapshot).
- A feature keeps the approved app's look: its tokens beat the CI profile, so a feature gets no snapshot.
- Deviations: on the corporate direction, every value taken from the template (``ci``) that the product owner changed
  is a deviation and needs a reason; another direction as a whole is one deviation (``direction``). Derived values
  change freely. Locked paths are read-only.
"""

from __future__ import annotations

from typing import Any

from .corporate import corporate_direction
from .state import STUDIO_KEY, studio

CORPORATE_ID = "corporate"
SNAPSHOT_KEY = "corporate"


class StudioLockedError(ValueError):
    """A change to a token the Corporate Identity locks (409)."""


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
    """Bring the snapshot in step with the Workspace's CI; ``True`` when it changed (the caller commits)."""
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
    """The only CI files the Studio serves for this run: its snapshot's logo and icons."""
    if corporate is None:
        return set()
    extra = dict(corporate["direction"].get("corporate") or {})
    return {str(path) for path in [extra.get("logo"), *dict(extra.get("icons") or {}).values()] if path}


def _value(design: dict[str, Any], path: str) -> Any:
    head, _, tail = path.partition(".")
    return dict(design.get(head) or {}).get(tail) if tail else design.get(head)


def deviations(design: dict[str, Any], corporate: dict[str, Any] | None, state: dict[str, Any]
               ) -> list[dict[str, Any]]:
    """``[{path, corporate, chosen, reason}]``: what the spec changes of the company's look, with the reasons."""
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
    """Refuse a change to a locked path while the corporate direction is in use (or a switch away from it when the
    direction itself is locked by any lock: the locked values would be lost)."""
    if corporate is None or not corporate.get("locks"):
        return
    on_corporate = str(state.get("direction") or CORPORATE_ID) == CORPORATE_ID
    if path == "direction" and on_corporate:
        raise StudioLockedError(f"The Corporate Identity locks {', '.join(corporate['locks'])}: the corporate "
                                "direction stays.")
    if on_corporate and path in corporate["locks"]:
        raise StudioLockedError(f"{path} is locked by the Corporate Identity {corporate['profile_name']}.")


__all__ = ["CORPORATE_ID", "asset_paths", "StudioLockedError", "check_lock", "deviations", "refresh", "snapshot"]
