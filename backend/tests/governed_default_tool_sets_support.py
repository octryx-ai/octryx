"""Shared helpers for the test_governed_default_tool_sets_* modules."""

from __future__ import annotations


def _definition(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {}}}


