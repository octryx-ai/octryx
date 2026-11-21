"""Shared helpers for the test_content_admission_* modules."""

from __future__ import annotations

IBAN = "GB82WEST12345698765432"


BLOCK_IBAN = ('@id("block-bank-data")\nforbid (principal, action == Action::"call_model", resource)\n'
              'when { context.content.detected.contains("iban") };')
