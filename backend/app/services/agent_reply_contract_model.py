"""The reply contract's schema model and matcher: a small JSON-Schema subset.

An object with typed properties, ``required`` names, string enums, typed arrays and ``schemaRef`` between named
schemas. As in JSON Schema, properties the schema does not declare are allowed. The model is strict (no type
coercion), closed (``extra="forbid"``), immutable and uses camelCase aliases; :func:`matches_named` answers a
boolean on purpose, so no validator text reaches a record.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

_MAX_DEPTH = 16

SchemaName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Za-z0-9]{0,63}$")]
FieldName = Annotated[str, StringConstraints(pattern=r"^[a-z][A-Za-z0-9_]{0,63}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(min_length=1, max_length=8000)]
FieldType = Literal["string", "integer", "number", "boolean", "array", "object"]


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        protected_namespaces=(),
    )


class FieldSchema(_ContractModel):
    """One typed value: either an inline ``type`` or a ``schemaRef``."""

    type: FieldType | None = None
    schema_ref: SchemaName | None = None
    enum: list[ShortText] | None = Field(default=None, min_length=1)
    items: FieldSchema | None = None
    description: LongText | None = None

    @model_validator(mode="after")
    def _consistent(self) -> FieldSchema:
        if (self.type is None) == (self.schema_ref is None):
            raise ValueError("a field needs exactly one of 'type' or 'schemaRef'")
        if self.enum is not None:
            if self.type != "string":
                raise ValueError("'enum' is only allowed on type 'string'")
            if len(set(self.enum)) != len(self.enum):
                raise ValueError("enum values must be distinct")
        if (self.type == "array") != (self.items is not None):
            raise ValueError("'items' is required on type 'array' and only allowed there")
        return self


class NamedSchema(_ContractModel):
    type: Literal["object"]
    properties: dict[FieldName, FieldSchema] = Field(min_length=1)
    required: list[FieldName] = Field(default_factory=list)
    description: LongText | None = None

    @model_validator(mode="after")
    def _required_declared(self) -> NamedSchema:
        undeclared = sorted(set(self.required) - set(self.properties))
        if undeclared:
            raise ValueError(f"required names undeclared properties: {', '.join(undeclared)}")
        return self


def matches_named(value: Any, name: str, schemas: Mapping[str, NamedSchema], depth: int = 0) -> bool:
    schema = schemas.get(name)
    if schema is None or depth > _MAX_DEPTH or not isinstance(value, dict):
        return False
    if any(required not in value for required in schema.required):
        return False
    return all(
        matches_field(value[key], field, schemas, depth + 1) for key, field in schema.properties.items() if key in value
    )


def matches_field(value: Any, field: FieldSchema, schemas: Mapping[str, NamedSchema], depth: int) -> bool:
    if field.schema_ref is not None:
        return matches_named(value, field.schema_ref, schemas, depth)
    kind = field.type
    if kind == "string":
        return isinstance(value, str) and (field.enum is None or value in field.enum)
    if kind == "integer":
        return type(value) is int
    if kind == "number":
        return type(value) in (int, float) and math.isfinite(value)
    if kind == "boolean":
        return type(value) is bool
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        items = field.items
        return (
            isinstance(value, list)
            and items is not None
            and depth <= _MAX_DEPTH
            and all(matches_field(item, items, schemas, depth + 1) for item in value)
        )
    return False


__all__ = ["FieldSchema", "NamedSchema", "matches_field", "matches_named"]
