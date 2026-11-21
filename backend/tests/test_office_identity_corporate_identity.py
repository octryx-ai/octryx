"""One corporate identity from PowerPoint + Word: shared core, per-medium accents.

A brand's decks and documents share a typeface, neutral palette and logo but use
deliberately different accent palettes. The unified identity keeps the core
shared and the accents separate per medium, and records a real conflict (a
different typeface between two templates) instead of averaging it away.
"""

from app.services.office_identity import build_corporate_identity

# Invented Example Corp signals: same Arial + neutrals, different accents per medium.
_PPTX = {
    "kind": "presentation",
    "source_file": "brand.potx",
    "theme": {
        "fonts": {"major": "Arial", "minor": "Arial"},
        "colors": {
            "dk1": "#000000", "lt1": "#FFFFFF", "dk2": "#4A4D52", "lt2": "#E2E3E5",
            "accent1": "#2A3F6B", "accent2": "#3FB8C9", "accent3": "#8E5A9B",
        },
        "theme_name": "Example Brand 2026",
    },
}
_DOCX = {
    "kind": "document",
    "source_file": "letter.docx",
    "theme": {
        "fonts": {"majorFont": "Arial", "minorFont": "Arial"},
        "colors": {
            "dk1": "#000000", "lt1": "#FFFFFF", "dk2": "#4A4D52", "lt2": "#E2E3E5",
            "accent1": "#4F7A5C", "accent2": "#D9822B", "accent3": "#6C8FA8",
        },
    },
    "branding": {"logo_count": 1, "footer_text": "Example Corp Ltd | Registered in Exampletown"},
}


def test_shared_core_with_per_medium_accents():
    ci = build_corporate_identity([_PPTX, _DOCX])

    assert ci["fonts"] == {"major": "Arial", "minor": "Arial"}
    assert ci["neutrals"] == {"dk1": "#000000", "lt1": "#FFFFFF", "dk2": "#4A4D52", "lt2": "#E2E3E5"}
    # Accents stay separate per medium — never merged into one list.
    assert ci["accents_by_medium"]["presentation"]["accent1"] == "#2A3F6B"
    assert ci["accents_by_medium"]["document"]["accent1"] == "#4F7A5C"
    assert ci["logo"]["present"] is True
    assert ci["logo"]["sources"] == ["letter.docx"]
    assert ci["letterhead"]["has_letterhead"] is True
    assert "Example Corp" in ci["letterhead"]["footer_text"]
    assert ci["conflicts"] == []
    assert ci["summary"]["media"] == ["document", "presentation"]
    assert ci["summary"]["font"] == "Arial"


def test_font_conflict_is_recorded_not_averaged():
    other = {**_DOCX, "source_file": "rogue.docx",
             "theme": {**_DOCX["theme"], "fonts": {"majorFont": "Calibri", "minorFont": "Calibri"}}}
    ci = build_corporate_identity([_PPTX, _DOCX, other])

    conflicts = {c["field"]: c for c in ci["conflicts"]}
    assert "font.major" in conflicts
    # Arial wins (2 of 3), Calibri is recorded as an alternative.
    assert ci["fonts"]["major"] == "Arial"
    assert "Calibri" in conflicts["font.major"]["alternatives"]


def test_single_source_is_a_valid_identity():
    ci = build_corporate_identity([_DOCX])

    assert ci["summary"]["source_count"] == 1
    assert ci["accents_by_medium"] == {"document": {"accent1": "#4F7A5C", "accent2": "#D9822B", "accent3": "#6C8FA8"}}
    assert "presentation" not in ci["accents_by_medium"]
    assert ci["conflicts"] == []


def test_empty_sources_yield_an_empty_but_valid_brief():
    ci = build_corporate_identity([])

    assert ci["kind"] == "corporate_identity"
    assert ci["fonts"] == {"major": "", "minor": ""}
    assert ci["neutrals"] == {}
    assert ci["accents_by_medium"] == {}
    assert ci["logo"]["present"] is False
    assert ci["summary"]["source_count"] == 0
