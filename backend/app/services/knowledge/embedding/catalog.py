"""The closed catalog of embedding spaces of the ``Embedder`` port. Vectors are compared only inside one space; a
runtime change that alters vectors needs a new version."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class EmbeddingProvider(StrEnum):
    LOCAL = "local"
    BEDROCK = "bedrock"


_SPACE_KEY = re.compile(r"^[a-z][a-z0-9_]{2,40}_v[0-9]+$")


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    key: str
    provider: EmbeddingProvider
    model: str
    dimensions: int
    max_input_chars: int
    # A vector-only hit below this cosine similarity is noise, not evidence. Set per space (each
    # model spreads similarities differently); measured and tuned on the golden set.
    min_similarity: float = 0.3
    # Remote spaces: the highest Workspace classification allowed to reach the provider.
    data_policy_class: str | None = None
    # Instruction prefixes some models require (e.g. E5: "query: " / "passage: ").
    query_prefix: str = ""
    document_prefix: str = ""
    # Local spaces: the pinned artifact (where it is published, which revision, which files).
    artifact_source: str | None = None
    artifact_revision: str | None = None
    artifact_files: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not _SPACE_KEY.fullmatch(self.key):
            raise ValueError("embedding space key is outside the allowed shape")
        if not 1 <= self.dimensions <= 4096 or not 1 <= self.max_input_chars <= 100_000:
            raise ValueError("embedding space bounds are outside the supported range")
        if self.provider is EmbeddingProvider.LOCAL and not self.artifact_files:
            raise ValueError("a local embedding space must pin its artifact")
        if self.provider is not EmbeddingProvider.LOCAL and not self.data_policy_class:
            raise ValueError("a remote embedding space must declare its data classification allowance")


_SPACES = (
    EmbeddingSpace(
        key="local_mlminilm_384_v1",
        provider=EmbeddingProvider.LOCAL,
        model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dimensions=384,
        min_similarity=0.3,
        # 512 word pieces; longer text is truncated by the tokenizer, so spans are bounded upstream.
        max_input_chars=4000,
        artifact_source="qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q",
        artifact_revision="faf4aa4225822f3bc6376869cb1164e8e3feedd0",
        artifact_files=MappingProxyType(
            {
                "config.json": "c8ec081fdad2df991bf5abbf18418fec7a5cdaa421f60ffb060a30040b8c376f",
                "model_optimized.onnx": "634d0f66c29dc934c8fa72b8a4fe91dd4d420a22f1d82a241058d4316e659a99",
                "special_tokens_map.json": "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835",
                "tokenizer.json": "fa685fc160bbdbab64058d4fc91b60e62d207e8dc60b9af5c002c5ab946ded00",
                "tokenizer_config.json": "0666eebf692422757e1dddf3c9fb1ded73ba3dc726c5828671fc89e45bf3609f",
            }
        ),
    ),
    EmbeddingSpace(
        key="bedrock_titan2_1024_v1",
        provider=EmbeddingProvider.BEDROCK,
        model="amazon.titan-embed-text-v2:0",
        dimensions=1024,
        min_similarity=0.25,
        max_input_chars=30_000,
        data_policy_class="internal",
    ),
    EmbeddingSpace(
        key="bedrock_cohere_ml3_1024_v1",
        provider=EmbeddingProvider.BEDROCK,
        model="cohere.embed-multilingual-v3",
        dimensions=1024,
        min_similarity=0.35,
        # Cohere v3 truncates at 512 tokens; the request asks it to cut the end.
        max_input_chars=2048,
        data_policy_class="internal",
    ),
)

EMBEDDING_SPACES = MappingProxyType({space.key: space for space in _SPACES})
if len(EMBEDDING_SPACES) != len(_SPACES):  # a duplicate key would silently shrink the catalog
    raise ValueError("duplicate embedding space key")


def embedding_space(key: object) -> EmbeddingSpace:
    space = EMBEDDING_SPACES.get(key) if type(key) is str else None
    if space is None:
        raise KeyError("unknown embedding space")
    return space


__all__ = ["EMBEDDING_SPACES", "EmbeddingProvider", "EmbeddingSpace", "embedding_space"]
