"""Closed, bounded additive specification proposals; server lineage is never model input."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from ...knowledge.retrieval.contracts import is_valid_evidence_id

KINDS = ("idea_frame", "research_plan", "research_brief", "spec")
TOOLS = {kind: f"submit_{kind}" for kind in KINDS}


def text(limit: int) -> dict:
    return {"type": "string", "minLength": 1, "maxLength": limit}


def items(value: dict, minimum=0, maximum=10, *, unique=False) -> dict:
    return {"type": "array", "items": value, "minItems": minimum, "maxItems": maximum,
            **({"uniqueItems": True} if unique else {})}


def obj(**properties) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def identifier(prefix: str) -> dict:
    return {**text(7), "pattern": f"^{prefix}[1-9][0-9]{{0,2}}$"}


KEY = {**text(128), "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"}
QUESTION = obj(id=identifier("Q"), text=text(500))
CLAIMS = items(obj(id=identifier("CL"), text=text(1000),
                   evidence_keys=items(KEY, 1, 8, unique=True)), 1, 20)
CONTRADICTIONS = items(obj(claim_ids=items(identifier("CL"), 2, 8, unique=True), summary=text(1000)))
UNCERTAINTY = items(obj(claim_ids=items(identifier("CL"), 0, 8, unique=True), text=text(1000)))
SCHEMAS = {
    "idea_frame": obj(schema_version={"const": "idea_frame/v1"}, summary=text(1000), problem=text(1000),
        desired_outcome=text(1000), scope=obj(in_scope=items(text(500), 1), out_of_scope=items(text(500))),
        constraints=items(text(500)), open_questions=items(QUESTION),
        deferred_questions=items(obj(id=identifier("Q"), text=text(500), reason=text(1000)))),
    "research_plan": obj(schema_version={"const": "research_plan/v1"},
        questions=items(obj(id=identifier("RQ"), text=text(500)), 1),
        source_kinds={"const": ["knowledge"]}, egress={"const": "none"}),
    "research_brief": obj(schema_version={"const": "research_brief/v1"}, summary=text(2000),
        claims=CLAIMS, contradictions=CONTRADICTIONS, uncertainty=UNCERTAINTY),
    "spec": obj(schema_version={"const": "spec/v1"}, summary=text(1000),
        stories=items(obj(id=identifier("ST"), as_a=text(300), i_want=text(500), so_that=text(500)), 1),
        criteria=items(obj(id=identifier("AC"), story_ids=items(identifier("ST"), 1, 10, unique=True),
                           given=text(1000), when=text(1000), then=text(1000)), 1, 20),
        nfrs=items(obj(id=identifier("NFR"), text=text(1000))),
        risks=items(obj(id=identifier("RISK"), text=text(1000))),
        documentation_audience=obj(semantics={"const": "workspace_readers"}, description=text(500)),
        claims=CLAIMS, contradictions=CONTRADICTIONS, uncertainty=UNCERTAINTY, open_questions=items(QUESTION)),
}
SERVER_FIELDS = {"idea_frame": set(), "research_plan": {"idea_frame_ref", "budget"},
                 "research_brief": {"research_plan_ref", "evidence"},
                 "spec": {"idea_frame_ref", "research_brief_ref", "evidence"}}


def _check(value: Any, schema: dict, path: str, errors: list[str]) -> None:
    if "const" in schema:
        if type(value) is not type(schema["const"]) or value != schema["const"]:
            errors.append(f"{path}: unexpected value")
        return
    kind = schema["type"]
    if kind == "object":
        if type(value) is not dict:
            errors.append(f"{path}: expected object")
            return
        if set(value) != set(schema["properties"]):
            errors.append(f"{path}: missing or unknown fields")
        for key, subschema in schema["properties"].items():
            if key in value:
                _check(value[key], subschema, f"{path}.{key}", errors)
    elif kind == "array":
        if type(value) is not list or not schema["minItems"] <= len(value) <= schema["maxItems"]:
            errors.append(f"{path}: invalid list size or type")
            return
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            errors.append(f"{path}: duplicate values")
        for index, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{index}]", errors)
    elif (type(value) is not str or not value.strip() or "\x00" in value
          or not schema["minLength"] <= len(value) <= schema["maxLength"]
          or ("pattern" in schema and re.fullmatch(schema["pattern"], value) is None)):
        errors.append(f"{path}: invalid text")


def _semantic(record: dict, errors: list[str]) -> None:
    for name in ("questions", "open_questions", "deferred_questions", "claims", "stories", "criteria", "nfrs", "risks"):
        rows = record.get(name, [])
        ids = [row["id"] for row in rows]
        if len(set(ids)) != len(ids):
            errors.append(f"{name}: duplicate ids")
    question_ids = [q["id"] for name in ("open_questions", "deferred_questions") for q in record.get(name, [])]
    if len(set(question_ids)) != len(question_ids):
        errors.append("questions: duplicate ids across collections")
    claims = {claim["id"] for claim in record.get("claims", [])}
    for row in record.get("contradictions", []) + record.get("uncertainty", []):
        if not set(row["claim_ids"]) <= claims:
            errors.append("claims: unknown reference")
    stories = {story["id"] for story in record.get("stories", [])}
    for criterion in record.get("criteria", []):
        if not set(criterion["story_ids"]) <= stories:
            errors.append("criteria: unknown story")
    for claim in record.get("claims", []):
        if not all(is_valid_evidence_id(key) for key in claim["evidence_keys"]):
            errors.append("claims: invalid Knowledge key")


def validate_proposal(kind: str, raw: Any) -> tuple[dict, list[str]]:
    errors: list[str] = []
    try:
        encoded = json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return {}, ["proposal: invalid JSON"]
    if kind not in SCHEMAS or len(encoded) > 65536:
        return {}, ["proposal: unknown kind or size exceeds 65536 bytes"]
    _check(raw, SCHEMAS[kind], kind, errors)
    if not errors:
        _semantic(raw, errors)
    return (copy.deepcopy(raw), []) if not errors else ({}, errors)


def proposal_from_record(kind: str, record: Any) -> tuple[dict, list[str]]:
    if type(record) is not dict or kind not in SERVER_FIELDS:
        return {}, ["record: invalid shape"]
    if set(record) != set(SCHEMAS[kind]["properties"]) | SERVER_FIELDS[kind]:
        return {}, ["record: missing or unknown server fields"]
    return validate_proposal(kind, {key: value for key, value in record.items() if key not in SERVER_FIELDS[kind]})


def used_keys(record: dict) -> list[str]:
    return sorted({key for claim in record.get("claims", []) for key in claim["evidence_keys"]})


def record_readiness(kind: str, record: Any) -> tuple[bool, str]:
    """Shape and explicit open questions only; current refs/ACL/review are separate server checks."""
    _, errors = proposal_from_record(kind, record)
    if errors:
        return False, "The current specification output is invalid."
    if record.get("open_questions"):
        return False, "Resolve the open questions before confirmation."
    return True, "The output has no blocking open questions; current lineage still requires server validation."
