"""Which app a run works on when its start named none."""

from __future__ import annotations

from typing import Any

from .run_app import APP_KEY, APP_SOURCE_INTAKE, app_context, record_apps

FIELD = "app"


def _deepest(paths: list[str]) -> list[str]:
    return [path for path in paths if not any(other != path and other.startswith(f"{path}/") for other in paths)]


def _named(paths: list[str], names: list[str]) -> list[str]:
    wanted = {name.strip().strip("/").lower() for name in names if name.strip()}
    return [path for path in paths if path.lower() in wanted or path.rsplit("/", 1)[-1].lower() in wanted]


def _in_text(paths: list[str], text: str) -> list[str]:
    lowered = text.lower()
    return _deepest([path for path in paths if path != "." and path.lower() in lowered])


async def choose_app(db: Any, run: Any, *, components: list[Any], text: str) -> dict[str, Any]:
    if dict(dict(run.context or {}).get(APP_KEY) or {}).get("source"):
        return {}
    paths = sorted({str(app["path"]) for app in await record_apps(db, run)})
    if not paths:
        return {}
    for found in (_named(paths, [str(name) for name in components]), _in_text(paths, text)):
        if len(found) == 1:
            run.context = {**dict(run.context or {}), APP_KEY: app_context(found[0], APP_SOURCE_INTAKE)}
            return {}
    if len(paths) == 1:
        run.context = {**dict(run.context or {}), APP_KEY: app_context(paths[0], APP_SOURCE_INTAKE)}
        return {}
    return {"options": paths}


async def paused_for_app(db: Any, run: Any, node: Any) -> bool:
    from ....models.runtime.secure_work import WorkItem
    from ..limits import pause_run
    from ..run_texts import run_text
    from ..states import PAUSE_NEEDS_INPUT

    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    text = f"{item.title}\n{item.description or ''}" if item is not None else str(run.title or "")
    answers = [str(entry.get("text") or "") for entry in dict(run.context or {}).get("po_answers") or []
               if isinstance(entry, dict)]
    choice = await choose_app(db, run, components=list(getattr(item, "components_json", None) or []),
                              text="\n".join([text, *answers]))
    if not choice.get("options"):
        return False
    await pause_run(db, run, reason=PAUSE_NEEDS_INPUT, actor_id=None, detail={
        "message": run_text("pause.app_choice", options=", ".join(choice["options"])), "field": FIELD,
        "app_options": choice["options"], "resume": {"kind": "restart", "node_id": node.id}})
    return True


__all__ = ["FIELD", "choose_app", "paused_for_app"]
