"""The value bounds of an Evidence index call: exactly the registry's parameter names with bounded values."""

from __future__ import annotations

import math
from typing import Any

from ..access.acl_keys import MAX_SOURCE_PRINCIPALS, AclKey, is_acl_key
from .errors import EvidenceIndexContractError
from .operations import OperationSpec

MAX_STRING_VALUE_CHARS = 16_000
MAX_INT_VALUE = 2**53 - 1
# Vectors: only these parameter names carry one, and only as finite floats of a bounded length.
VECTOR_PARAMETER_NAMES = frozenset({"vector", "embedding"})
MAX_VECTOR_DIMENSIONS = 4096
# String lists: only the product scope, as short product keys.
STRING_LIST_PARAMETER_NAMES = frozenset({"products"})
MAX_STRING_LIST_ITEMS = 8
MAX_STRING_LIST_ITEM_CHARS = 40
# ACL marker lists: only the closed ACL key shapes, one marker plus the source's principals.
ACL_LIST_PARAMETER_NAMES = frozenset({"acl_keys", "principals"})
MAX_ACL_LIST_ITEMS = MAX_SOURCE_PRINCIPALS + 1


def checked_parameters(spec: OperationSpec, parameters: object) -> dict[str, Any]:
    if parameters is None:
        parameters = {}
    if type(parameters) is not dict or frozenset(parameters) != spec.parameters:
        raise EvidenceIndexContractError()
    checked: dict[str, Any] = {}
    for name, value in parameters.items():
        if name in VECTOR_PARAMETER_NAMES:
            checked[name] = _checked_vector(value)
        elif name in STRING_LIST_PARAMETER_NAMES:
            checked[name] = _checked_string_list(value)
        elif name in ACL_LIST_PARAMETER_NAMES:
            checked[name] = _checked_acl_list(value)
        else:
            checked[name] = _checked_scalar(value)
    return checked


def _checked_scalar(value: object) -> str | int:
    if type(value) is str and len(value) <= MAX_STRING_VALUE_CHARS:
        return value
    if type(value) is int and 0 <= value <= MAX_INT_VALUE:
        return value
    raise EvidenceIndexContractError()


def _checked_string_list(value: object) -> list[str]:
    if type(value) is not list or len(value) > MAX_STRING_LIST_ITEMS:
        raise EvidenceIndexContractError()
    if not all(type(item) is str and 0 < len(item) <= MAX_STRING_LIST_ITEM_CHARS for item in value):
        raise EvidenceIndexContractError()
    return list(value)


def _checked_acl_list(value: object) -> list[AclKey]:
    if type(value) is not list or not 0 < len(value) <= MAX_ACL_LIST_ITEMS:
        raise EvidenceIndexContractError()
    if not all(is_acl_key(item) for item in value):
        raise EvidenceIndexContractError()
    return list(value)


def _checked_vector(value: object) -> list[float]:
    if type(value) is not list or not 0 < len(value) <= MAX_VECTOR_DIMENSIONS:
        raise EvidenceIndexContractError()
    if not all(type(item) is float and math.isfinite(item) for item in value):
        raise EvidenceIndexContractError()
    return list(value)


__all__ = [
    "ACL_LIST_PARAMETER_NAMES",
    "MAX_ACL_LIST_ITEMS",
    "MAX_STRING_LIST_ITEMS",
    "MAX_VECTOR_DIMENSIONS",
    "STRING_LIST_PARAMETER_NAMES",
    "VECTOR_PARAMETER_NAMES",
    "checked_parameters",
]
