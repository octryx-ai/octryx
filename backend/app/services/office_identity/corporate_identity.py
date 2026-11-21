"""One corporate identity from all of a profile's templates.

A brand ships more than one template — decks *and* documents — and they share a
core (typeface, neutral palette, logo, company name) while deliberately using
different accent palettes: presentation accents are vivid, document accents are
subdued. Merging every accent into one list would erase that distinction, so this
builds a *unified* identity instead: one shared core across every source, plus a
separate accent palette per medium. Disagreements in the core (a different
typeface between two templates) are recorded as conflicts, never averaged away.

The builder is pure — it takes already-extracted brand signals, not files — so it
is deterministic and testable without any template on disk.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

CI_KIND = "corporate_identity"
CI_VERSION = 1

#: The neutral slots shared across every medium (black / white / greys).
_NEUTRAL_SLOTS = ("dk1", "lt1", "dk2", "lt2")
#: The accent slots that differ per medium.
_ACCENT_SLOTS = ("accent1", "accent2", "accent3", "accent4", "accent5", "accent6")
#: Source kind -> the medium its accents belong to.
_MEDIUM_BY_KIND = {"presentation": "presentation", "pptx": "presentation", "document": "document", "docx": "document"}


def _consensus(values: list[tuple[str, str]]) -> tuple[str, dict[str, Any] | None]:
    """Agreed value across ``(value, source_file)`` pairs, plus any conflict.

    Empty values are ignored. When the non-empty values disagree, the most common
    wins and the disagreement is returned so the caller can surface it rather than
    silently picking one.
    """
    present = [(value, source) for value, source in values if str(value or "").strip()]
    if not present:
        return "", None
    counts = Counter(value for value, _ in present)
    winner, _ = counts.most_common(1)[0]
    if len(counts) == 1:
        return winner, None
    conflict = {
        "chosen": winner,
        "alternatives": sorted(set(counts) - {winner}),
        "by_source": {source: value for value, source in present},
    }
    return winner, conflict


def _font_consensus(
    clean: list[dict[str, Any]], role: str, keys: tuple[str, ...], conflicts: list[dict[str, Any]]
) -> str:
    # pptx themes name the roles "major"/"minor"; docx themes name them
    # "majorFont"/"minorFont". Read whichever a source provides so the two
    # media are compared as the same role and a real typeface conflict shows.
    pairs: list[tuple[str, str]] = []
    for source in clean:
        fonts_map = (source.get("theme") or {}).get("fonts", {})
        value = next((str(fonts_map[key]) for key in keys if fonts_map.get(key)), "")
        pairs.append((value, str(source.get("source_file") or "")))
    agreed, conflict = _consensus(pairs)
    if conflict:
        conflicts.append({"field": f"font.{role}", **conflict})
    return agreed


def _neutral_colors(clean: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> dict[str, str]:
    neutrals: dict[str, str] = {}
    for slot in _NEUTRAL_SLOTS:
        pairs = [
            (str((source.get("theme") or {}).get("colors", {}).get(slot) or ""), str(source.get("source_file") or ""))
            for source in clean
        ]
        value, conflict = _consensus(pairs)
        if value:
            neutrals[slot] = value
        if conflict:
            conflicts.append({"field": f"neutral.{slot}", **conflict})
    return neutrals


def _accents_by_medium(clean: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    accents_by_medium: dict[str, dict[str, str]] = {}
    for source in clean:
        medium = _MEDIUM_BY_KIND.get(str(source.get("kind") or "").strip())
        if not medium or medium in accents_by_medium:
            continue
        colors = (source.get("theme") or {}).get("colors", {})
        accents = {slot: colors[slot] for slot in _ACCENT_SLOTS if colors.get(slot)}
        if accents:
            accents_by_medium[medium] = accents
    return accents_by_medium


def _letterhead(clean: list[dict[str, Any]]) -> Any:
    return next(
        (
            source.get("branding")
            for source in clean
            if (source.get("branding") or {}).get("footer_text")
        ),
        {},
    )


def build_corporate_identity(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one identity from many template brand signals.

    Each source is ``{"kind": "presentation"|"document", "source_file": str,
    "theme": {"fonts": {...}, "colors": {...}}, "branding": {...}}`` — the shape
    the pptx and docx snapshots already expose. Returns the unified identity brief.
    """
    clean = [source for source in sources if isinstance(source, dict)]
    conflicts: list[dict[str, Any]] = []
    fonts = {
        "major": _font_consensus(clean, "major", ("major", "majorFont"), conflicts),
        "minor": _font_consensus(clean, "minor", ("minor", "minorFont"), conflicts),
    }
    neutrals = _neutral_colors(clean, conflicts)
    accents_by_medium = _accents_by_medium(clean)
    logo_sources = [
        str(source.get("source_file") or "")
        for source in clean
        if int((source.get("branding") or {}).get("logo_count") or 0) > 0
    ]
    letterhead = _letterhead(clean)

    return {
        "kind": CI_KIND,
        "version": CI_VERSION,
        "fonts": fonts,
        "neutrals": neutrals,
        "accents_by_medium": accents_by_medium,
        "logo": {"present": bool(logo_sources), "sources": logo_sources},
        "letterhead": {
            "footer_text": str((letterhead or {}).get("footer_text") or ""),
            "header_text": str((letterhead or {}).get("header_text") or ""),
            "has_letterhead": bool(letterhead),
        },
        "sources": [
            {
                "source_file": str(source.get("source_file") or ""),
                "kind": str(source.get("kind") or ""),
                "theme_name": str((source.get("theme") or {}).get("theme_name") or ""),
            }
            for source in clean
        ],
        "conflicts": conflicts,
        "summary": {
            "source_count": len(clean),
            "media": sorted(accents_by_medium),
            "font": fonts.get("major") or fonts.get("minor"),
            "neutral_count": len(neutrals),
            "has_logo": bool(logo_sources),
            "has_letterhead": bool(letterhead),
            "conflict_count": len(conflicts),
        },
    }


def _presentation_source(path: str | Path) -> dict[str, Any] | None:
    from .template_snapshot import build_template_snapshot

    try:
        snapshot = build_template_snapshot(path)
    except (FileNotFoundError, ValueError):
        return None
    theme = snapshot.get("theme") or {}
    colors = {
        slot: (value.get("hex") if isinstance(value, dict) else value)
        for slot, value in (theme.get("colors") or {}).items()
    }
    return {
        "kind": "presentation",
        "source_file": Path(path).name,
        "theme": {"fonts": theme.get("fonts") or {}, "colors": colors, "theme_name": theme.get("theme_name")},
    }


def _document_source(path: str | Path) -> dict[str, Any] | None:
    from .document_snapshot import build_document_snapshot

    try:
        snapshot = build_document_snapshot(path)
    except (FileNotFoundError, ValueError):
        return None
    return {
        "kind": "document",
        "source_file": Path(path).name,
        "theme": snapshot.get("theme") or {},
        "branding": snapshot.get("branding") or {},
    }


def corporate_identity_from_templates(
    *, presentation_paths: list[str] | None = None, document_paths: list[str] | None = None
) -> dict[str, Any]:
    """Build the unified identity from a profile's template files on disk.

    Unreadable templates are skipped rather than aborting the whole identity —
    one broken upload never hides the rest of the brand.
    """
    sources: list[dict[str, Any]] = []
    for path in presentation_paths or []:
        source = _presentation_source(path)
        if source:
            sources.append(source)
    for path in document_paths or []:
        source = _document_source(path)
        if source:
            sources.append(source)
    return build_corporate_identity(sources)


__all__ = [
    "build_corporate_identity",
    "corporate_identity_from_templates",
    "CI_KIND",
    "CI_VERSION",
]
