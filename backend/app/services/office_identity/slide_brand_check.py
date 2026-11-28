"""Theme conformance of the text a slide actually carries."""

from __future__ import annotations

from typing import Any

from .slide_findings import finding as _finding
from .slide_findings import placeholder_idx as _placeholder_idx

#: Runs scanned per slide before the check gives up; a slide with more runs
#: than this has bigger problems than its typeface.
MAX_RUNS_PER_SLIDE = 400

#: Neutral text colours are part of every corporate palette in practice.
_NEUTRAL_COLORS = frozenset({"#000000", "#FFFFFF"})


#: Theme font references resolve to the theme faces themselves.
_THEME_FONT_ALIASES = frozenset({"+mj-lt", "+mn-lt", "+mj-ea", "+mn-ea"})


def _brand_fonts(theme: dict[str, Any]) -> set[str]:
    return {str(value).strip() for value in (theme.get("fonts") or {}).values() if value}


def _brand_colors(theme: dict[str, Any]) -> set[str]:
    colors = {
        str(entry.get("hex") or "").upper()
        for entry in (theme.get("colors") or {}).values()
    }
    return {value for value in colors if value} | set(_NEUTRAL_COLORS)


def check_brand(
    slide_index: int, layout: dict[str, Any], slide: Any, theme: dict[str, Any]
) -> list[dict[str, Any]]:
    fonts = _brand_fonts(theme)
    colors = _brand_colors(theme)
    key = str(layout.get("key"))
    findings: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    scanned = 0
    for shape in slide.shapes:
        if not getattr(shape, "has_text_frame", False):
            continue
        index = _placeholder_idx(shape)
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                scanned += 1
                if scanned > MAX_RUNS_PER_SLIDE:
                    return findings
                for detail in _run_violations(run, fonts, colors):
                    if (index, detail) in seen:
                        continue
                    seen.add((index, detail))
                    findings.append(
                        _finding("off_brand_font_or_color", slide_index, key, index, detail)
                    )
    return findings


def _run_violations(run: Any, fonts: set[str], colors: set[str]) -> list[str]:
    details: list[str] = []
    name = getattr(run.font, "name", None)
    if name and fonts and str(name).strip() not in fonts | _THEME_FONT_ALIASES:
        details.append(f"run sets font {name!r}, outside the theme fonts {sorted(fonts)}")
    try:
        from pptx.enum.dml import MSO_COLOR_TYPE

        color = run.font.color
        if color is not None and color.type == MSO_COLOR_TYPE.RGB:
            value = f"#{color.rgb}".upper()
            if value not in colors:
                details.append(f"run sets colour {value}, outside the theme palette")
    except (AttributeError, TypeError, ValueError, ImportError):
        pass
    return details


__all__ = ["MAX_RUNS_PER_SLIDE", "check_brand"]
