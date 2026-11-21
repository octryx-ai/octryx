"""The registered vector-search operation and parameters for one retrieval request."""

from __future__ import annotations

from ..evidence_index.operations import (
    SEARCH_EVIDENCE_VECTOR,
    SEARCH_EVIDENCE_VECTOR_SCOPED,
    SEARCH_EVIDENCE_VECTOR_SCOPED_VERSION,
)
from .contracts import RetrievalRequest


def vector_operation(request: RetrievalRequest, space_key: str, vector: list[float]) -> tuple[str, dict]:
    """The nearest ``limit_per_mode`` spans of one space the request's ACL keys and scope admit."""
    parameters: dict[str, object] = {
        "space": space_key,
        "vector": vector,
        "principals": list(request.acl_keys),
        "k": request.limit_per_mode,
    }
    if not request.products:
        return SEARCH_EVIDENCE_VECTOR, parameters
    parameters["products"] = list(request.products)
    if request.version is None:
        return SEARCH_EVIDENCE_VECTOR_SCOPED, parameters
    parameters["version"] = request.version
    return SEARCH_EVIDENCE_VECTOR_SCOPED_VERSION, parameters
