"""The product owner's work in the Studio: one change at a time, each an audited run event (who, when, what)."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from ....time_utils import utc_now
from .design import THEMES
from .schema import COLOR_KEYS

STUDIO_KEY = "spec_studio"
EVENT_CHANGED = "spec_studio_changed"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DEVICES = ("desktop", "phone")
VERDICTS = ("ok", "change")


class StudioChangeError(ValueError):
    pass


def studio(run: Any) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(STUDIO_KEY) or {})


def current_state(run: Any) -> dict[str, Any]:
    return dict(studio(run).get("state") or {})


def _store(run: Any, state: dict[str, Any]) -> None:
    run.context = {**dict(run.context or {}), STUDIO_KEY: {**studio(run), "state": state}}


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _answer(artefact: dict[str, Any], state: dict[str, Any], change: dict[str, Any]) -> tuple[str, Any, Any]:
    question = next((q for q in artefact["questions"] if q["id"] == _text(change.get("question"))), None)
    if question is None:
        raise StudioChangeError("Unknown question.")
    answers = dict(state.get("answers") or {})
    before = answers.get(question["id"])
    other = _text(change.get("other"))
    value = _text(change.get("value"))
    if other:
        after: dict[str, str] | None = {"other": other}
    elif value in [o["value"] for o in question["options"]]:
        after = None if value == question["proposal"] else {"value": value}
    else:
        raise StudioChangeError("Pick one of the options or write your own answer.")
    answers[question["id"]] = after
    state["answers"] = {k: v for k, v in answers.items() if v}
    return f"question:{question['id']}", before, after


def _design(artefact: dict[str, Any], state: dict[str, Any], change: dict[str, Any],
            corporate: dict[str, Any] | None = None) -> tuple[str, Any, Any]:
    from .corporate_link import check_lock

    if "direction" in change:
        check_lock(corporate, state, "direction")
        ids = [d["id"] for d in artefact["design"]["directions"]]
        ids += [corporate["direction"]["id"]] if corporate else []
        if _text(change["direction"]) not in ids:
            raise StudioChangeError("Unknown design direction.")
        before, state["direction"] = state.get("direction"), _text(change["direction"])
        state["tokens"] = {}
        return "design:direction", before, state["direction"]
    if "radius" in change:
        radius = change["radius"]
        if not isinstance(radius, int) or radius < 0:
            raise StudioChangeError("The radius is a whole number of px, 0 or more.")
        check_lock(corporate, state, "radius")
        before, state["radius"] = state.get("radius"), radius
        return "design:radius", before, radius
    if "font" in change:
        fonts = change["font"] if isinstance(change["font"], dict) else {}
        clean = {k: _text(v) for k, v in fonts.items() if k in ("head", "body", "mono") and _text(v)}
        for key in clean:
            if clean[key] != dict(state.get("fonts") or {}).get(key):
                check_lock(corporate, state, f"fonts.{key}")
        before, state["fonts"] = state.get("fonts"), clean
        return "design:font", before, clean
    theme, key, value = _text(change.get("theme")), _text(change.get("key")), _text(change.get("value")).upper()
    if theme not in THEMES or key not in (*COLOR_KEYS, "error") or not _HEX.match(value):
        raise StudioChangeError("A colour needs its theme (light/dark), token and a value #RRGGBB.")
    check_lock(corporate, state, f"{theme}.{key}")
    tokens = {t: dict(v) for t, v in dict(state.get("tokens") or {}).items()}
    before = tokens.get(theme, {}).get(key)
    tokens.setdefault(theme, {})[key] = value
    state["tokens"] = tokens
    return f"token:{theme}.{key}", before, value


def _reason(state: dict[str, Any], change: dict[str, Any]) -> tuple[str, Any, Any]:
    path, text = _text(change.get("path")), _text(change.get("text"))
    if not path or len(text) > 1000:
        raise StudioChangeError("A reason needs the deviation's path and at most 1000 characters.")
    reasons = dict(state.get("reasons") or {})
    before = reasons.get(path)
    reasons[path] = text
    state["reasons"] = {k: v for k, v in reasons.items() if v}
    return f"reason:{path}", before, text or None


def _comment(artefact: dict[str, Any], state: dict[str, Any], change: dict[str, Any], by: str,
             base_screens: tuple[str, ...]) -> tuple[str, Any, Any]:
    comments = [dict(c) for c in state.get("comments") or []]
    op = _text(change.get("op"))
    if op == "comment.add":
        screen = _text(change.get("screen"))
        if screen not in [*(s["id"] for s in artefact["screens"]), *base_screens]:
            raise StudioChangeError("Unknown screen.")
        comment = {"id": uuid4().hex[:8], "screen": screen,
                   "device": _text(change.get("device")) if _text(change.get("device")) in DEVICES else "desktop",
                   "theme": _text(change.get("theme")) or "light", "data": _text(change.get("data")) or "filled",
                   "x": round(float(change.get("x") or 0)), "y": round(float(change.get("y") or 0)),
                   "element": _text(change.get("element")), "path": _text(change.get("path")),
                   "text": _text(change.get("text")), "by": by, "at": utc_now().isoformat()}
        comments.append(comment)
        state["comments"] = comments
        return f"comment:{comment['id']}", None, comment
    target = next((c for c in comments if c["id"] == _text(change.get("id"))), None)
    if target is None:
        raise StudioChangeError("Unknown comment.")
    if op == "comment.remove":
        state["comments"] = [c for c in comments if c is not target]
        return f"comment:{target['id']}", target, None
    before, target["text"] = target["text"], _text(change.get("text"))
    state["comments"] = comments
    return f"comment:{target['id']}", before, target["text"]


def _rule(artefact: dict[str, Any], state: dict[str, Any], change: dict[str, Any]) -> tuple[str, Any, Any]:
    rule = next((r for r in artefact["rules"] if r["id"] == _text(change.get("rule"))), None)
    param = next((p for p in (rule or {}).get("params") or [] if p["id"] == _text(change.get("param"))), None)
    if rule is None or param is None:
        raise StudioChangeError("Unknown rule value.")
    rules = {k: dict(v) for k, v in dict(state.get("rules") or {}).items()}
    values = rules.setdefault(rule["id"], {})
    before = values.get(param["id"], param["value"])
    value = _text(change.get("value"))
    if value == param["value"]:
        values.pop(param["id"], None)
    else:
        values[param["id"]] = value
    state["rules"] = {k: v for k, v in rules.items() if v}
    return f"rule:{rule['id']}.{param['id']}", before, value


def _acceptance(artefact: dict[str, Any], state: dict[str, Any], change: dict[str, Any]) -> tuple[str, Any, Any]:
    ident = _text(change.get("id"))
    if ident not in [a["id"] for a in artefact["acceptance"]] or _text(change.get("verdict")) not in VERDICTS:
        raise StudioChangeError("A criterion is marked ok or change.")
    verdicts = dict(state.get("acceptance") or {})
    before = verdicts.get(ident)
    after = {"verdict": _text(change["verdict"]), "note": _text(change.get("note"))}
    verdicts[ident] = after
    state["acceptance"] = {k: v for k, v in verdicts.items() if v.get("verdict") == "change"}
    return f"acceptance:{ident}", before, after


def apply_change(run: Any, artefact: dict[str, Any], change: dict[str, Any], *, by: str,
                 base_screens: tuple[str, ...] = (), frozen: bool = False,
                 corporate: dict[str, Any] | None = None) -> dict[str, Any]:
    if frozen:
        raise StudioChangeError("This version is approved and frozen.")
    state = current_state(run)
    op = _text(change.get("op"))
    if op == "answer":
        target, before, after = _answer(artefact, state, change)
    elif op == "design":
        target, before, after = _design(artefact, state, change, corporate)
    elif op == "reason":
        target, before, after = _reason(state, change)
    elif op.startswith("comment."):
        target, before, after = _comment(artefact, state, change, by, base_screens)
    elif op == "rule":
        target, before, after = _rule(artefact, state, change)
    elif op == "acceptance":
        target, before, after = _acceptance(artefact, state, change)
    else:
        raise StudioChangeError("Unknown change.")
    _store(run, state)
    return {"op": op, "target": target, "from": before, "to": after, "by": by}


__all__ = ["DEVICES", "EVENT_CHANGED", "STUDIO_KEY", "StudioChangeError", "apply_change", "current_state", "studio"]
