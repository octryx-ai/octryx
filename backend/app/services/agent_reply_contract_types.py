"""The stored reply contract of an Agent Definition and the result of checking a reply against it, which the turn's
context snapshot stores as ``agent_reply_contract``."""

from typing import Literal, TypedDict

PrimitiveType = Literal["string", "integer", "number", "boolean"]
ReplyCheckStatus = Literal["satisfied", "violated"]
ReplyCheckReason = Literal["agent_reply_contract_invalid", "agent_reply_not_json", "agent_reply_schema_mismatch"]


class PrimitiveField(TypedDict):
    type: PrimitiveType


class ArrayField(TypedDict):
    type: Literal["array"]
    items: PrimitiveField


class ReplySchema(TypedDict):
    type: Literal["object"]
    properties: dict[str, PrimitiveField | ArrayField]
    required: list[str]


class TextContract(TypedDict):
    kind: Literal["text"]


class JsonObjectContract(TypedDict):
    kind: Literal["json_object"]
    schema: ReplySchema


ReplyContract = TextContract | JsonObjectContract


class ReplyCheck(TypedDict):
    kind: Literal["json_object"]
    status: ReplyCheckStatus
    reason: ReplyCheckReason | None  # None exactly when satisfied


__all__ = [
    "ArrayField",
    "JsonObjectContract",
    "PrimitiveField",
    "PrimitiveType",
    "ReplyCheck",
    "ReplyCheckReason",
    "ReplyCheckStatus",
    "ReplyContract",
    "ReplySchema",
    "TextContract",
]
