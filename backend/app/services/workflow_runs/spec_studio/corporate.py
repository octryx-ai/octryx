"""The Corporate Identity as the Spec Studio's default direction.

The source is the corporate identity brief of a CI profile (``corp_identity_service.get_corp_identity_brief``: the
Office theme of the uploaded templates). It gives fonts (major / minor), neutrals (dk1, lt1, dk2, lt2), accents per
medium, a logo and icons; it has no dark theme, no ok / warn / error, no radius. ``corporate_direction`` turns it
into a Studio direction and marks every value with its source:

- ``ci``: taken from the template as it is, never changed (a CI pair below AA stays and becomes an open point);
- ``derived``: filled in where the template says nothing, adjusted until it meets AA.

Mapping: lt1 → bg, lt2 → surface, dk1 → text, dk2 → muted, the first accent → accent; ok / warn / error take an
accent of fitting hue when the template has one. The dark theme is derived from the same hues.
"""

from __future__ import annotations

import colorsys
from pathlib import PurePosixPath
from typing import Any

from .design import AA, contrast, on_accent

FALLBACK_LIGHT = {"bg": "#FFFFFF", "text": "#1B1F24", "accent": "#2F5BD3"}
FALLBACK_SIGNAL = {"ok": "#1E7A46", "warn": "#8A5A00", "error": "#B42318"}
# Hue windows (degrees) an accent must fall in to stand for a signal colour.
SIGNAL_HUES = {"ok": (90, 165), "warn": (30, 55), "error": (345, 15)}
RADIUS = 8
MONO = "ui-monospace, monospace"


def _hls(colour: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)))


def _hex(h: float, lightness: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, lightness)), s)
    return "#" + "".join(f"{round(c * 255):02X}" for c in (r, g, b))


def _mix(a: str, b: str, share: float) -> str:
    """``share`` of ``b`` in ``a``."""
    return "#" + "".join(f"{round(int(a[i:i + 2], 16) * (1 - share) + int(b[i:i + 2], 16) * share):02X}"
                         for i in (1, 3, 5))


def until_aa(colour: str, background: str, *, lighter: bool) -> str:
    """``colour`` made lighter or darker in steps, keeping its hue, until it meets AA on ``background``."""
    h, lightness, s = _hls(colour)
    candidate = colour
    while contrast(candidate, background) < AA and 0.0 < lightness < 1.0:
        lightness += 0.02 if lighter else -0.02
        candidate = _hex(h, lightness, s)
    return candidate


def accent_until_aa(colour: str, background: str, *, lighter: bool) -> str:
    """A derived main-action colour: AA on ``background`` and AA for the button text drawn on it."""
    h, lightness, s = _hls(colour)
    candidate = until_aa(colour, background, lighter=lighter)
    lightness = _hls(candidate)[1]
    while contrast(candidate, on_accent(candidate)) < AA and 0.0 < lightness < 1.0:
        lightness += 0.02 if lighter else -0.02
        candidate = _hex(h, lightness, s)
    return candidate


def _in_hue(colour: str, window: tuple[int, int]) -> bool:
    h, lightness, s = _hls(colour)
    degrees, (low, high) = h * 360, window
    inside = low <= degrees <= high if low < high else degrees >= low or degrees <= high
    return inside and s > 0.35 and 0.15 < lightness < 0.85


def _accents(brief: dict[str, Any]) -> list[str]:
    media = dict(brief.get("accents_by_medium") or {})
    for medium in ("presentation", "document", *media):
        accents = dict(media.get(medium) or {})
        if accents:
            return [str(value).upper() for _key, value in sorted(accents.items()) if _valid(value)]
    return []


def _valid(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 7 and value.startswith("#")


def _light(brief: dict[str, Any], sources: dict[str, str]) -> dict[str, str]:
    neutrals = {key: str(value).upper() for key, value in dict(brief.get("neutrals") or {}).items() if _valid(value)}
    accents = _accents(brief)
    out: dict[str, str] = {}

    def take(key: str, value: str | None, fallback: str) -> None:
        out[key] = value or fallback
        sources[f"light.{key}"] = "ci" if value else "derived"

    take("bg", neutrals.get("lt1"), FALLBACK_LIGHT["bg"])
    take("text", neutrals.get("dk1"), FALLBACK_LIGHT["text"])
    take("surface", neutrals.get("lt2"), _mix(out["bg"], out["text"], 0.04))
    take("muted", neutrals.get("dk2"), until_aa(_mix(out["text"], out["surface"], 0.35), out["surface"],
                                                lighter=False))
    take("accent", accents[0] if accents else None, FALLBACK_LIGHT["accent"])
    if sources["light.accent"] == "derived":
        out["accent"] = accent_until_aa(out["accent"], out["bg"], lighter=False)
    for key, window in SIGNAL_HUES.items():
        match = next((colour for colour in accents[1:] if _in_hue(colour, window)), None)
        if match is not None and contrast(match, out["surface"]) >= AA:
            take(key, match, "")
        else:
            out[key] = until_aa(match or FALLBACK_SIGNAL[key], out["surface"], lighter=False)
            sources[f"light.{key}"] = "derived"
    return out


def _dark(light: dict[str, str], sources: dict[str, str]) -> dict[str, str]:
    """The dark theme from the light one's hues: deep page and card, light text, colours lightened until AA."""
    hue, _lightness, saturation = _hls(light["text"])
    bg = _hex(hue, 0.08, min(saturation, 0.25))
    surface = _hex(hue, 0.12, min(saturation, 0.25))
    text = light["bg"] if contrast(light["bg"], bg) >= 7 else "#ECEEF1"
    out = {"bg": bg, "surface": surface, "text": text,
           "muted": until_aa(_mix(text, surface, 0.35), surface, lighter=True)}
    out["accent"] = accent_until_aa(light["accent"], bg, lighter=True)
    for key in ("ok", "warn", "error"):
        out[key] = until_aa(light[key], surface, lighter=True)
    for key in out:
        sources[f"dark.{key}"] = "derived"
    return out


def corporate_direction(brief: dict[str, Any]) -> dict[str, Any]:
    """The Studio direction "Corporate: <profile>" with ``sources`` per value path (``light.accent``, ``radius``, …),
    the CI logo and icons by slug."""
    sources: dict[str, str] = {}
    light = _light(brief, sources)
    dark = _dark(light, sources)
    fonts_in = dict(brief.get("fonts") or {})
    fonts = {}
    for key, source in (("head", "major"), ("body", "minor")):
        name = str(fonts_in.get(source) or fonts_in.get("major") or "").strip()
        fonts[key] = f"{name}, system-ui, sans-serif" if name else "system-ui, sans-serif"
        sources[f"fonts.{key}"] = "ci" if name else "derived"
    fonts["mono"] = MONO
    sources["fonts.mono"] = "derived"
    sources["radius"] = "derived"
    assets = dict(brief.get("assets") or {})
    logos = [row for row in assets.get("logos") or [] if isinstance(row, dict) and row.get("path")]
    # The brief's icon assets carry name and path (<category>/<slug>.svg); the file name is the CI slug.
    icons = {PurePosixPath(str(row["path"])).stem: str(row["path"]) for row in assets.get("icons") or []
             if isinstance(row, dict) and str(row.get("path") or "").endswith(".svg")}
    name = str(brief.get("profile_name") or "Corporate")
    return {
        "id": "corporate",
        "name": f"Corporate: {name}",
        "hint": "Your corporate identity, from the template uploaded on the platform.",
        "light": light, "dark": dark, "fonts": fonts, "radius": RADIUS,
        "corporate": {"profile_id": str(brief.get("profile_id") or ""), "profile_name": name,
                      "sources": sources, "logo": logos[0]["path"] if logos else None, "icons": icons},
    }


__all__ = ["accent_until_aa", "corporate_direction", "until_aa"]
