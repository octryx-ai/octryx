"""The style that applies, field by field, with where each value comes from."""

from __future__ import annotations

from typing import Any

from .defaults import BUILT_IN
from .schema_values import FIELDS

LEVELS = ("repository", "workspace", "installation", "built_in")
_NESTED = ("comments", "layout", "naming", "formatter", "linter", "l10n", "diagrams")


def _candidates(levels: dict[str, dict[str, Any]], language: str | None) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for level in LEVELS:
        profile = BUILT_IN if level == "built_in" else dict(levels.get(level) or {})
        own = dict(dict(profile.get("languages") or {}).get(language) or {}) if language else {}
        if own:
            out.append((f"{level}.languages.{language}", own))
        out.append((level, profile))
    return out


def effective(levels: dict[str, dict[str, Any]], language: str | None = None) -> dict[str, Any]:
    candidates = _candidates(levels, language)
    out: dict[str, Any] = {}
    for field in FIELDS:
        if field == "exclude":
            seen: dict[str, dict[str, Any]] = {}
            for source, fields in candidates:
                for row in fields.get("exclude") or []:
                    seen.setdefault(row["glob"], {"glob": row["glob"], "reason": row.get("reason", "other"),
                                                  **({"keep": row["keep"]} if row.get("keep") else {}),
                                                  "source": source})
            out["exclude"] = {"value": list(seen.values()), "source": "merged"}
        elif field == "include":
            included: dict[str, dict[str, Any]] = {}
            for source, fields in candidates:
                for glob in fields.get("include") or []:
                    included.setdefault(str(glob), {"glob": str(glob), "source": source})
            out["include"] = {"value": list(included.values()), "source": "merged"}
        elif field == "rules":
            lines: list[str] = []
            for _source, fields in reversed(candidates):  # the central rules first
                for line in str(fields.get("rules") or "").splitlines():
                    if line.strip() and line.strip() not in {item.strip() for item in lines}:
                        lines.append(line.rstrip())
            out["rules"] = {"value": "\n".join(lines) or None, "source": "merged"}
        elif field in _NESTED:
            merged: dict[str, Any] = {}
            for source, fields in reversed(candidates):
                for key, item in dict(fields.get(field) or {}).items():
                    merged[key] = {"value": item, "source": source}
            out[field] = merged
        else:
            source, value = next(((source, fields[field]) for source, fields in candidates
                                  if fields.get(field) is not None), ("built_in", None))
            out[field] = {"value": value, "source": source}
    return out


def flat(view: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, item in view.items():
        if field in ("exclude", "include"):  # each row keeps its level: the most specific one decides (check.py)
            out[field] = [dict(row) for row in item["value"]]
        elif field in _NESTED:
            out[field] = {key: entry["value"] for key, entry in item.items()}
        else:
            out[field] = item["value"]
    return out


__all__ = ["LEVELS", "effective", "flat"]
