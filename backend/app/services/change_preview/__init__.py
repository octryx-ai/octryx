"""Canonical package surface for change preview services."""

from .builders import build_command_change_preview, build_tool_change_preview
from .grants import (
    approval_ref_for,
    build_change_request_fingerprint,
    consume_change_preview_grant,
    consume_enforced_approval_mark,
    record_approval_ref,
    record_enforced_approval_mark,
)
from .service import (
    acknowledge_change_previews_for_approval,
    approval_grants_from_preview,
    list_change_previews_by_approval_id,
    serialize_change_preview,
    upsert_change_preview,
)

__all__ = [
    "acknowledge_change_previews_for_approval",
    "approval_grants_from_preview",
    "approval_ref_for",
    "build_change_request_fingerprint",
    "build_command_change_preview",
    "build_tool_change_preview",
    "consume_change_preview_grant",
    "consume_enforced_approval_mark",
    "list_change_previews_by_approval_id",
    "record_approval_ref",
    "record_enforced_approval_mark",
    "serialize_change_preview",
    "upsert_change_preview",
]
