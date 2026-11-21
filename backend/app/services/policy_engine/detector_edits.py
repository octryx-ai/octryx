"""Custom content detectors in the policy-set draft.

``PUT …/policy-sets/{v}/detectors`` replaces the custom detectors and categories of the working draft with the
same contract as a policy edit (``policy_edits``): ``If-Match`` with the digest of ``{v}`` as the client saw it,
a new draft from the published version when none is open (its policies are kept), and the saved test cases run
on save. A detector scoped to a Workspace must name an existing one, and a detector a policy still names cannot
be removed. The audit row names the detector ids, categories and counts; patterns stay in the version, which only
platform admins read.

``detector_catalog`` is the Detectors tab: the built-in categories and detectors, the custom ones of the version,
and per detector the policies of that version that use it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.content_detection.custom_definitions import ERROR_INVALID, DetectorDefinitions, DetectorSetError
from app.services.content_detection.custom_validation import check_detector_set

from ...models import AuditLog, PolicySetVersion, Project
from ..content_detection.vocabulary import BUILTIN_DETECTORS, CUSTOM_PREFIX
from . import store
from .policy_edits import edit_base, save_edit
from .policy_text import index_statements, split_statements

AUDIT_DETECTORS_SAVED = "policy_engine.content_detectors_saved"
ISSUE_WORKSPACE_UNKNOWN = "workspace_unknown"
ISSUE_DETECTOR_IN_USE = "detector_in_use"


async def _check_workspaces(db: AsyncSession, raw: Any) -> None:
    definitions = check_detector_set(raw)
    wanted = {item.workspace_id for item in definitions.detectors if item.workspace_id}
    if not wanted:
        return
    found = set((await db.execute(select(Project.id).where(Project.id.in_(wanted)))).scalars())
    missing = sorted(wanted - found)
    if missing:
        raise DetectorSetError(ERROR_INVALID, [
            {"detector_id": item.id, "code": ISSUE_WORKSPACE_UNKNOWN, "message": "The Workspace does not exist."}
            for item in definitions.detectors if item.workspace_id in missing])


def _check_in_use(text: str, definitions: DetectorDefinitions) -> None:
    """Refuse a save that drops a custom detector a policy of the base text still names."""
    defined = {item.id for item in definitions.detectors}
    missing = sorted((name, policies) for name, policies in _used_by(text).items()
                     if name.startswith(CUSTOM_PREFIX) and name not in defined)
    if missing:
        raise DetectorSetError(ERROR_INVALID, [
            {"detector_id": name, "code": ISSUE_DETECTOR_IN_USE,
             "message": f"Used by {', '.join(sorted(policies))}; remove it from those policies first."}
            for name, policies in missing])


async def put_detectors(
    db: AsyncSession, version: int, raw: Any, *, if_match: str | None, note: Any, actor_id: str
) -> PolicySetVersion:
    """Save the definitions into the draft; ``DetectorSetError`` (422) or ``PolicyEditError``. Flushes."""
    definitions = check_detector_set(raw)
    await _check_workspaces(db, raw)
    draft, text, _previous = await edit_base(db, version, if_match)
    _check_in_use(text, definitions)
    row = await save_edit(db, draft, text, note, actor_id, definitions)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_DETECTORS_SAVED, resource_type="policy_set_version",
                    resource_id=row.id, details={
                        "version": row.version, "digest": row.digest,
                        "detectors": [item.id for item in definitions.detectors],
                        "categories": [item.id for item in definitions.categories]}))
    await db.flush()
    return row


def _used_by(text: str) -> dict[str, list[str]]:
    """``{quoted string: [policy ids]}`` of every string literal (comma parts too) a policy of ``text`` mentions."""
    if not split_statements(text).statements:
        return {}
    used: dict[str, list[str]] = {}
    for statement in index_statements(text):
        # ``@mask("a,b")`` names several detectors in one literal.
        tokens = {part.strip() for literal in statement.text.split('"')[1::2] for part in literal.split(",")}
        for token in tokens:
            used.setdefault(token, []).append(statement.policy_id)
    return used


def detector_catalog(row: PolicySetVersion | None) -> dict[str, Any]:
    definitions = store.detector_definitions(row)
    used = _used_by(str(row.policies_text or "")) if row is not None else {}
    builtin = [{**item.to_dict(), "used_by": sorted(used.get(item.id, []))} for item in BUILTIN_DETECTORS]
    custom = [{**item.to_json(), **item.info().to_dict(), "used_by": sorted(used.get(item.id, []))}
              for item in definitions.detectors]
    return {
        "version": row.version if row is not None else None,
        "state": row.state if row is not None else None,
        "digest": row.digest if row is not None else None,
        "categories": [item.to_dict() for item in definitions.all_categories()],
        "detectors": builtin + custom,
    }


__all__ = ["AUDIT_DETECTORS_SAVED", "detector_catalog", "put_detectors"]
