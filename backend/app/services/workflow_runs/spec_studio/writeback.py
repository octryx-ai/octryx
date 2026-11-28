"""Write the approved Studio back into the repository: decisions and tokens into SPEC.md, the approved mock next to
it."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .design import THEMES
from .schema import COLOR_KEYS

APPROVED_FILE = "spec-studio.json"
_DECISIONS = re.compile(r"^##\s+(?:\d+[.)]?\s+)?(?:Decisions|Entscheidungen)\b.*$", re.MULTILINE | re.IGNORECASE)
_NEXT_SECTION = re.compile(r"^##\s", re.MULTILINE)
TOKENS_OPEN, TOKENS_CLOSE = "<!-- spec-studio:tokens -->", "<!-- /spec-studio:tokens -->"


def _option_label(question: dict[str, Any], value: str) -> str:
    return next((o["label"] for o in question["options"] if o["value"] == value), value)


def decision_lines(artefact: dict[str, Any], state: dict[str, Any], design: dict[str, Any],
                   screen_names: dict[str, str], deviations: list[dict[str, Any]] = ()) -> list[str]:
    lines: list[str] = []
    proposed = artefact["design"]["proposed"]
    reasons = {d["path"]: d for d in deviations}
    if design.get("direction") == "corporate":
        lines.append(f"`design.direction`: {design['name']} (the company's Corporate Identity).")
    elif "direction" in reasons:
        lines.append(f"`design.direction`: {design['name']} instead of {reasons['direction']['corporate']}, "
                     f"because: {reasons['direction']['reason'] or 'no reason given'}.")
    elif state.get("direction") and state["direction"] != proposed:
        lines.append(f"`design.direction`: {design['name']} (proposal was {proposed}).")
    elif artefact["design"]["directions"]:
        lines.append(f"`design.direction`: {design['name']} (proposal accepted).")
    for theme, tokens in sorted(dict(state.get("tokens") or {}).items()):
        for key, value in sorted(dict(tokens).items()):
            deviation = reasons.get(f"{theme}.{key}")
            why = (f" Differs from Corporate ({deviation['corporate']}), because: {deviation['reason'] or 'no reason'}."
                   if deviation else "")
            lines.append(f"`{key}` ({theme}): {value} (chosen in the Studio).{why}")
    if isinstance(state.get("radius"), int):
        lines.append(f"`radius`: {state['radius']} px (chosen in the Studio).")
    for key, value in sorted(dict(state.get("fonts") or {}).items()):
        deviation = reasons.get(f"fonts.{key}")
        why = f" Differs from Corporate, because: {deviation['reason'] or 'no reason'}." if deviation else ""
        lines.append(f"`font.{key}`: {value} (chosen in the Studio).{why}")
    answers = dict(state.get("answers") or {})
    for question in artefact["questions"]:
        name = f"`{question['identifier']}`" if question["identifier"] else question["id"]
        answer = dict(answers.get(question["id"]) or {})
        if answer.get("other"):
            choice = f"{answer['other']} (own answer; proposal was {_option_label(question, question['proposal'])})"
        elif answer.get("value"):
            choice = (f"{_option_label(question, answer['value'])} (proposal was "
                      f"{_option_label(question, question['proposal'])})")
        else:
            choice = f"{_option_label(question, question['proposal'])} (proposal accepted)"
        lines.append(f"{name} – {question['question']} → {choice}.")
    for comment in state.get("comments") or []:
        if not str(comment.get("text") or "").strip():
            continue
        where = screen_names.get(comment["screen"], comment["screen"])
        view = "390 px" if comment.get("device") == "phone" else "1280 px"
        element = f" at “{comment['element']}”" if comment.get("element") else ""
        path = f" (`{comment['path']}`)" if comment.get("path") else ""
        lines.append(f"Comment on {where}, {view}{element}{path}: {comment['text'].strip()}")
    return lines


def decisions_block(run_id: str, version: int, who: str, when: str, lines: list[str]) -> str:
    body = "\n".join(f"- SS{index}. {line}" for index, line in enumerate(lines, 1)) or "- No change to the draft."
    return (f"<!-- spec-studio:decisions run={run_id} -->\n### Spec Studio decisions (v{version}, approved by "
            f"{who}, {when})\n\n{body}\n<!-- /spec-studio:decisions run={run_id} -->")


def tokens_block(design: dict[str, Any], version: int) -> str:
    rows = [f"| `{key}` | {design['light'].get(key, '')} | {design['dark'].get(key, '')} |"
            for key in (*COLOR_KEYS, "error") if any(design[t].get(key) for t in THEMES)]
    fonts = design.get("fonts") or {}
    return "\n".join([TOKENS_OPEN, f"### Design tokens (approved in the Spec Studio, v{version}, exact)", "",
                      f"Direction: {design['name']}. Fonts: headings `{fonts.get('head', '')}`, text "
                      f"`{fonts.get('body', '')}`, numbers `{fonts.get('mono', '')}`. Radius `{design['radius']}` px.",
                      "", "| Token | Light | Dark |", "|---|---|---|", *rows, TOKENS_CLOSE])


def _replace_marked(text: str, opening: str, closing: str, block: str) -> str | None:
    start = text.find(opening)
    end = text.find(closing, start) if start >= 0 else -1
    if start < 0 or end < 0:
        return None
    return text[:start] + block + text[end + len(closing):]


def merge_spec(text: str, *, run_id: str, decisions: str, tokens: str | None) -> str:
    opening = f"<!-- spec-studio:decisions run={run_id} -->"
    replaced = _replace_marked(text, opening, f"<!-- /spec-studio:decisions run={run_id} -->", decisions)
    if replaced is not None:
        text = replaced
    else:
        heading = _DECISIONS.search(text)
        if heading is None:
            text = text.rstrip() + "\n\n## Decisions\n\n" + decisions + "\n"
        else:
            following = _NEXT_SECTION.search(text, heading.end())
            cut = following.start() if following else len(text)
            text = text[:cut].rstrip() + "\n\n" + decisions + "\n\n" + text[cut:].lstrip("\n")
    if tokens is None:
        return text if text.endswith("\n") else text + "\n"
    replaced = _replace_marked(text, TOKENS_OPEN, TOKENS_CLOSE, tokens)
    if replaced is None:
        heading = _DECISIONS.search(text)
        cut = heading.start() if heading else len(text)
        replaced = text[:cut].rstrip() + "\n\n" + tokens + "\n\n" + text[cut:].lstrip("\n")
    return replaced if replaced.endswith("\n") else replaced + "\n"


def approved_app(artefact: dict[str, Any], design: dict[str, Any], base: dict[str, Any] | None,
                 version: dict[str, Any]) -> dict[str, Any]:
    base = dict(base or {})

    def merged(key: str, ident: str) -> list[dict[str, Any]]:
        mine = {item[ident]: item for item in artefact.get(key) or []}
        return [mine.pop(item[ident], item) for item in base.get(key) or [] if ident in item] + list(mine.values())

    direction = {"id": design["direction"] or "approved", "name": design["name"], "hint": "approved",
                 "light": design["light"], "dark": design["dark"], "fonts": design["fonts"], "radius": design["radius"]}
    return {"format": "octryx.spec-studio/v1", "target": artefact["target"], "title": base.get("title") or
            artefact["title"], "approved": version,
            "design": {"proposed": direction["id"], "directions": [direction]},
            "nav": artefact.get("nav") or base.get("nav") or [], "screens": merged("screens", "id"),
            "glossary": merged("glossary", "term"), "conditions": merged("conditions", "word"),
            "rules": merged("rules", "id"), "acceptance": merged("acceptance", "id")}


def inside(root: Path, relative: str) -> Path | None:
    target = (root / relative).resolve()
    return target if target == root.resolve() or root.resolve() in target.parents else None


def read_base(local_path: str, spec_path: str) -> dict[str, Any] | None:
    root = Path(local_path)
    spec = inside(root, spec_path or "SPEC.md")
    candidate = spec.parent / APPROVED_FILE if spec is not None else None
    try:
        data = json.loads(candidate.read_text(encoding="utf-8")) if candidate and candidate.is_file() else None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_files(local_path: str, spec_path: str, *, spec_text_of, approved: dict[str, Any]) -> list[str]:
    root = Path(local_path)
    spec = inside(root, spec_path or "SPEC.md")
    if spec is None:
        raise ValueError(f"spec path {spec_path!r} leaves the working copy")
    old = spec.read_text(encoding="utf-8") if spec.is_file() else ""
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(spec_text_of(old), encoding="utf-8")
    approved_path = spec.parent / APPROVED_FILE
    approved_path.write_text(json.dumps(approved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return [str(spec.relative_to(root.resolve())), str(approved_path.relative_to(root.resolve()))]


__all__ = ["APPROVED_FILE", "approved_app", "decision_lines", "decisions_block", "inside", "merge_spec",
           "read_base", "tokens_block", "write_files"]
