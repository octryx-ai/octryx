"""The closed catalog of rerankers (the ``Reranker`` port).

A reranker scores (query, passage) pairs jointly and reorders the authorized, fused candidates.
Like embedding spaces, a remote reranker declares the highest data classification it is approved
for, because the query and the candidate passages leave the process.

Local rerankers: none yet. The fastembed multilingual candidate
(``jinaai/jina-reranker-v2-base-multilingual``) is licensed CC-BY-NC-4.0, which is non-commercial,
and the MIT-licensed ``BAAI/bge-reranker-base`` is essentially English and Chinese. A licence-clean
multilingual local reranker (e.g. ``BAAI/bge-reranker-v2-m3``, Apache-2.0) is evaluated on the golden
set before it is pinned here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType

_KEY = re.compile(r"^[a-z][a-z0-9_]{2,40}_v[0-9]+$")


@dataclass(frozen=True, slots=True)
class RerankerSpec:
    key: str
    provider: str
    model: str
    data_policy_class: str
    max_documents: int
    max_document_chars: int
    # A candidate below this relevance is dropped: it is not evidence for the question.
    min_relevance: float

    def __post_init__(self) -> None:
        if not _KEY.fullmatch(self.key) or self.provider != "bedrock" or not self.data_policy_class:
            raise ValueError("reranker spec is outside the catalog rules")
        if not 1 <= self.max_documents <= 1000 or not 0.0 <= self.min_relevance < 1.0:
            raise ValueError("reranker bounds are outside the supported range")


_RERANKERS = (
    RerankerSpec(
        key="bedrock_cohere_rerank35_v1",
        provider="bedrock",
        model="cohere.rerank-v3-5:0",
        data_policy_class="internal",
        max_documents=100,
        max_document_chars=4000,
        # With a German query and English passages the answer scored 0.735, the noise
        # 0.047 and 0.014. Tuned on the golden set.
        min_relevance=0.1,
    ),
)

RERANKERS = MappingProxyType({spec.key: spec for spec in _RERANKERS})


def reranker_spec(key: object) -> RerankerSpec:
    spec = RERANKERS.get(key) if type(key) is str else None
    if spec is None:
        raise KeyError("unknown reranker")
    return spec


__all__ = ["RERANKERS", "RerankerSpec", "reranker_spec"]
