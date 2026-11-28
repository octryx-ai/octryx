"""The Studio on a run: what the product owner sees, their changes, approval (freeze + writeback) and revision."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ....time_utils import utc_now
from ..phase_outputs import recorded_output
from .corporate_link import deviations, snapshot
from .design import contrast_report, effective_design
from .gates import needs_revision, open_points
from .state import EVENT_CHANGED, STUDIO_KEY, apply_change, current_state, studio
from .writeback import approved_app, decision_lines, decisions_block, merge_spec, read_base, tokens_block, write_files

KIND = "spec_studio"
EVENT_APPROVED = "spec_studio_approved"
EVENT_REVISION = "spec_studio_revision_requested"
STUDIO_PATH = "/chat"
VIEWPORTS = {"desktop": {"width": 1280, "height": 800}, "phone": {"width": 390, "height": 844}}


def artefact_of(run: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
    envelope = recorded_output(run, KIND)
    if not envelope or not isinstance(envelope.get("record"), dict):
        return None
    return envelope["record"], envelope


def base_of(run: Any, artefact: dict[str, Any]) -> dict[str, Any] | None:
    if artefact.get("mode") != "feature":
        return None
    local_path = str(dict(run.context or {}).get("local_path") or "")
    return read_base(local_path, artefact.get("spec_path") or "SPEC.md") if local_path else None


def frozen(run: Any, envelope: dict[str, Any]) -> bool:
    approved = list(studio(run).get("approved") or [])
    return bool(approved) and approved[-1].get("artefact_hash") == envelope.get("hash")


def evaluate(run: Any) -> dict[str, Any] | None:
    found = artefact_of(run)
    if found is None:
        return None
    artefact, envelope = found
    base = base_of(run, artefact)
    state = current_state(run)
    corporate = snapshot(run)
    design = effective_design(artefact, state, base, corporate)
    found = deviations(design, corporate, state)
    points = open_points(artefact, state, design, found)
    return {"artefact": artefact, "version": envelope.get("version"), "hash": envelope.get("hash"),
            "base": base, "state": state, "design": design, "contrast": contrast_report(design),
            "corporate": _corporate_view(corporate), "deviations": found,
            "open_points": points, "needs_revision": needs_revision(points), "frozen": frozen(run, envelope),
            "approved": list(studio(run).get("approved") or []), "baseline": list(studio(run).get("baseline") or [])}


def _corporate_view(corporate: dict[str, Any] | None) -> dict[str, Any] | None:
    if corporate is None:
        return None
    extra = dict(corporate["direction"].get("corporate") or {})
    direction = {key: value for key, value in corporate["direction"].items() if key != "corporate"}
    return {key: corporate[key] for key in ("profile_id", "profile_name", "source", "locks", "hash")} | {
        "sources": extra.get("sources") or {}, "logo": extra.get("logo"), "icons": extra.get("icons") or {},
        "direction": direction}


def base_screen_ids(view: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(s.get("id")) for s in dict(view.get("base") or {}).get("screens") or [] if s.get("id"))


def change(db: Any, run: Any, payload: dict[str, Any], *, user: Any) -> dict[str, Any]:
    from ..records import record_event

    view = evaluate(run)
    if view is None:
        from .state import StudioChangeError

        raise StudioChangeError("This run has no Spec Studio yet.")
    detail = apply_change(run, view["artefact"], payload, by=str(user.id),
                          base_screens=base_screen_ids(view), frozen=view["frozen"], corporate=snapshot(run))
    record_event(db, run, EVENT_CHANGED, node_id=run.current_node_id, detail=detail)
    return detail


def render_url(run_id: str, screen: str, device: str, theme: str, version: int, data: str = "filled") -> str:
    query = {"area": "work", "work_view": "spec_studio", "run_id": run_id, "render": screen, "device": device,
             "theme": theme, "data": data, "version": version}
    return f"{STUDIO_PATH}?{urlencode(query)}"


def baseline(run_id: str, artefact: dict[str, Any], version: int) -> list[dict[str, Any]]:
    devices = ("phone", "desktop")
    return [{"name": f"{screen['id']}-{VIEWPORTS[device]['width']}-{theme}", "screen": screen["id"],
             "viewport": dict(VIEWPORTS[device]), "theme": theme, "data": "filled",
             "url": render_url(run_id, screen["id"], device, theme, version), "path": screen.get("route") or "/"}
            for screen in artefact["screens"] for device in devices for theme in ("light", "dark")]


def scenarios(artefact: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for rule in artefact["rules"]:
        for index, example in enumerate(rule["examples"], 1):
            scenario = example.get("scenario")
            if isinstance(scenario, dict) and scenario.get("steps"):
                found.append({"part": "feature", "title": scenario.get("title") or f"{rule['id']} example {index}",
                              "covers": [rule["id"]], **{k: v for k, v in scenario.items() if k != "title"}})
    return found


def _who(user: Any) -> str:
    if user is None:
        return "the platform (auto-accepted)"
    return str(getattr(user, "display_name", "") or getattr(user, "username", "") or user.id)


async def freeze(db: Any, run: Any, *, user: Any, how: str) -> dict[str, Any] | None:
    from ..records import record_event

    view = evaluate(run)
    if view is None or view["frozen"]:
        return None
    artefact, state, design = view["artefact"], view["state"], view["design"]
    number = len(view["approved"]) + 1
    when = utc_now()
    entry = {"version": number, "artefact_version": view["version"], "artefact_hash": view["hash"],
             "state": state, "design": design, "approved_by": getattr(user, "id", None), "who": _who(user),
             "at": when.isoformat(), "how": how, "open_points": view["open_points"], "files": [],
             "deviations": view["deviations"]}
    if view["corporate"]:
        entry["corporate"] = {"profile_id": view["corporate"]["profile_id"], "hash": view["corporate"]["hash"]}
    names = {s["id"]: s["name"] for s in [*dict(view["base"] or {}).get("screens", []), *artefact["screens"]]}
    lines = decision_lines(artefact, state, design, names, view["deviations"])
    decisions = decisions_block(str(run.id), number, entry["who"], when.strftime("%Y-%m-%d %H:%M UTC"), lines)
    tokens = tokens_block(design, number) if artefact["design"]["directions"] or state.get("tokens") else None
    entry["decisions"] = lines
    local_path = str(dict(run.context or {}).get("local_path") or "")
    if local_path:
        entry["files"] = await _write(run, local_path, artefact, view, design, entry, decisions, tokens)
    context = dict(run.context or {})
    record = studio(run)
    record.update(approved=[*view["approved"], entry], baseline=baseline(str(run.id), artefact, number),
                  scenarios=scenarios(artefact))
    run.context = {**context, STUDIO_KEY: record}
    record_event(db, run, EVENT_APPROVED, node_id=run.current_node_id,
                 detail={"version": number, "how": how, "by": entry["approved_by"], "decisions": len(lines),
                         "open_points": len(view["open_points"]), "files": entry["files"]})
    return entry


async def _write(run: Any, local_path: str, artefact: dict[str, Any], view: dict[str, Any], design: dict[str, Any],
                 entry: dict[str, Any], decisions: str, tokens: str | None) -> list[str]:
    from .. import safe_git

    review = dict(dict(run.context or {}).get("review") or {})
    before = await safe_git.staged_tree(local_path) if review.get("tree") else ""
    approved = approved_app(artefact, design, view["base"], {k: entry[k] for k in ("version", "who", "at")})
    files = write_files(local_path, artefact.get("spec_path") or "SPEC.md", approved=approved,
                        spec_text_of=lambda old: merge_spec(old, run_id=str(run.id), decisions=decisions,
                                                            tokens=tokens))
    if review.get("tree") and review["tree"] == before:
        # The push sends exactly the reviewed tree (``platform/scm.push``); the Studio's writeback is the one change
        # added after the review, recorded with both trees so it stays visible.
        after = await safe_git.staged_tree(local_path)
        run.context = {**dict(run.context or {}), "review": {**review, "tree": after, "studio_writeback": {
            "reviewed_tree": before, "tree": after, "files": files}}}
    return files


def revision_answer(view: dict[str, Any]) -> str:
    artefact, state = view["artefact"], view["state"]
    names = {s["id"]: s["name"] for s in [*dict(view["base"] or {}).get("screens", []), *artefact["screens"]]}
    lines = ["The product owner reviewed the spec in the Spec Studio. Carry out every point below in SPEC.md and "
             "in a new submit_spec_studio, and list each under Decisions:", ""]
    lines += [f"- {line}" for line in decision_lines(artefact, state, view["design"], names)]
    for rule_id, values in sorted(dict(state.get("rules") or {}).items()):
        for param, value in sorted(dict(values).items()):
            lines.append(f"- Rule {rule_id}: set `{param}` to {value} and recompute its worked examples.")
    for ident, verdict in sorted(dict(state.get("acceptance") or {}).items()):
        lines.append(f"- {ident} must change: {dict(verdict).get('note') or 'rewrite it'}.")
    for point in view["open_points"]:
        if "send the spec to revision" not in point["text"]:
            lines.append(f"- Open point: {point['text']}")
    return "\n".join(lines)


def note_revision(db: Any, run: Any, user: Any) -> None:
    from ..records import record_event

    record_event(db, run, EVENT_REVISION, node_id=run.current_node_id, detail={"by": getattr(user, "id", None)})


__all__ = ["EVENT_APPROVED", "EVENT_REVISION", "KIND", "artefact_of", "baseline", "change", "evaluate", "freeze",
           "render_url", "revision_answer", "scenarios"]
