"""Contract: authoring validation, strict reply check and prompt rendering of a reply contract."""

from __future__ import annotations

import json

import pytest

from app.services.agent_reply_contract_check import check_reply
from app.services.agent_reply_contract_schema import MAX_FIELDS, ReplyContractError, normalize_reply_contract


def _contract(properties=None, required=None):
    properties = {"sum": {"type": "integer"}, "note": {"type": "string"}} if properties is None else properties
    return {"kind": "json_object",
            "schema": {"type": "object", "properties": properties, "required": ["sum"] if required is None else required}}


def test_valid_contracts_normalize_canonically():
    assert normalize_reply_contract({"kind": "text"}) == {"kind": "text"}
    contract = _contract({
        "sum": {"type": "integer"}, "ratio": {"type": "number"}, "ok": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}}, "snake_Case9": {"type": "string"},
    }, ["sum", "tags"])
    assert normalize_reply_contract(contract) == contract
    assert normalize_reply_contract(_contract(required=[]))["schema"]["required"] == []
    without_required = {"kind": "json_object", "schema": {"type": "object", "properties": {"a": {"type": "string"}}}}
    assert normalize_reply_contract(without_required)["schema"]["required"] == []
    many = {f"f{index}": {"type": "string"} for index in range(MAX_FIELDS)}
    assert len(normalize_reply_contract(_contract(many, []))["schema"]["properties"]) == MAX_FIELDS


@pytest.mark.parametrize("value", [
    None, "text", [], {}, {"kind": "markdown"}, {"kind": "text", "schema": {}},
    {"kind": "json_object"}, {"kind": "json_object", "schema": {}, "extra": 1},
    {"kind": "json_object", "schema": {"type": "array", "properties": {"a": {"type": "string"}}}},
    {"kind": "json_object", "schema": {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}},
    {"kind": "json_object", "schema": {"type": "object", "properties": {"a": {"type": "string"}}, "$ref": "#/x"}},
    _contract({}),
    _contract({f"f{index}": {"type": "string"} for index in range(MAX_FIELDS + 1)}, []),
    _contract({"Sum": {"type": "integer"}}, []),
    _contract({"1sum": {"type": "integer"}}, []),
    _contract({"a" * 65: {"type": "integer"}}, []),
    _contract({"sum": {"type": "object"}}, []),
    _contract({"sum": {"schemaRef": "Other"}}, []),
    _contract({"sum": {"type": "string", "enum": ["a"]}}, []),
    _contract({"sum": {"type": "string", "description": "x"}}, []),
    _contract({"sum": {"type": "string", "pattern": "^a$"}}, []),
    _contract({"sum": {"type": "array"}}, []),
    _contract({"sum": {"type": "array", "items": {"type": "object"}}}, []),
    _contract({"sum": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}}, []),
    _contract({"sum": {"type": "integer", "items": {"type": "string"}}}, []),
    _contract(required=["missing"]),
    _contract(required=["sum", "sum"]),
    _contract(required="sum"),
    _contract(required=[1]),
    {"kind": "json_object", "schema": {"type": "object", "properties": {"a": {"type": "string"}}, "x": "y" * 17000}},
])
def test_invalid_contracts_are_refused_without_echoing_input(value):
    with pytest.raises(ReplyContractError) as refused:
        normalize_reply_contract(value)
    assert "y" * 20 not in str(refused.value) and "pattern" not in str(refused.value)


def test_an_oversized_contract_is_refused_before_schema_parsing():
    huge = _contract({f"f{index}": {"type": "string"} for index in range(MAX_FIELDS)}, [])
    huge["schema"]["properties"]["f0"] = {"type": "string", "padding": "x" * 20000}
    with pytest.raises(ReplyContractError, match="16 KiB"):
        normalize_reply_contract(huge)


SATISFIED = {"kind": "json_object", "status": "satisfied", "reason": None}


def _violated(reason):
    return {"kind": "json_object", "status": "violated", "reason": reason}


@pytest.mark.parametrize("reply", [
    '{"sum": 37}', '  \n{"sum": 37, "note": "ok"}\n ', '{"sum": 37, "extra": [1, {"x": null}]}',
    '{"sum": -0}', '{"sum": 37, "note": "<thinking>quoted</thinking>"}',
])
def test_a_matching_reply_is_satisfied(reply):
    assert check_reply(_contract(), reply) == SATISFIED


@pytest.mark.parametrize(("reply", "reason"), [
    ('```json\n{"sum": 37}\n```', "agent_reply_not_json"),
    ('Here it is: {"sum": 37}', "agent_reply_not_json"),
    ('{"sum": 37} done', "agent_reply_not_json"),
    ('<thinking>x</thinking>\n{"sum": 37}', "agent_reply_not_json"),
    ('{"sum": 37, "sum": 38}', "agent_reply_not_json"),
    ('{"sum": NaN}', "agent_reply_not_json"),
    ('{"sum": Infinity}', "agent_reply_not_json"),
    ('{"sum": 1e400}', "agent_reply_not_json"),
    ("SUM=37", "agent_reply_not_json"),
    ("", "agent_reply_not_json"),
    (None, "agent_reply_not_json"),
    ('[{"sum": 37}]', "agent_reply_schema_mismatch"),
    ('"text"', "agent_reply_schema_mismatch"),
    ('{"note": "no sum"}', "agent_reply_schema_mismatch"),
    ('{"sum": "37"}', "agent_reply_schema_mismatch"),
    ('{"sum": 37.0}', "agent_reply_schema_mismatch"),
    ('{"sum": true}', "agent_reply_schema_mismatch"),
    ('{"sum": 37, "note": 5}', "agent_reply_schema_mismatch"),
])
def test_a_non_matching_reply_is_violated_with_a_fixed_reason(reply, reason):
    assert check_reply(_contract(), reply) == _violated(reason)


_HUGE = "9" * 400


@pytest.mark.parametrize(("field", "reply"), [
    ({"type": "number"}, f'{{"x": {_HUGE}}}'),
    ({"type": "number"}, f'{{"x": -{_HUGE}}}'),
    ({"type": "array", "items": {"type": "number"}}, f'{{"x": [1, {_HUGE}]}}'),
    ({"type": "integer"}, f'{{"x": {_HUGE}}}'),
    ({"type": "array", "items": {"type": "integer"}}, f'{{"x": [{_HUGE}]}}'),
    ({"type": "string"}, f'{{"x": "a", "undeclared": {_HUGE}}}'),
    ({"type": "number"}, '{"x": ' + "9" * 5000 + "}"),
])
def test_integers_outside_float_range_are_not_json_and_never_raise(field, reply):
    assert check_reply(_contract({"x": field}, ["x"]), reply) == _violated("agent_reply_not_json")


def test_large_integers_inside_float_range_still_match():
    assert check_reply(_contract({"x": {"type": "number"}}, ["x"]), '{"x": ' + "9" * 300 + "}") == SATISFIED
    assert check_reply(_contract({"x": {"type": "integer"}}, ["x"]), '{"x": 9007199254740993}') == SATISFIED


def test_pathologically_nested_json_is_violated_without_raising():
    assert check_reply(_contract(), "[" * 100000 + "]" * 100000)["status"] == "violated"


def test_array_and_primitive_field_types_are_checked_exactly():
    contract = _contract({"tags": {"type": "array", "items": {"type": "integer"}}, "ratio": {"type": "number"},
                          "ok": {"type": "boolean"}}, ["tags", "ratio", "ok"])
    assert check_reply(contract, '{"tags": [1, 2], "ratio": 0.5, "ok": false}') == SATISFIED
    assert check_reply(contract, '{"tags": [], "ratio": 2, "ok": true}') == SATISFIED
    for bad in ('{"tags": [1, "2"], "ratio": 0.5, "ok": false}', '{"tags": 1, "ratio": 0.5, "ok": false}',
                '{"tags": [true], "ratio": 0.5, "ok": false}', '{"tags": [1], "ratio": "0.5", "ok": false}',
                '{"tags": [1], "ratio": 0.5, "ok": 0}'):
        assert check_reply(contract, bad) == _violated("agent_reply_schema_mismatch"), bad


def test_text_contract_has_no_marker_and_an_invalid_contract_fails_closed():
    assert check_reply({"kind": "text"}, "anything <thinking>") is None
    for corrupt in (None, "{not json", {"kind": "json_object"}, json.dumps(_contract())):
        assert check_reply(corrupt, '{"sum": 37}') == _violated("agent_reply_contract_invalid")


