"""The manual layer of one PDF revision: outline, references, parameters, compatibility, terms."""

from __future__ import annotations

from .facts import Extraction, SpanInput
from .manual_structure import add_outline, add_references, build_outline
from .manual_tables import add_tables
from .manual_terms import add_terms
from .profile_types import StructuredProfile

EXTRACTOR = "manual-rules"


def extract_manual(spans: list[SpanInput], profile: StructuredProfile, *, document_key: str, title: str) -> Extraction:
    ordered = sorted(spans, key=lambda span: span.ordinal)
    extraction = Extraction()
    outline = build_outline(ordered, profile, document_key)
    add_outline(extraction, outline, title, ordered[0].ordinal if ordered else None)
    add_references(extraction, outline, ordered, profile)
    add_tables(extraction, ordered, outline, profile)
    add_terms(extraction, ordered, outline, profile)
    return extraction


__all__ = ["EXTRACTOR", "extract_manual"]
