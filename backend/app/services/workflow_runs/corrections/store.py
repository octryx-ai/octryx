"""Where corrections are kept (``correction_signatures``) and the Workspace's settings for them.

``capture`` is called at the moment a correction happens (never by reading events back): it redacts, normalises,
finds the signature for the Workspace, repository and app, counts the repeat and keeps the occurrence. It never
stands in the way of what triggered it: a failure is logged and dropped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ....models import CorrectionSignature, Project
from ....time_utils import utc_now
from . import signature

CONFIG_KEY = "check_proposals"
SETTING_KEYS = ("threshold", "approver_permission", "sources")
RUN_LINK = "/chat?area=work&work_view=runs&run_id={run_id}"

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Correction:
    """One correction as its source saw it; ``people`` are names to redact besides the Workspace's members."""

    source: str
    check_kind: str
    message: str
    file: str = ""
    run_id: str = ""
    work_item_key: str = ""
    link: str = ""
    people: tuple[Any, ...] = field(default=())
    #: The code state for a check proposal's proof, as far as the source knows it: ``before_sha`` / ``after_sha``
    #: (commits) or ``before_tree`` / ``after_tree`` (git tree ids of the run's working copy), and ``paths``.
    code: dict[str, Any] = field(default_factory=dict)
    ref: str = ""  # the source's own id (a comment's), so one occurrence seen twice (webhook and poll) counts once


def settings(project: Project | None) -> dict[str, dict[str, Any]]:
    """The three settings with their source (``default`` or ``workspace``), as the contract's ``GET /settings``."""
    defaults = signature.data()["settings"]
    stored = dict(dict(getattr(project, "config", None) or {}).get(CONFIG_KEY) or {})
    view: dict[str, dict[str, Any]] = {}
    for name in SETTING_KEYS:
        value = stored.get(name)
        valid = (isinstance(value, int) and not isinstance(value, bool) and value >= 1) if name == "threshold" else (
            isinstance(value, list) and all(item in defaults["sources"] for item in value)) if name == "sources" else (
            isinstance(value, str) and bool(value.strip()))
        view[name] = {"value": value if valid else defaults[name], "source": "workspace" if valid else "default"}
    return view


async def _names(db: Any, project_id: str, people: tuple[Any, ...]) -> tuple[str, ...]:
    from ..work_roles import workspace_humans

    members = await workspace_humans(db, project_id)
    return signature.name_parts([*members.values(), *people])


async def capture(db: Any, project_id: str | None, repository: str | None, app: str, correction: Correction,
                  ) -> CorrectionSignature | None:
    """Keep ``correction`` for the Workspace, repository and app; the signature row, or ``None`` when the source is
    off, the correction says nothing, or keeping it failed (logged, never raised)."""
    if not project_id or not repository or not str(correction.message or "").strip():
        return None
    try:
        async with db.begin_nested():
            return await _capture(db, project_id, repository, app or ".", correction)
    except Exception:  # noqa: BLE001 - a correction is information, never in the way of what caused it
        _LOG.warning("correction_capture_failed", extra={"source": correction.source}, exc_info=True)
        return None


async def _capture(db: Any, project_id: str, repository: str, app: str,
                   correction: Correction) -> CorrectionSignature | None:
    from ...observability.agent_metrics import on_commit
    from ...observability.correction_metrics import CAPTURED, OVER_THRESHOLD

    project = await db.get(Project, project_id)
    current = settings(project)
    if correction.source not in current["sources"]["value"]:
        return None
    names = await _names(db, project_id, correction.people)
    message = signature.normalise(signature.redact(correction.message, names))
    if not re.sub(r"<\w+>", "", message).strip(" .,:;-()[]"):
        return None  # nothing but placeholders: says nothing about what was wrong
    pattern = signature.file_pattern(correction.file)
    key = signature.key(correction.check_kind, pattern, message)
    now = utc_now()
    row = await _row(db, project_id, repository, app, key)
    if row is not None and correction.ref and any(item.get("ref") == correction.ref for item in row.occurrences or []):
        return row
    if row is None:
        hint = signature.kind_hint(correction.check_kind)
        row = CorrectionSignature(project_id=project_id, repository=repository, app=app, signature_key=key,
                                  check_kind=correction.check_kind, kind_hint=hint,
                                  file_pattern=pattern, message=message, repeats=0, first_seen=now, last_seen=now,
                                  occurrences=[])
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:  # a concurrent capture created it first: count on that row
            row = await _row(db, project_id, repository, app, key)
            if row is None:
                return None
    occurrence = {"source": correction.source, "run_id": correction.run_id or None,
                  "work_item_key": correction.work_item_key or None, "at": now.isoformat(),
                  "excerpt": signature.excerpt(correction.message, names),
                  "link": correction.link or (RUN_LINK.format(run_id=correction.run_id) if correction.run_id else None),
                  **{name: value for name, value in correction.code.items() if value},
                  **({"ref": correction.ref} if correction.ref else {})}
    limit = int(signature.data()["max_occurrences"])
    row.occurrences = [occurrence, *list(row.occurrences or [])][:limit]
    row.repeats = int(row.repeats or 0) + 1
    row.last_seen = now
    crossed = row.over_threshold_at is None and row.repeats >= int(current["threshold"]["value"])
    if crossed:
        row.over_threshold_at = now
    await db.flush()
    source, hint = correction.source, row.kind_hint
    on_commit(db, lambda: CAPTURED.inc(source=source))
    if crossed:
        on_commit(db, lambda: OVER_THRESHOLD.inc(kind_hint=hint))
    await _updated(db, row.id)
    return row


async def _updated(db: Any, signature_id: str) -> None:
    """``check_proposals.signature_updated`` decides on a proposal after every update. Until that
    function ships there is nobody to tell; its failure never undoes the capture (its own savepoint)."""
    import importlib

    try:
        module = importlib.import_module("app.services.check_proposals")
    except ImportError:
        return
    updated = getattr(module, "signature_updated", None)
    if updated is None:
        return
    try:
        async with db.begin_nested():
            await updated(db, signature_id)
    except Exception:  # noqa: BLE001 - a failed proposal never drops the correction
        _LOG.warning("check_proposal_update_failed", extra={"signature_id": signature_id}, exc_info=True)


async def get_signature(db: Any, signature_id: str) -> dict[str, Any] | None:
    """One signature in the contract's shape, or ``None``."""
    row = await db.get(CorrectionSignature, signature_id)
    return view(row) if row is not None else None


async def _row(db: Any, project_id: str, repository: str, app: str, key: str) -> CorrectionSignature | None:
    return (await db.execute(select(CorrectionSignature).where(
        CorrectionSignature.project_id == project_id, CorrectionSignature.repository == repository,
        CorrectionSignature.app == app, CorrectionSignature.signature_key == key,
    ).with_for_update())).scalar_one_or_none()


def view(row: CorrectionSignature) -> dict[str, Any]:
    """The contract's ``Signature`` shape."""
    return {"id": row.id, "workspace_id": row.project_id, "repository": row.repository, "app": row.app,
            "check_kind": row.check_kind, "kind_hint": row.kind_hint, "file_pattern": row.file_pattern,
            "message": row.message, "repeats": int(row.repeats or 0),
            "first_seen": row.first_seen.isoformat() if row.first_seen else None,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            "over_threshold_at": row.over_threshold_at.isoformat() if row.over_threshold_at else None,
            "occurrences": list(row.occurrences or [])}


__all__ = ["CONFIG_KEY", "Correction", "RUN_LINK", "capture", "get_signature", "settings", "view"]
