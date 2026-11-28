"""The fields of a style profile and their validation; a level stores only what it sets, ``None`` keeps the parent's."""

from __future__ import annotations

from typing import Any

from .schema_sections import _comments, _diagrams, _exclude, _l10n, _layout, _naming, _tool
from .schema_values import (
    FIELDS,
    LANGUAGES,
    LINE_FIELDS,
    MAX_TEXT,
    MISSING_TOOL_LEVELS,
    TOOL_FIELDS,
    CodeStyleError,
    _globs,
)


def _fields(value: dict[str, Any], path: str, *, language: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in LINE_FIELDS:
        if value.get(key) is not None:
            if type(value[key]) is not int or not 0 <= value[key] <= 20000:
                raise CodeStyleError("invalid_number", f"{path}.{key}")
            out[key] = value[key]
    if value.get("exclude") is not None:
        out["exclude"] = _exclude(value["exclude"], path)
    if value.get("include") is not None:
        out["include"] = _globs(value["include"], f"{path}.include")
    if value.get("test_globs") is not None:
        out["test_globs"] = _globs(value["test_globs"], f"{path}.test_globs")
    if value.get("comments") is not None:
        out["comments"] = _comments(value["comments"], path)
    if value.get("layout") is not None:
        out["layout"] = _layout(value["layout"], path)
    if value.get("naming") is not None:
        out["naming"] = _naming(value["naming"], path)
    for kind in TOOL_FIELDS:
        if value.get(kind) is not None:
            out[kind] = _tool(value[kind], f"{path}.{kind}")
    if value.get("l10n") is not None:
        out["l10n"] = _l10n(value["l10n"], f"{path}.l10n")
    if value.get("diagrams") is not None:
        out["diagrams"] = _diagrams(value["diagrams"], f"{path}.diagrams")
    if value.get("missing_tool") is not None:
        # A formatter / linter that is not installed warns by default; error makes it red.
        if value["missing_tool"] not in MISSING_TOOL_LEVELS:
            raise CodeStyleError("invalid_missing_tool", f"{path}.missing_tool")
        out["missing_tool"] = value["missing_tool"]
    if value.get("rules") is not None:
        if not isinstance(value["rules"], str) or len(value["rules"]) > MAX_TEXT:
            raise CodeStyleError("invalid_rules", f"{path}.rules")
        out["rules"] = value["rules"].strip()
    if not language and value.get("languages") is not None:
        languages = value["languages"]
        if not isinstance(languages, dict) or set(languages) - set(LANGUAGES):
            raise CodeStyleError("invalid_languages", f"{path}.languages")
        out["languages"] = {}
        for name, item in languages.items():
            if not isinstance(item, dict) or set(item) - set(FIELDS):
                raise CodeStyleError("invalid_languages", f"{path}.languages.{name}")
            out["languages"][name] = _fields(item, f"{path}.languages.{name}", language=True)
    return out


def normalize_profile(value: Any, path: str = "code_style") -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {*FIELDS, "languages", "technologies"}:
        raise CodeStyleError("invalid_code_style", path)
    out = _fields(value, path, language=False)
    if value.get("technologies") is not None:
        # The technologies specification decisions name (``technologies``; review ``spec_decisions``).
        from .technologies import normalize

        out["technologies"] = normalize(value["technologies"], f"{path}.technologies")
    return out


__all__ = [
    "normalize_profile",
]
