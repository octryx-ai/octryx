"""Storage-neutral retrieval request, evidence, and Retrieval Bundle types. Bounds are enforced at construction; nested
values are revalidated fresh."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from enum import StrEnum

from ..access.acl_keys import MAX_READER_KEYS, PUBLIC_ACL_KEY, AclKey, is_principal_key
from ..identity.workspace import WorkspaceId
from ..objects.source_object import SourceObjectRef
from ..text_safety import has_unsafe_chars
from .errors import InvalidRetrievalRequestError, WorkspaceRequiredError

MAX_QUERY_CHARS = 2000
MIN_LIMIT_PER_MODE = 1
MAX_LIMIT_PER_MODE = 50
DEFAULT_LIMIT_PER_MODE = 8
MAX_EVIDENCE_TEXT_CHARS = 8000
MAX_CITATION_CHARS = 512
MAX_EVIDENCE_ID_CHARS = 128

# Opaque product evidence ids. The alphabet deliberately excludes ``#`` and
# whitespace, and the bare record-id shape (``#12:0`` or ``12:0``) is rejected
# separately, so a database record id cannot pass as an evidence id.
MAX_SCOPE_PRODUCTS = 8
_PRODUCT_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_VERSION_TOKEN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,39}$")
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_RECORD_ID = re.compile(r"^#?-?[0-9]+:-?[0-9]+$")


class RetrievalMode(StrEnum):
    LEXICAL = "lexical"
    VECTOR = "vector"
    GRAPH = "graph"


class EvidenceKind(StrEnum):
    PASSAGE = "passage"
    ENTITY = "entity"
    RELATION = "relation"


def _validated_limit(limit: object) -> int:
    # Exact int: excludes bool (``True`` must not mean limit 1) and subclasses
    # whose comparison operators could pass the bounds check.
    if type(limit) is not int:
        raise InvalidRetrievalRequestError()
    if not MIN_LIMIT_PER_MODE <= limit <= MAX_LIMIT_PER_MODE:
        raise InvalidRetrievalRequestError()
    return limit


def _validated_modes(raw: object) -> frozenset[RetrievalMode]:
    if isinstance(raw, str | bytes):
        raise InvalidRetrievalRequestError()
    try:
        # Materialize first: a generator is truthy even when it yields nothing.
        modes = frozenset(RetrievalMode(mode) for mode in raw)  # type: ignore[attr-defined]
    except (TypeError, ValueError):
        raise InvalidRetrievalRequestError() from None
    if not modes:
        raise InvalidRetrievalRequestError()
    return modes


def _validated_score(score: object) -> float | None:
    if score is None:
        return None
    if isinstance(score, bool) or not isinstance(score, int | float):
        raise InvalidRetrievalRequestError()
    try:
        # Convert once, then check the converted value; a huge int overflows
        # float conversion, which is invalid, not a crash.
        value = float(score)
    except OverflowError:
        raise InvalidRetrievalRequestError() from None
    if not math.isfinite(value):
        raise InvalidRetrievalRequestError()
    return value


def is_valid_evidence_id(evidence_id: object) -> bool:
    return (
        type(evidence_id) is str
        and len(evidence_id) <= MAX_EVIDENCE_ID_CHARS
        and bool(_EVIDENCE_ID.fullmatch(evidence_id))
        and not _RECORD_ID.fullmatch(evidence_id)
    )


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    # ``query_text`` is data for ranking only; stores must never interpret it as query language.
    workspace: WorkspaceId
    query_text: str
    modes: frozenset[RetrievalMode]
    limit_per_mode: int = DEFAULT_LIMIT_PER_MODE
    # Product and version narrowing: labels inside the Workspace, validated here so a store
    # only ever sees a bounded tuple of product keys and a version that is scoped by a product.
    products: tuple[str, ...] = ()
    version: str | None = None
    # Source ACL keys this request admits: always ``public`` first, then at most
    # ``MAX_READER_KEYS`` principal keys of the calling user. The default admits public spans only.
    acl_keys: tuple[AclKey, ...] = (PUBLIC_ACL_KEY,)

    def __post_init__(self) -> None:
        if self.workspace is None:
            raise WorkspaceRequiredError()
        object.__setattr__(self, "workspace", WorkspaceId.parse(self.workspace))
        if type(self.query_text) is not str:
            raise InvalidRetrievalRequestError()
        query_text = self.query_text.strip()
        if not query_text or len(query_text) > MAX_QUERY_CHARS:
            raise InvalidRetrievalRequestError()
        if has_unsafe_chars(query_text, allow_line_breaks=True):
            raise InvalidRetrievalRequestError()
        object.__setattr__(self, "query_text", query_text)
        object.__setattr__(self, "modes", _validated_modes(self.modes))
        _validated_limit(self.limit_per_mode)
        if type(self.products) is not tuple or len(self.products) > MAX_SCOPE_PRODUCTS:
            raise InvalidRetrievalRequestError()
        if not all(type(product) is str and _PRODUCT_KEY.fullmatch(product) for product in self.products):
            raise InvalidRetrievalRequestError()
        if self.version is not None and (
            not self.products or type(self.version) is not str or not _VERSION_TOKEN.fullmatch(self.version)
        ):
            # A version is a subject version *of a product*; alone it would mix products.
            raise InvalidRetrievalRequestError()
        if (
            type(self.acl_keys) is not tuple
            or not 0 < len(self.acl_keys) <= MAX_READER_KEYS + 1
            or self.acl_keys[0] != PUBLIC_ACL_KEY
            or not all(is_principal_key(key) for key in self.acl_keys[1:])
        ):
            # Never ``restricted``: that marker is admitted by no request.
            raise InvalidRetrievalRequestError()

    @property
    def ordered_modes(self) -> tuple[RetrievalMode, ...]:
        return tuple(mode for mode in RetrievalMode if mode in self.modes)


@dataclass(frozen=True, slots=True)
class Evidence:
    # A bundle accepts only evidence owned by its request's Workspace.
    workspace: WorkspaceId
    evidence_id: str
    mode: RetrievalMode
    kind: EvidenceKind
    text: str
    score: float | None = None
    citation: str | None = None
    source: SourceObjectRef | None = None

    def __post_init__(self) -> None:
        if type(self.workspace) is not WorkspaceId:
            raise InvalidRetrievalRequestError()
        # Fresh, revalidated copy: the caller's instance may be shared or mutated.
        object.__setattr__(self, "workspace", WorkspaceId.parse(self.workspace))
        if not is_valid_evidence_id(self.evidence_id):
            raise InvalidRetrievalRequestError()
        try:
            object.__setattr__(self, "mode", RetrievalMode(self.mode))
            object.__setattr__(self, "kind", EvidenceKind(self.kind))
        except (TypeError, ValueError):
            raise InvalidRetrievalRequestError() from None
        if (
            type(self.text) is not str
            or not self.text.strip()
            or len(self.text) > MAX_EVIDENCE_TEXT_CHARS
            or has_unsafe_chars(self.text, allow_line_breaks=True)
        ):
            raise InvalidRetrievalRequestError()
        object.__setattr__(self, "score", _validated_score(self.score))
        if self.citation is not None and (
            type(self.citation) is not str
            or not self.citation.strip()
            or len(self.citation) > MAX_CITATION_CHARS
            or has_unsafe_chars(self.citation, allow_line_breaks=False)
        ):
            raise InvalidRetrievalRequestError()
        if self.source is not None:
            if type(self.source) is not SourceObjectRef:
                raise InvalidRetrievalRequestError()
            # Fresh, revalidated copy, for the same reason as ``workspace``.
            object.__setattr__(self, "source", replace(self.source))


@dataclass(frozen=True, slots=True)
class RetrievalBundle:
    request: RetrievalRequest
    evidence: tuple[Evidence, ...]

    def __post_init__(self) -> None:
        if type(self.request) is not RetrievalRequest:
            raise InvalidRetrievalRequestError()
        evidence = tuple(self.evidence)
        if not all(type(item) is Evidence for item in evidence):
            raise InvalidRetrievalRequestError()
        # Exactly one Workspace per bundle: foreign-owned evidence never passes.
        if any(item.workspace != self.request.workspace for item in evidence):
            raise InvalidRetrievalRequestError()
        if any(item.mode not in self.request.modes for item in evidence):
            raise InvalidRetrievalRequestError()
        per_mode = Counter(item.mode for item in evidence)
        if any(count > self.request.limit_per_mode for count in per_mode.values()):
            raise InvalidRetrievalRequestError()
        if len({(item.mode, item.evidence_id) for item in evidence}) != len(evidence):
            raise InvalidRetrievalRequestError()
        object.__setattr__(self, "evidence", evidence)

    @property
    def workspace(self) -> WorkspaceId:
        return self.request.workspace

    def for_mode(self, mode: RetrievalMode) -> tuple[Evidence, ...]:
        return tuple(item for item in self.evidence if item.mode == mode)
