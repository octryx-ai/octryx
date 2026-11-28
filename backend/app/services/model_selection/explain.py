"""Explain a turn (Runtime → Default & fallback → Explain a turn)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, Project
from .gates import CatalogModel, gate
from .resolver import REFUSAL_CHOICE_NOT_ALLOWED, SOURCE_LABELS, ModelRequest, resolve_model
from .snapshot import SelectionSnapshot, load_scope, load_snapshot

OK, NO, MID = "ok", "no", "mid"


@dataclass(slots=True)
class Explanation:
    state: str = "answered"  # answered | refused | needs_configuration | blocked | error
    title: str = ""
    note: str = ""
    trace: list[dict[str, str]] = field(default_factory=list)

    def step(self, icon: str, label: str, text: str) -> None:
        self.trace.append({"icon": icon, "label": label, "text": text})

    def payload(self) -> dict[str, Any]:
        return {"state": self.state, "title": self.title, "note": self.note, "trace": self.trace}


def _names(models: list[CatalogModel]) -> str:
    return ", ".join(model.display_name for model in models) or "none"


def explain_resolution(
    snapshot: SelectionSnapshot,
    scope: Any,
    *,
    workspace_name: str,
    request: ModelRequest,
    first_fails: bool,
) -> Explanation:
    out = Explanation()
    level = scope.data_class or "no data class"
    enabled = [model for model in snapshot.models.values() if model.enabled and model.provider_active]
    allowed = [model for model in enabled if gate(model, scope) not in {"not_allowed_in_workspace"}]
    listed = "all enabled models" if scope.assignment_mode != "selected_only" else _names(allowed)
    out.step(OK if allowed else NO, "Allowed", f"{workspace_name} allows {listed}.")
    candidates = [model for model in allowed if not gate(model, scope)]
    not_cleared = [model for model in allowed if model not in candidates]
    if not candidates:
        out.step(NO, "Data", f"No allowed model is cleared for {level}.")
        out.state, out.title = "needs_configuration", "Needs configuration"
        out.note = f"No model is available for {level} data in this Workspace. Nothing runs."
        return out
    dropped = f" Not cleared: {_names(not_cleared)}." if not_cleared else ""
    out.step(OK, "Data", f"Cleared for {level}: {_names(candidates)}.{dropped}")

    resolution = resolve_model(snapshot, scope, request)
    for item in resolution.trace:
        if item.outcome == "skipped":
            out.step(MID, "Skipped", f"{item.label}: {item.detail}")
    if resolution.refusal == REFUSAL_CHOICE_NOT_ALLOWED:
        chosen = snapshot.model(request.person_choice)
        name = chosen.display_name if chosen else request.person_choice
        out.step(NO, "Start", f"Person chose {name}. Refused: {resolution.refusal_detail}")
        out.state, out.title = "refused", f"Refused · {name}"
        out.note = "Shown to the person with the reason and the models they can pick. No silent swap."
        return out
    if resolution.refused:
        out.step(NO, "Start", resolution.refusal_detail)
        out.state, out.title, out.note = "needs_configuration", "Needs configuration", resolution.refusal_detail
        return out
    current = snapshot.model(resolution.start)
    out.step(OK, "Start", f"{SOURCE_LABELS.get(resolution.source, resolution.source)}: {current.display_name}.")

    chain = [snapshot.model(key) for key in resolution.chain]

    if first_fails:
        if snapshot.fallback == "stop":
            out.step(NO, "Fallback", f'{current.display_name} timed out. Fallback is set to "Stop with an error".')
            out.state, out.title = "error", f"Error · {current.display_name} timed out"
            out.note = "Visible error. No other model answered."
            return out
        following = [model for model in chain if model is not current]
        skipped = [snapshot.model(key) for key in snapshot.order if snapshot.model(key) not in candidates]
        if not following:
            out.step(NO, "Fallback", f"{current.display_name} timed out. No other allowed and cleared model is left.")
            out.state, out.title = "error", "Error · no allowed model left"
            return out
        skipped_text = f" Skipped (not allowed or not cleared): {_names([m for m in skipped if m])}." if skipped else ""
        out.step(MID, "Fallback", f"{current.display_name} timed out. Next allowed model in the platform order: "
                                  f"{following[0].display_name}.{skipped_text}")
        out.note = f"Fell back from {current.display_name} (timeout)."
        current = following[0]
    out.title = f"Answered by {current.display_name}"
    if not out.note:
        out.note = "Shown in the answer header."
    return out


async def explain_turn(
    db: AsyncSession,
    *,
    workspace_id: str,
    person_choice: str = "",
    agent_pin: str = "",
    first_fails: bool = False,
) -> dict[str, Any]:
    project = await db.get(Project, workspace_id)
    if project is None:
        raise LookupError("workspace_not_found")
    snapshot = await load_snapshot(db)
    scope = await load_scope(db, workspace_id=workspace_id)
    explanation = explain_resolution(
        snapshot, scope, workspace_name=project.name,
        first_fails=first_fails, request=ModelRequest(person_choice=person_choice, agent_pin=agent_pin),
    )
    return explanation.payload()


async def explain_options(db: AsyncSession) -> dict[str, Any]:
    projects = (
        await db.execute(select(Project.id, Project.name, Project.config).where(Project.is_active.is_(True))
                         .order_by(Project.name))
    ).all()
    enabled = select(LLMModel).where(LLMModel.is_active.is_(True)).order_by(LLMModel.display_name)
    rows = (await db.execute(enabled)).scalars()
    return {
        "workspaces": [
            {"id": project_id, "name": name,
             "data_class": str(((config or {}).get("data_policy") or {}).get("classification") or "")}
            for project_id, name, config in projects
        ],
        "models": [
            {"key": row.catalog_key, "name": row.display_name or row.model_id} for row in rows if row.catalog_key
        ],
    }


__all__ = ["explain_options", "explain_resolution", "explain_turn"]
