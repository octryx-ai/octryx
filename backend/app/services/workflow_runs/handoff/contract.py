"""Closed authored handoff/action contracts and canonical server bindings."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from ...work_role_model.seeds import WORK_ROLE_KEYS

ARTEFACT_KINDS = frozenset({"definition_of_ready", "test_contract", "reproduction", "incident_hypothesis",
                           "feature_documentation", "spec"})
SCOPE_KEYS = frozenset({"workspace_id", "work_item_id", "repository", "service_ids", "connection_ids", "source_ids"})


def refuse(reason: str, message: str, status: int = 409) -> None:
    raise HTTPException(status, {"reason": reason, "message": message})


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _uuid(value: Any) -> str:
    if not isinstance(value, str):
        refuse("invalid_handoff", "A UUID reference is required", 422)
    try:
        parsed = str(UUID(value))
    except ValueError:
        refuse("invalid_handoff", "A UUID reference is required", 422)
    if value != parsed:
        refuse("invalid_handoff", "UUID references must be canonical", 422)
    return parsed


def owner_ref(value: Any, *, deputy: bool = False) -> tuple[str, str]:
    if not isinstance(value, str) or value.count(":") != 1:
        refuse("invalid_handoff", "Use a person, work role or identity group reference", 422)
    kind, key = value.split(":")
    if kind == "role" and key in WORK_ROLE_KEYS:
        return kind, key
    if not deputy and kind in {"person", "group"}:
        return kind, _uuid(key)
    refuse("invalid_handoff", "The owner or deputy reference is unsupported", 422)


def validate_contract(raw: Any) -> dict:
    required = {"schema_version", "owner", "artefacts", "acceptance", "scope", "detach", "timeout_seconds"}
    if not isinstance(raw, dict) or set(raw) - required - {"deputy"} or required - set(raw):
        refuse("invalid_handoff", "The handoff must use the closed handoff/v1 schema", 422)
    if raw["schema_version"] != "handoff/v1":
        refuse("invalid_handoff", "Unsupported handoff schema", 422)
    owner_ref(raw["owner"])
    if raw.get("deputy") is not None:
        owner_ref(raw["deputy"], deputy=True)
    if type(raw["detach"]) is not bool or type(raw["timeout_seconds"]) is not int or not (
            1 <= raw["timeout_seconds"] <= 604800):
        refuse("invalid_handoff", "A boolean detach flag and bounded positive timeout are required", 422)
    if not isinstance(raw["acceptance"], str) or not raw["acceptance"].strip() or len(raw["acceptance"]) > 4000:
        refuse("invalid_handoff", "Concrete artefact acceptance is required", 422)
    kinds = raw["artefacts"]
    if not isinstance(kinds, list) or not kinds or any(not isinstance(k, str) or k not in ARTEFACT_KINDS for k in kinds
            ) or len(kinds) != len(set(kinds)):
        refuse("invalid_handoff", "Choose distinct existing artefact kinds", 422)
    scope = raw["scope"]
    if not isinstance(scope, dict) or set(scope) != SCOPE_KEYS:
        refuse("invalid_handoff", "All explicit scope fields are required", 422)
    _uuid(scope["workspace_id"])
    if scope["work_item_id"] is not None:
        _uuid(scope["work_item_id"])
    repository = scope["repository"]
    if repository is not None:
        from ..platform.repo_ref import parse_repository
        if not isinstance(repository, str) or parse_repository(repository) is None:
            refuse("invalid_handoff", "The repository reference is invalid", 422)
    for key in ("service_ids", "connection_ids", "source_ids"):
        values = scope[key]
        if not isinstance(values, list) or len(values) > 30 or any(not isinstance(v, str) for v in values):
            refuse("invalid_handoff", "Scope references must be bounded UUID lists", 422)
        for value in values:
            _uuid(value)
        if len(values) != len(set(values)):
            refuse("invalid_handoff", "Scope references must be distinct", 422)
    return json.loads(json.dumps({**raw, "deputy": raw.get("deputy")}))


def validate_action(raw: Any) -> dict:
    if not isinstance(raw, dict) or raw.get("action") not in {"accept", "decline"}:
        refuse("invalid_action", "Choose accept or decline", 422)
    fields = {"action", "payload_hash", "round", "expected_state_version"}
    fields.add("runtime_target" if raw["action"] == "accept" else "reason")
    if set(raw) != fields or any(type(raw[key]) is not int or raw[key] < 1
                                for key in ("round", "expected_state_version")):
        refuse("invalid_action", "The action must bind the current hash, round and version", 422)
    digest = raw["payload_hash"]
    if not isinstance(digest, str) or len(digest) != 71 or not digest.startswith("sha256:") or any(
            c not in "0123456789abcdef" for c in digest[7:]):
        refuse("invalid_action", "A canonical payload hash is required", 422)
    if raw["action"] == "accept":
        runtime = raw["runtime_target"]
        if not isinstance(runtime, dict) or runtime.get("kind") not in {"server", "device", "terminal"}:
            refuse("invalid_action", "An explicit runtime target is required", 422)
        allowed = {"kind"} if runtime["kind"] != "device" else {"kind", "device_id", "folder", "profile", "model"}
        if set(runtime) - allowed:
            refuse("invalid_action", "Only declared runtime-target fields are accepted", 422)
        if runtime["kind"] == "device":
            _uuid(runtime.get("device_id"))
            if not isinstance(runtime.get("folder"), str) or not runtime["folder"].strip():
                refuse("invalid_action", "The receiver must choose their device folder", 422)
            if any(not isinstance(v, str) or len(v) > 2000 for v in runtime.values()):
                refuse("invalid_action", "Runtime-target fields must be bounded strings", 422)
    elif not isinstance(raw["reason"], str) or not raw["reason"].strip() or len(raw["reason"]) > 2000:
        refuse("invalid_action", "A bounded personal rejection reason is required", 422)
    return raw
