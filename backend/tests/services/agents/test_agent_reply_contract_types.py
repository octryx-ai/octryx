from __future__ import annotations

from typing import get_args

import pytest

from app.services.agent_reply_contract_check import check_reply
from app.services.agent_reply_contract_schema import (
    KIND_JSON_OBJECT,
    KIND_TEXT,
    PRIMITIVE_TYPES,
    REASON_CONTRACT_INVALID,
    REASON_NOT_JSON,
    REASON_SCHEMA_MISMATCH,
    STATUS_SATISFIED,
    STATUS_VIOLATED,
    normalize_reply_contract,
)
from app.services.agent_reply_contract_types import (
    PrimitiveType,
    ReplyCheck,
    ReplyCheckReason,
    ReplyCheckStatus,
    ReplyContract,
)
from tests.typed_dict_support import shape_problems

CHECKED = {"kind": "json_object", "schema": {"type": "object", "required": ["title"], "properties": {
    "title": {"type": "string"}, "count": {"type": "integer"}, "tags": {"type": "array", "items": {"type": "string"}},
    "score": {"type": "number"}, "done": {"type": "boolean"}}}}


@pytest.mark.parametrize("contract", [{"kind": "text"}, CHECKED,
                                      {"kind": "json_object", "schema": {"type": "object",
                                                                         "properties": {"a": {"type": "string"}}}}])
def test_a_normalized_contract_is_a_reply_contract(contract):
    assert shape_problems(normalize_reply_contract(contract), ReplyContract, "contract") == []


@pytest.mark.parametrize(("contract", "reply"), [
    (CHECKED, '{"title": "x", "count": 2}'),
    (CHECKED, "not json"),
    (CHECKED, '{"count": 2}'),
    (CHECKED, "[1]"),
    (CHECKED, None),
    ({"kind": "json_object"}, "{}"),
])
def test_every_check_result_is_a_reply_check(contract, reply):
    result = check_reply(contract, reply)
    assert shape_problems(result, ReplyCheck, "result") == []
    assert (result["reason"] is None) == (result["status"] == STATUS_SATISFIED)


def test_a_text_contract_has_no_check_result():
    assert check_reply({"kind": "text"}, "anything") is None


def test_the_reply_contract_vocabularies_are_the_constants_the_code_uses():
    assert get_args(PrimitiveType) == PRIMITIVE_TYPES
    assert set(get_args(ReplyCheckStatus)) == {STATUS_SATISFIED, STATUS_VIOLATED}
    assert set(get_args(ReplyCheckReason)) == {REASON_CONTRACT_INVALID, REASON_NOT_JSON, REASON_SCHEMA_MISMATCH}
    assert {KIND_TEXT, KIND_JSON_OBJECT} == {"text", "json_object"}
