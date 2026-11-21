"""Shared helpers for the test_data_classification_* modules."""

from __future__ import annotations

import uuid


def _uid() -> str:
    return str(uuid.uuid4())
