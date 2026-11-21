"""The weak coding model families as an admin-editable list (W22b, R3).

A runtime whose model id contains one of these families is not coding-capable unless an admin
tagged the runtime target with the ``coding`` capability explicitly
(``services/session/turn_runtime_requirement``); pre-dispatch compaction also treats such a model
as a fast tier. The seed is ``model_family_policy.WEAK_CODING_MODEL_FAMILIES``.

Closed validation: ``invalid_payload`` (not a list of strings), ``invalid_entry`` (a family
outside ``[a-z0-9][a-z0-9._:/-]{2,63}``; at least three characters, because a family matches as
a substring of the model id and a one- or two-letter family would match almost every model),
``duplicate_entry``. An empty list is allowed: it declares that no model family is weak.
"""

from __future__ import annotations

import re
from typing import Any

from ..model_family_policy import WEAK_CODING_MODEL_FAMILIES
from .errors import INVALID_ENTRY, INVALID_PAYLOAD, PolicyListError, refuse_duplicates
from .records import PolicyListSpec

_FAMILY = re.compile(r"^[a-z0-9][a-z0-9._:/\-]{2,63}$")


def _read(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(item, str) and _FAMILY.fullmatch(item) for item in raw):
        raise ValueError("families")
    return list(raw)


WEAK_MODEL_FAMILIES_SPEC = PolicyListSpec(
    list_id="weak_coding_model_families",
    config_key="policy.weak_coding_model_families",
    key_prefix="weak_coding_model_families",
    title="Weak coding model families",
    description=(
        "Model families (matched as part of the model id) that are not coding-capable unless the runtime "
        "target carries the coding capability tag."
    ),
    seed_values=lambda: list(WEAK_CODING_MODEL_FAMILIES),
    read_values=_read,
)


def validate_weak_model_families(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise PolicyListError(INVALID_PAYLOAD, "values must be a list of model family names.")
    families = [item.strip().lower() for item in raw if item.strip()]
    invalid = [family for family in families if not _FAMILY.fullmatch(family)]
    if invalid:
        raise PolicyListError(
            INVALID_ENTRY, "A model family is 3-64 characters of a-z, 0-9 and . _ : / -.", invalid
        )
    refuse_duplicates(families, what="The family list")
    return families


__all__ = ["WEAK_MODEL_FAMILIES_SPEC", "validate_weak_model_families"]
