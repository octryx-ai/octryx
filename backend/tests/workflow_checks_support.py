"""Shared helpers for the test_workflow_checks_* modules."""

from __future__ import annotations

KNOWLEDGE_CHECKS = [
    {"type": "tool_called", "params": {"tools": ["knowledge_search", "knowledge_read"], "any": True},
     "blocking": True, "description": "Evidence retrieved"},
    {"type": "answer_contains_any", "params": {"values": ["release"]}, "blocking": False},
    {"type": "judge", "params": {"rubric": "Is it complete?"}},
]
