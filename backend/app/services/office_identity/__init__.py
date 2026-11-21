"""Deterministic Office template evidence and composition (PowerPoint first).

``template_snapshot`` turns an uploaded ``.potx``/``.pptx`` into a machine
readable brief (theme resolved through the master, layout catalog with
capacities, icon catalog). ``presentation_composer`` builds decks *only* from
the layouts of that template — it never invents shapes or coordinates.
``slide_gate`` measures the composed deck and reports every violation it finds;
it never corrects one silently. ``template_normalization`` closes the layout
gaps an upload leaves — as a derivative beside the original, never by editing
the customer's file. ``aws_deck_plan`` derives a deck plan from an AWS topology
snapshot: every bullet carries its evidence field in the notes, and every gap
becomes a visible marker instead of invented prose.
"""

from __future__ import annotations

from .aws_deck_plan import build_aws_deck_plan
from .aws_document_plan import build_aws_document_plan
from .composer_plan import ComposerError
from .corporate_identity import (
    build_corporate_identity,
    corporate_identity_from_templates,
)
from .document_composer import DocumentComposerError, build_document_from_plan
from .document_gate import check_document_quality
from .document_snapshot import build_document_snapshot
from .generic_content_plan import build_generic_deck_plan, build_generic_document_plan
from .presentation_composer import build_presentation_from_plan
from .slide_gate import FINDING_CODES, check_deck_quality
from .template_normalization import NormalizationError, normalize_template
from .template_snapshot import build_template_snapshot

__all__ = [
    "FINDING_CODES",
    "ComposerError",
    "DocumentComposerError",
    "NormalizationError",
    "build_aws_deck_plan",
    "build_aws_document_plan",
    "build_corporate_identity",
    "build_document_from_plan",
    "build_document_snapshot",
    "build_generic_deck_plan",
    "build_generic_document_plan",
    "check_document_quality",
    "corporate_identity_from_templates",
    "build_presentation_from_plan",
    "build_template_snapshot",
    "check_deck_quality",
    "normalize_template",
]
