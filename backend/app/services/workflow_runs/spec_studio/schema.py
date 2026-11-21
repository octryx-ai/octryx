"""The Spec Studio artefact (phase output ``spec_studio``): normalised record plus the problems that refuse it.

The record is data the Studio renders and the platform reasons about, never free text: the live mock is built from
``design`` tokens and ``screens`` blocks, the questions are buttons, the rules carry worked examples. A refused
proposal lists every problem at once, so the agent fixes it in one go. Content is never cut (no artificial
limits); only the shape is checked.
"""

from __future__ import annotations

import re
from typing import Any

MODES = ("new", "feature")
TARGETS = ("web", "flutter")
COLOR_KEYS = ("bg", "surface", "text", "muted", "accent", "ok", "warn")
OPTIONAL_COLOR_KEYS = ("error",)
ZERO_CONFIG = ("yes", "no")
TONES = ("neutral", "ok", "warn", "error", "accent")
# The mock's building blocks. Each has the fields the renderer reads; ``blocks`` nests (card, row).
BLOCKS: dict[str, tuple[str, ...]] = {
    "eyebrow": ("text",), "title": ("text",), "text": ("text",), "muted": ("text",),
    "card": ("title", "blocks"), "row": ("blocks",),
    "item": ("title", "meta", "badge", "badge_tone", "art", "icon"),
    "button": ("text", "variant", "go"), "field": ("label", "value", "suffix"),
    "chips": ("items",), "banner": ("text", "tone", "action"), "progress": ("value", "label"),
    "big": ("text", "sub"), "kpis": ("items",), "empty": ("icon", "title", "text", "action"),
    "image": ("label", "icon"),
}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _t(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _texts(value: Any) -> list[str]:
    return [_t(item) for item in _list(value) if _t(item)]


def _palette(raw: Any, where: str, problems: list[str]) -> dict[str, str]:
    raw = _dict(raw)
    palette: dict[str, str] = {}
    for key in (*COLOR_KEYS, *OPTIONAL_COLOR_KEYS):
        value = _t(raw.get(key))
        if not value and key in OPTIONAL_COLOR_KEYS:
            continue
        if not _HEX.match(value):
            problems.append(f"{where}.{key}: a colour as #RRGGBB")
            continue
        palette[key] = value.upper()
    return palette


def _direction(raw: Any, index: int, problems: list[str]) -> dict[str, Any]:
    raw = _dict(raw)
    ident = _t(raw.get("id")) or f"d{index}"
    where = f"design.directions[{ident}]"
    fonts = _dict(raw.get("fonts"))
    radius = raw.get("radius")
    if not isinstance(radius, int | float) or radius < 0:
        problems.append(f"{where}.radius: corner radius in px (0 or more)")
        radius = 8
    direction = {"id": ident, "name": _t(raw.get("name")) or ident, "hint": _t(raw.get("hint")),
                 "light": _palette(raw.get("light"), f"{where}.light", problems),
                 "dark": _palette(raw.get("dark"), f"{where}.dark", problems),
                 "fonts": {"head": _t(fonts.get("head")) or "Georgia, serif",
                           "body": _t(fonts.get("body")) or "system-ui, sans-serif",
                           "mono": _t(fonts.get("mono")) or "ui-monospace, monospace"},
                 "radius": int(radius)}
    return direction


def _design(raw: Any, mode: str, problems: list[str]) -> dict[str, Any]:
    raw = _dict(raw)
    directions = [_direction(item, index, problems) for index, item in enumerate(_list(raw.get("directions")), 1)]
    if not directions and mode == "new":
        problems.append("design.directions: at least one design direction with light and dark tokens")
    ids = [item["id"] for item in directions]
    proposed = _t(raw.get("proposed")) or (ids[0] if ids else "")
    if directions and proposed not in ids:
        problems.append(f"design.proposed: one of {', '.join(ids)}")
    return {"proposed": proposed, "directions": directions}


def _block(raw: Any, where: str, problems: list[str]) -> dict[str, Any] | None:
    raw = _dict(raw)
    kind = _t(raw.get("type"))
    if kind not in BLOCKS:
        problems.append(f"{where}.type: one of {', '.join(BLOCKS)}")
        return None
    block: dict[str, Any] = {"type": kind}
    for field in BLOCKS[kind]:
        value = raw.get(field)
        if field == "blocks":
            block["blocks"] = _blocks(value, f"{where}.blocks", problems)
        elif field == "items":
            block["items"] = [{"text": _t(_dict(item).get("text") or item), "label": _t(_dict(item).get("label")),
                               "value": _t(_dict(item).get("value")), "tone": _t(_dict(item).get("tone"))}
                              for item in _list(value)]
        elif field == "value" and kind == "progress":
            block["value"] = max(0.0, min(1.0, float(value))) if isinstance(value, int | float) else 0.0
        elif _t(value):
            block[field] = _t(value)
    return block


def _blocks(raw: Any, where: str, problems: list[str]) -> list[dict[str, Any]]:
    return [block for index, item in enumerate(_list(raw), 1)
            if (block := _block(item, f"{where}[{index}]", problems)) is not None]


def _screen(raw: Any, index: int, problems: list[str]) -> dict[str, Any]:
    raw = _dict(raw)
    ident = _t(raw.get("id")) or f"s{index}"
    where = f"screens[{ident}]"
    return {"id": ident, "name": _t(raw.get("name")) or ident, "route": _t(raw.get("route")),
            "nav": _t(raw.get("nav")) or ident, "focus": raw.get("focus") is True,
            "filled": _blocks(raw.get("filled"), f"{where}.filled", problems),
            "empty": _blocks(raw.get("empty"), f"{where}.empty", problems),
            "empty_not_applicable": _t(raw.get("empty_not_applicable")),
            "next_step": _t(raw.get("next_step")), "note": _t(raw.get("note"))}


def _question(raw: Any, index: int, problems: list[str]) -> dict[str, Any]:
    raw = _dict(raw)
    ident = _t(raw.get("id")) or f"q{index}"
    options = [{"value": _t(_dict(o).get("value")), "label": _t(_dict(o).get("label")),
                "detail": _t(_dict(o).get("detail"))} for o in _list(raw.get("options"))]
    options = [o for o in options if o["value"] and o["label"]]
    proposal = _t(raw.get("proposal"))
    if len(options) < 2:
        problems.append(f"questions[{ident}].options: at least two options, each with value and label")
    elif proposal not in [o["value"] for o in options]:
        problems.append(f"questions[{ident}].proposal: the value of the proposed option")
    if not _t(raw.get("question")):
        problems.append(f"questions[{ident}].question: the question")
    return {"id": ident, "question": _t(raw.get("question")), "why": _t(raw.get("why")),
            "identifier": _t(raw.get("identifier")), "options": options, "proposal": proposal,
            "affects": _texts(raw.get("affects"))}


def _example(raw: Any) -> dict[str, Any]:
    raw = _dict(raw)
    scenario = raw.get("scenario") if isinstance(raw.get("scenario"), dict) else None
    return {"given": _t(raw.get("given")), "expect": _t(raw.get("expect")), "realistic": raw.get("realistic") is True,
            **({"scenario": scenario} if scenario else {})}


def _rule(raw: Any, index: int) -> dict[str, Any]:
    raw = _dict(raw)
    params = [{"id": _t(_dict(p).get("id")), "label": _t(_dict(p).get("label")) or _t(_dict(p).get("id")),
               "value": _t(_dict(p).get("value")), "unit": _t(_dict(p).get("unit"))}
              for p in _list(raw.get("params")) if _t(_dict(p).get("id"))]
    return {"id": _t(raw.get("id")) or f"R{index}", "title": _t(raw.get("title")), "text": _t(raw.get("text")),
            "identifier": _t(raw.get("identifier")), "numeric": raw.get("numeric") is True, "params": params,
            "examples": [_example(item) for item in _list(raw.get("examples"))]}


def _entries(raw: Any, prefix: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    entries = []
    for index, item in enumerate(_list(raw), 1):
        item = _dict(item)
        entries.append({"id": _t(item.get("id")) or f"{prefix}{index}", **{f: _t(item.get(f)) for f in fields}})
    return entries


def _unique(items: list[dict[str, Any]], what: str, problems: list[str]) -> None:
    ids = [item["id"] for item in items]
    for ident in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"{what}: the id {ident} is used twice")
    for ident in ids:
        if not _ID.match(ident):
            problems.append(f"{what}: id {ident!r} uses letters, digits, '_', '.' or '-' only")


def validate_spec_studio(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The normalised artefact and the problems that refuse it (shape only; the gates judge the content)."""
    problems: list[str] = []
    mode = _t(raw.get("spec_mode") or raw.get("mode")) or "new"  # tools say spec_mode: no MCP tool has "mode"
    target = _t(raw.get("target")) or "web"
    if mode not in MODES:
        problems.append(f"spec_mode: one of {', '.join(MODES)}")
    if target not in TARGETS:
        problems.append(f"target: one of {', '.join(TARGETS)}")
    screens = [_screen(item, index, problems) for index, item in enumerate(_list(raw.get("screens")), 1)]
    if not screens:
        problems.append("screens: at least one screen with its filled and empty state")
    record = {
        "mode": mode, "target": target, "title": _t(raw.get("title")), "summary": _t(raw.get("summary")),
        "spec_path": _t(raw.get("spec_path")) or "SPEC.md", "language": _t(raw.get("language")) or "en",
        "out_of_scope": _texts(raw.get("out_of_scope")),
        "stories": [{"title": _t(_dict(s).get("title")), "summary": _t(_dict(s).get("summary"))}
                    for s in _list(raw.get("stories")) if _t(_dict(s).get("title"))],
        "design": _design(raw.get("design"), mode, problems),
        "nav": [{"id": _t(_dict(n).get("id")), "label": _t(_dict(n).get("label")), "icon": _t(_dict(n).get("icon")),
                 "phone": _dict(n).get("phone") is not False}
                for n in _list(raw.get("nav")) if _t(_dict(n).get("id"))],
        "screens": screens,
        "questions": [_question(item, index, problems) for index, item in enumerate(_list(raw.get("questions")), 1)],
        "rules": [_rule(item, index) for index, item in enumerate(_list(raw.get("rules")), 1)],
        "acceptance": _entries(raw.get("acceptance"), "AC-", ("text",)),
        "requirements": _entries(raw.get("requirements"), "P", ("text", "zero_config", "how")),
        "glossary": [{"term": _t(_dict(g).get("term")), "translation": _t(_dict(g).get("translation")),
                      "avoid": _texts(_dict(g).get("avoid"))} for g in _list(raw.get("glossary"))
                     if _t(_dict(g).get("term"))],
        "conditions": [{"word": _t(_dict(c).get("word")), "definition": _t(_dict(c).get("definition"))}
                       for c in _list(raw.get("conditions")) if _t(_dict(c).get("word"))],
        "flow": {key: _t(_dict(raw.get("flow")).get(key)) for key in ("progressive_disclosure", "carry_over")},
    }
    if not record["title"]:
        problems.append("title: the product or feature name")
    for key in ("screens", "questions", "rules", "acceptance", "requirements"):
        _unique(record[key], key, problems)
    return record, problems


__all__ = ["BLOCKS", "COLOR_KEYS", "MODES", "TARGETS", "TONES", "ZERO_CONFIG", "validate_spec_studio"]
