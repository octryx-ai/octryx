"""Three-way merge of a skill bundle: base = upstream snapshot, ours = published, theirs = new upstream.

Per file:

- unchanged locally (ours == base) → theirs (including an upstream deletion or addition);
- unchanged upstream (theirs == base) → ours;
- both sides identical → that text;
- otherwise a line-based diff3 (the classic merge3 sync-region algorithm, ``difflib`` matching blocks —
  deterministic, no heuristics). Hunks changed on one side merge; overlapping hunks are **conflicts**.

A conflicted file is written with the upstream text in the conflicted places, so the draft stays a valid bundle;
the conflict is listed in the merge report and submitting is refused until every conflict has a resolution:
``upstream`` (take upstream), ``mine`` (keep my lines), ``manual`` (given text) or ``relocate``.

**Relocation**: when upstream removed a conflicted hunk's base lines from the file and exactly one file *new*
upstream contains those base lines verbatim, the conflict offers to apply the local edit in the new place: the base
block in that file is replaced by my lines, and the original place takes upstream.
"""

from __future__ import annotations

import difflib
import hashlib
from typing import Any

from .errors import SkillCatalogError

RESOLUTIONS = ("upstream", "mine", "manual", "relocate")


def _lines(text: str | None) -> list[str]:
    return (text or "").splitlines(keepends=True)


def _sync_regions(base: list[str], ours: list[str], theirs: list[str]) -> list[tuple[int, int, int, int, int, int]]:
    ours_blocks = difflib.SequenceMatcher(None, base, ours, autojunk=False).get_matching_blocks()
    theirs_blocks = difflib.SequenceMatcher(None, base, theirs, autojunk=False).get_matching_blocks()
    regions: list[tuple[int, int, int, int, int, int]] = []
    index_o = index_t = 0
    while index_o < len(ours_blocks) and index_t < len(theirs_blocks):
        base_o, match_o, length_o = ours_blocks[index_o]
        base_t, match_t, length_t = theirs_blocks[index_t]
        start, end = max(base_o, base_t), min(base_o + length_o, base_t + length_t)
        if start < end:
            sub_o, sub_t = match_o + (start - base_o), match_t + (start - base_t)
            regions.append((start, end, sub_o, sub_o + end - start, sub_t, sub_t + end - start))
        if base_o + length_o < base_t + length_t:
            index_o += 1
        else:
            index_t += 1
    regions.append((len(base), len(base), len(ours), len(ours), len(theirs), len(theirs)))
    return regions


def merge_lines(base: list[str], ours: list[str], theirs: list[str]) -> list[tuple[str, Any]]:
    """Regions in order: ``("unchanged" | "same" | "ours" | "theirs", lines)`` or
    ``("conflict", (base, ours, theirs))``; ``ours``/``theirs`` mark a hunk changed on that side only."""
    regions: list[tuple[str, Any]] = []
    at_base = at_ours = at_theirs = 0
    for base_start, base_end, ours_start, ours_end, theirs_start, theirs_end in _sync_regions(base, ours, theirs):
        base_part, ours_part = base[at_base:base_start], ours[at_ours:ours_start]
        theirs_part = theirs[at_theirs:theirs_start]
        if ours_part or theirs_part:
            if ours_part == theirs_part:
                regions.append(("same", ours_part))
            elif ours_part == base_part:
                regions.append(("theirs", theirs_part))
            elif theirs_part == base_part:
                regions.append(("ours", ours_part))
            else:
                regions.append(("conflict", (base_part, ours_part, theirs_part)))
        if base_end > base_start:
            regions.append(("unchanged", base[base_start:base_end]))
        at_base, at_ours, at_theirs = base_end, ours_end, theirs_end
    return regions


def _conflict_id(path: str, index: int, base: list[str], ours: list[str]) -> str:
    digest = hashlib.sha256(f"{path}\0{index}\0{''.join(base)}\0{''.join(ours)}".encode()).hexdigest()
    return f"c-{digest[:12]}"


def _strip_blank(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _find_block(haystack: list[str], needle: list[str]) -> int | None:
    if not needle:
        return None
    hits = [index for index in range(len(haystack) - len(needle) + 1) if haystack[index:index + len(needle)] == needle]
    return hits[0] if len(hits) == 1 else None


def _relocation(path: str, base: list[str], ours: list[str], theirs_file: list[str],
                new_files: dict[str, list[str]]) -> dict[str, Any] | None:
    block = _strip_blank(base)
    if not block or any(theirs_file[index:index + len(block)] == block for index in range(len(theirs_file))):
        return None  # the base lines still live in the upstream file: nothing moved
    candidates = [(other, position) for other, lines in sorted(new_files.items())
                  if other != path and (position := _find_block(lines, block)) is not None]
    if len(candidates) != 1:
        return None
    target, position = candidates[0]
    mine = _strip_blank(ours)
    return {"path": target, "line": position + 1, "end_line": position + len(block),
            "after_line": position + len(block), "block": block, "mine": mine}


def merge_bundle(base: dict[str, str], ours: dict[str, str], theirs: dict[str, str]) -> dict[str, Any]:
    """``{"files": {path: text}, "report": {...}}``; conflicted places carry upstream text until resolved."""
    merged: dict[str, str] = {}
    files: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    layouts: dict[str, list[Any]] = {}
    new_upstream = {path: _lines(text) for path, text in theirs.items() if path not in base}
    for path in sorted(set(base) | set(ours) | set(theirs)):
        b, o, t = base.get(path), ours.get(path), theirs.get(path)
        counts: dict[str, int] = {}
        if o == t:
            status, result = ("unchanged" if o == b else "same_change"), o
        elif o == b:
            status, result = ("removed_upstream" if t is None else "added_upstream" if b is None
                              else "took_upstream"), t
        elif t == b:
            status, result = "kept_local", o
        elif o is None or t is None:
            conflict_id = _conflict_id(path, 0, _lines(b), _lines(o))
            conflicts.append({"id": conflict_id, "path": path, "kind": "file", "base": _lines(b), "ours": _lines(o),
                              "theirs": _lines(t), "relocation": None})
            layouts[path] = [("conflict", conflict_id)]
            status, result = "conflict", t
        else:
            regions = merge_lines(_lines(b), _lines(o), _lines(t))
            layout: list[Any] = []
            text_parts: list[str] = []
            counts = {"local_hunks": sum(1 for kind, _ in regions if kind == "ours"),
                      "upstream_hunks": sum(1 for kind, _ in regions if kind == "theirs")}
            for index, (kind, value) in enumerate(regions):
                if kind != "conflict":
                    layout.append(("text", value))
                    text_parts += value
                    continue
                base_part, ours_part, theirs_part = value
                conflict_id = _conflict_id(path, index, base_part, ours_part)
                conflicts.append({"id": conflict_id, "path": path, "kind": "hunk", "base": base_part,
                                  "ours": ours_part, "theirs": theirs_part,
                                  "relocation": _relocation(path, base_part, ours_part, _lines(t), new_upstream)})
                layout.append(("conflict", conflict_id))
                text_parts += theirs_part
            if any(kind == "conflict" for kind, _ in regions):
                layouts[path] = layout
                status = "conflict"
            else:
                status = "merged"
            result = "".join(text_parts)
        files.append({"path": path, "status": status, **counts})
        if result is not None:
            merged[path] = result
    # Relocation targets as upstream wrote them: resolutions are always re-applied from these, so changing a
    # resolution later never leaves an earlier relocation behind.
    originals = {item["relocation"]["path"]: theirs[item["relocation"]["path"]]
                 for item in conflicts if item.get("relocation")}
    report = {"files": files, "conflicts": conflicts, "layouts": _serialize_layouts(layouts), "resolutions": {},
              "originals": originals}
    return {"files": merged, "report": report}


def _serialize_layouts(layouts: dict[str, list[Any]]) -> dict[str, list[dict[str, Any]]]:
    return {path: [{"text": "".join(value)} if kind == "text" else {"conflict": value} for kind, value in layout]
            for path, layout in layouts.items()}


def resolved_files(files: dict[str, str], report: dict[str, Any]) -> dict[str, str]:
    """``files`` with every resolved conflict applied (unresolved ones keep upstream text)."""
    conflicts = {item["id"]: item for item in report.get("conflicts") or []}
    resolutions = report.get("resolutions") or {}
    for conflict_id, resolution in resolutions.items():
        if conflict_id not in conflicts:
            raise SkillCatalogError("skill_conflict_unknown", 422, conflict=conflict_id)
        choice = (resolution or {}).get("choice") if isinstance(resolution, dict) else None
        if choice not in RESOLUTIONS:
            raise SkillCatalogError("skill_resolution_invalid", 422, conflict=conflict_id)
        if choice == "relocate" and not conflicts[conflict_id].get("relocation"):
            raise SkillCatalogError("skill_relocation_unavailable", 422, conflict=conflict_id)
        if choice == "manual" and not isinstance(resolution.get("text"), str):
            raise SkillCatalogError("skill_resolution_text_required", 422, conflict=conflict_id)
    result = {**files, **(report.get("originals") or {})}
    for path, layout in (report.get("layouts") or {}).items():
        parts: list[str] = []
        file_level_removed = False
        for item in layout:
            if "text" in item:
                parts.append(item["text"])
                continue
            conflict = conflicts[item["conflict"]]
            resolution = resolutions.get(item["conflict"]) or {"choice": "upstream"}
            choice = resolution["choice"]
            chosen = ("".join(conflict["ours"]) if choice == "mine" else resolution.get("text", "")
                      if choice == "manual" else "".join(conflict["theirs"]))
            if conflict["kind"] == "file" and choice == "mine" and not conflict["ours"]:
                file_level_removed = True
            if conflict["kind"] == "file" and choice == "upstream" and not conflict["theirs"]:
                file_level_removed = True
            parts.append(chosen)
        if file_level_removed:
            result.pop(path, None)
        else:
            result[path] = "".join(parts)
    for conflict_id, resolution in resolutions.items():
        relocation = conflicts[conflict_id].get("relocation")
        if resolution.get("choice") != "relocate" or not relocation:
            continue
        target = _lines(result.get(relocation["path"]))
        start = _find_block(target, relocation["block"])
        if start is None:
            raise SkillCatalogError("skill_relocation_unavailable", 422, conflict=conflict_id)
        target[start:start + len(relocation["block"])] = relocation["mine"]
        result[relocation["path"]] = "".join(target)
    return result


__all__ = ["RESOLUTIONS", "merge_bundle", "merge_lines", "resolved_files"]
