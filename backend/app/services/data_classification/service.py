"""Data Classification, Retention, and Redaction Service.

Provides:
  classify_entity()            — create or update a DataClassificationTag
  get_classification()         — look up the tag for an entity
  get_policy()                 — look up the active policy for an entity type
  ensure_default_policies()    — seed platform-wide defaults (idempotent)
  check_export_allowed()       — validate export is permitted per policy
  apply_export_classification() — filter/redact an export payload by policy
  detect_and_redact_pii()      — regex PII detection + in-place redaction
  pii_redact_text()            — redact PII from a single string
  list_classification_tags()   — query tags (with filters)
  list_redaction_logs()        — query redaction audit log

The implementation lives in ``pii``, ``policies``, ``tags`` and ``export_controls``; this module keeps the
names importable from one place.
"""

from __future__ import annotations

__all__ = []
