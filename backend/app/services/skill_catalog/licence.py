"""Licence of an imported skill: SPDX id and the licence text that must travel with the copy.

Order: the skill's frontmatter ``license``, else the plugin's ``plugin.json`` / marketplace entry ``license``,
else the repository ``LICENSE`` file. A LICENSE file is identified by the canonical title lines the licence
texts themselves carry (exact phrases, first 40 lines) — deterministic, no scoring. An unidentified text stays
``None`` and publishing is refused until an admin sets the SPDX id (``skill_licence_not_allowed``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LICENCE_FILE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "COPYING")

#: (SPDX id, phrases that must all appear in the first lines of the text, case-insensitive, whitespace-folded).
#: First match wins, so the more specific texts come first (BSD-3 before BSD-2, AGPL/LGPL before GPL).
_TITLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("MPL-2.0", ("mozilla public license version 2.0",)),
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MIT", ("mit license",)),
    ("MIT", ("permission is hereby granted, free of charge, to any person obtaining a copy",)),
    ("BSD-3-Clause", ("redistribution and use in source and binary forms", "neither the name")),
    ("BSD-2-Clause", ("redistribution and use in source and binary forms",)),
    ("ISC", ("isc license",)),
    ("ISC", ("permission to use, copy, modify, and/or distribute this software for any",)),
    ("AGPL-3.0", ("gnu affero general public license", "version 3")),
    ("LGPL-3.0", ("gnu lesser general public license", "version 3")),
    ("GPL-3.0", ("gnu general public license", "version 3")),
)
_SPDX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$")


@dataclass(frozen=True, slots=True)
class LicenceInfo:
    spdx: str | None
    source: str  # "frontmatter" | "plugin" | "repository" | "none"
    text_path: str | None = None


def _folded(text: str) -> str:
    head = "\n".join(text.splitlines()[:40])
    return re.sub(r"\s+", " ", head).strip().lower()


def _contains(folded: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", folded) is not None


def identify_licence_text(text: str) -> str | None:
    folded = _folded(text)
    return next((spdx for spdx, phrases in _TITLES if all(_contains(folded, phrase) for phrase in phrases)), None)


def spdx_value(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text and _SPDX.match(text) else None


def detect_licence(*, frontmatter_licence: object, plugin_licence: object,
                   repository_files: dict[str, str]) -> LicenceInfo:
    """``repository_files``: candidate LICENSE texts by path, nearest first (skill folder, plugin, repository)."""
    declared = spdx_value(frontmatter_licence)
    text_path = next(iter(repository_files), None)
    if declared:
        return LicenceInfo(declared, "frontmatter", text_path)
    plugin = spdx_value(plugin_licence)
    if plugin:
        return LicenceInfo(plugin, "plugin", text_path)
    for path, text in repository_files.items():
        identified = identify_licence_text(text)
        if identified:
            return LicenceInfo(identified, "repository", path)
    return LicenceInfo(None, "none", text_path)


__all__ = ["LICENCE_FILE_NAMES", "LicenceInfo", "detect_licence", "identify_licence_text", "spdx_value"]
