"""Effective design tokens and the WCAG AA contrast check (the same formula the Studio shows live).

The tokens the product owner sees are the proposed direction (or the approved app's tokens for a feature), then
their own choices: another direction, single colours, the radius. The contrast check runs on exactly these, in
light and dark, so a colour that fails AA blocks approval.
"""

from __future__ import annotations

from typing import Any

AA = 4.5
DARK_INK = "#1A1410"
LIGHT_INK = "#FFFFFF"
THEMES = ("light", "dark")
# Text pairs the mock really draws: (label, foreground key or on-accent, background key).
PAIRS = (("Text on background", "text", "bg"), ("Muted text on card", "muted", "surface"),
         ("Button text on main action", "on_accent", "accent"), ("Warning on card", "warn", "surface"),
         ("OK on card", "ok", "surface"))


def _luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground: str, background: str) -> float:
    """WCAG 2.x contrast ratio of two #RRGGBB colours."""
    a, b = _luminance(foreground), _luminance(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def on_accent(accent: str) -> str:
    """The button text colour on ``accent``: white or near-black, whichever contrasts more."""
    return LIGHT_INK if contrast(accent, LIGHT_INK) >= contrast(accent, DARK_INK) else DARK_INK


def effective_design(artefact: dict[str, Any], state: dict[str, Any], base: dict[str, Any] | None = None,
                     corporate: dict[str, Any] | None = None) -> dict[str, Any]:
    """The direction in use with the product owner's overrides applied: ``{direction, name, light, dark, fonts,
    radius}``. A feature without directions of its own uses the approved app's tokens (``base``). The Corporate
    Identity (``corporate``, the run's snapshot) comes first and is preselected; the spec's directions are the
    alternatives."""
    directions = list(dict(artefact.get("design") or {}).get("directions") or [])
    if not directions and base:
        directions = list(dict(base.get("design") or {}).get("directions") or [])
        proposed = str(dict(base.get("design") or {}).get("proposed") or "")
    else:
        proposed = str(dict(artefact.get("design") or {}).get("proposed") or "")
    if corporate is not None:
        directions, proposed = [corporate["direction"], *directions], corporate["direction"]["id"]
    chosen = str(state.get("direction") or proposed)
    direction = next((d for d in directions if d.get("id") == chosen), directions[0] if directions else None)
    if direction is None:
        return {"direction": "", "name": "", "light": {}, "dark": {}, "fonts": {}, "radius": 8}
    overrides = dict(state.get("tokens") or {})
    design = {"direction": direction["id"], "name": direction.get("name") or direction["id"],
              "fonts": {**dict(direction.get("fonts") or {}), **dict(state.get("fonts") or {})},
              "radius": int(state["radius"]) if isinstance(state.get("radius"), int) else int(direction["radius"])}
    for theme in THEMES:
        design[theme] = {**dict(direction.get(theme) or {}), **dict(overrides.get(theme) or {})}
    return design


def contrast_report(design: dict[str, Any]) -> list[dict[str, Any]]:
    """Every text pair in light and dark with its ratio and whether it passes AA (4.5:1)."""
    rows = []
    for theme in THEMES:
        palette = dict(design.get(theme) or {})
        if not palette.get("accent"):
            continue
        palette["on_accent"] = on_accent(palette["accent"])
        for label, fg, bg in PAIRS:
            if palette.get(fg) and palette.get(bg):
                ratio = contrast(palette[fg], palette[bg])
                rows.append({"theme": theme, "pair": label, "ratio": round(ratio, 2), "passes": ratio >= AA})
    return rows


__all__ = ["AA", "THEMES", "contrast", "contrast_report", "effective_design", "on_accent"]
